"""Tests for development-only OOF threshold analysis and alert policy."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.alert_policy import (
    probabilities_to_alert_timeline,
    probability_to_risk_level,
    risk_history_to_alert_state,
)
from ml.threshold_analysis import (
    analyze_development_oof_thresholds,
    calculate_threshold_metrics,
    generate_oof_predictions,
    select_operating_points,
    validate_development_oof_predictions,
)


def _oof(patient_ids=(1, 2, 3, 4)):
    return pd.DataFrame(
        {
            "patient_id": patient_ids,
            "y_true": [0, 0, 1, 1],
            "y_prob": [0.1, 0.6, 0.4, 0.9],
            "fold": [1, 2, 1, 2],
        }
    )


class TestOOFIntegrity:
    def test_exact_development_cohort_is_accepted(self):
        validate_development_oof_predictions(_oof(), [1, 2, 3, 4], [5, 6])

    def test_holdout_id_cannot_enter_threshold_analysis(self):
        predictions = _oof(patient_ids=(1, 2, 3, 5))
        with pytest.raises(ValueError, match="Held-out"):
            analyze_development_oof_thresholds(
                predictions, [1, 2, 3, 4], [5, 6], [0.5],
            )

    def test_missing_development_patient_is_rejected(self):
        with pytest.raises(ValueError, match="development cohort exactly"):
            validate_development_oof_predictions(
                _oof().iloc[:3], [1, 2, 3, 4], [5, 6],
            )

    def test_duplicate_patient_prediction_is_rejected(self):
        predictions = _oof()
        predictions.loc[3, "patient_id"] = 3
        with pytest.raises(ValueError, match="exactly one OOF"):
            validate_development_oof_predictions(
                predictions, [1, 2, 3, 4], [5, 6],
            )

    def test_oof_generator_scores_each_patient_once(self):
        class DummyModel:
            def fit(self, X, y):
                self.classes_ = np.array([0, 1])
                return self

            def predict_proba(self, X):
                probability = np.clip(X.iloc[:, 0].to_numpy(), 0, 1)
                return np.column_stack([1 - probability, probability])

        index = pd.Index(range(10, 30), name="PatientID")
        X = pd.DataFrame({"risk": np.linspace(0.05, 0.95, 20)}, index=index)
        y = pd.Series([0, 1] * 10, index=index)
        result = generate_oof_predictions(
            X, y, DummyModel, n_splits=2, random_state=42,
        )
        assert result["patient_id"].is_unique
        assert set(result["patient_id"]) == set(index)
        assert set(result["fold"]) == {1, 2}
        assert result["y_prob"].notna().all()


class TestThresholdMetrics:
    def test_known_confusion_metrics(self):
        result = calculate_threshold_metrics(
            [0, 0, 1, 1], [0.1, 0.6, 0.4, 0.9], [0.5],
        ).iloc[0]
        assert (result.tp, result.fp, result.tn, result.fn) == (1, 1, 1, 1)
        assert result.precision == pytest.approx(0.5)
        assert result.recall == pytest.approx(0.5)
        assert result.sensitivity == pytest.approx(0.5)
        assert result.specificity == pytest.approx(0.5)
        assert result.false_positive_rate == pytest.approx(0.5)
        assert result.f1 == pytest.approx(0.5)

    def test_threshold_zero_predicts_everyone_positive(self):
        row = calculate_threshold_metrics([0, 1], [0.0, 1.0], [0.0]).iloc[0]
        assert (row.tp, row.fp, row.tn, row.fn) == (1, 1, 0, 0)

    def test_threshold_one_is_inclusive(self):
        row = calculate_threshold_metrics([0, 1], [0.9, 1.0], [1.0]).iloc[0]
        assert (row.tp, row.fp, row.tn, row.fn) == (1, 0, 1, 0)

    def test_zero_denominators_are_safe(self):
        row = calculate_threshold_metrics([0, 0], [0.1, 0.2], [0.9]).iloc[0]
        assert row.precision == 0
        assert row.recall == 0
        assert row.f1 == 0

    def test_invalid_probability_is_rejected(self):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            calculate_threshold_metrics([0, 1], [0.2, 1.1], [0.5])

    def test_operating_point_rules_are_deterministic(self):
        metrics = pd.DataFrame(
            {
                "threshold": [0.2, 0.4, 0.6, 0.8],
                "recall": [0.9, 0.75, 0.4, 0.2],
                "false_positive_rate": [0.5, 0.3, 0.1, 0.02],
                "precision": [0.2, 0.3, 0.5, 0.7],
                "f1": [0.3, 0.5, 0.55, 0.31],
            }
        )
        selected = select_operating_points(metrics).set_index("operating_point")
        assert selected.loc["HIGH_SENSITIVITY", "threshold"] == 0.4
        assert selected.loc["BALANCED", "threshold"] == 0.6
        assert selected.loc["LOWER_FALSE_ALARM", "threshold"] == 0.6


class TestRiskLevels:
    @pytest.mark.parametrize(
        ("probability", "expected"),
        [(0.0, "LOW"), (0.29, "LOW"), (0.3, "MEDIUM"),
         (0.69, "MEDIUM"), (0.7, "HIGH"), (1.0, "HIGH")],
    )
    def test_boundary_mapping(self, probability, expected):
        assert probability_to_risk_level(probability, 0.3, 0.7) == expected

    def test_mapping_is_deterministic(self):
        results = [probability_to_risk_level(0.55, 0.3, 0.7) for _ in range(5)]
        assert results == ["MEDIUM"] * 5

    def test_mapping_is_monotonic(self):
        levels = [
            probability_to_risk_level(p, 0.3, 0.7)
            for p in np.linspace(0, 1, 101)
        ]
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        numeric = [order[level] for level in levels]
        assert numeric == sorted(numeric)

    def test_invalid_threshold_order_is_rejected(self):
        with pytest.raises(ValueError, match="medium_threshold"):
            probability_to_risk_level(0.5, 0.7, 0.3)


class TestAlertPolicy:
    def test_empty_history_has_no_alert(self):
        assert risk_history_to_alert_state([]) == "NO_ALERT"

    def test_single_high_is_watch_not_high_alert(self):
        assert risk_history_to_alert_state(["HIGH"]) == "WATCH"

    def test_isolated_spike_surrounded_by_low_never_high_alerts(self):
        timeline = probabilities_to_alert_timeline([0.1, 0.9, 0.1], 0.3, 0.7)
        assert [row["alert_state"] for row in timeline] == [
            "NO_ALERT", "WATCH", "NO_ALERT",
        ]

    def test_persistent_elevated_risk_high_alerts(self):
        assert risk_history_to_alert_state(["MEDIUM", "MEDIUM"]) == "HIGH_ALERT"
        assert risk_history_to_alert_state(["HIGH", "HIGH"]) == "HIGH_ALERT"

    def test_worsening_risk_high_alerts(self):
        assert risk_history_to_alert_state(
            ["LOW", "MEDIUM", "HIGH"]
        ) == "HIGH_ALERT"

    def test_current_state_cannot_inspect_future_scores(self):
        prefix = probabilities_to_alert_timeline([0.1, 0.4], 0.3, 0.7)
        extended = probabilities_to_alert_timeline([0.1, 0.4, 0.95], 0.3, 0.7)
        assert prefix == extended[:2]
