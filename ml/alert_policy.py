"""Simple explainable risk levels and persistence-aware alert logic.

The policy is intended for a hackathon decision-support demonstration.  It is
not clinically validated and operates only on the supplied chronological risk
sequence (currently the supported 6h, 12h, and 24h model checkpoints).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal


RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]
AlertState = Literal["NO_ALERT", "WATCH", "HIGH_ALERT"]

RISK_ORDER: dict[RiskLevel, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _validate_thresholds(medium_threshold: float, high_threshold: float) -> None:
    if not 0 <= medium_threshold < high_threshold <= 1:
        raise ValueError(
            "Risk thresholds must satisfy "
            "0 <= medium_threshold < high_threshold <= 1"
        )


def probability_to_risk_level(
    probability: float,
    medium_threshold: float,
    high_threshold: float,
) -> RiskLevel:
    """Map one probability to a deterministic LOW/MEDIUM/HIGH level."""
    _validate_thresholds(medium_threshold, high_threshold)
    if not 0 <= probability <= 1:
        raise ValueError("Probability must lie in [0, 1]")
    if probability >= high_threshold:
        return "HIGH"
    if probability >= medium_threshold:
        return "MEDIUM"
    return "LOW"


def risk_history_to_alert_state(risk_history: Sequence[RiskLevel]) -> AlertState:
    """Return the current alert state from chronological risk levels.

    Policy:
      * LOW now -> NO_ALERT.
      * One isolated MEDIUM or HIGH -> WATCH.
      * Two consecutive MEDIUM-or-higher checkpoints -> HIGH_ALERT.

    Thus a high alert requires persistent elevated risk or worsening from
    MEDIUM to HIGH; one isolated spike surrounded by LOW remains a WATCH.
    """
    if not risk_history:
        return "NO_ALERT"
    invalid = [level for level in risk_history if level not in RISK_ORDER]
    if invalid:
        raise ValueError(f"Unknown risk level(s): {invalid}")

    current = risk_history[-1]
    if current == "LOW":
        return "NO_ALERT"
    if len(risk_history) >= 2 and RISK_ORDER[risk_history[-2]] >= 1:
        return "HIGH_ALERT"
    return "WATCH"


def probabilities_to_alert_timeline(
    probabilities: Sequence[float | None],
    medium_threshold: float,
    high_threshold: float,
) -> list[dict[str, str | float | None]]:
    """Evaluate each prefix; missing assessments break alert persistence."""
    _validate_thresholds(medium_threshold, high_threshold)
    levels: list[RiskLevel] = []
    timeline: list[dict[str, str | float | None]] = []
    for probability in probabilities:
        if probability is None:
            levels.clear()
            timeline.append({
                "probability": None, "risk_level": None, "alert_state": None,
            })
            continue
        level = probability_to_risk_level(
            probability, medium_threshold, high_threshold,
        )
        levels.append(level)
        timeline.append(
            {
                "probability": float(probability),
                "risk_level": level,
                "alert_state": risk_history_to_alert_state(levels),
            }
        )
    return timeline
