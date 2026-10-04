"""Out-of-fold threshold analysis for Silent Window development models.

This module intentionally requires patient identifiers in memory so it can
prove that an OOF prediction set contains exactly the development cohort and
none of the held-out cohort.  Patient-level predictions must not be persisted.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold


DEFAULT_THRESHOLD_GRID: tuple[float, ...] = tuple(
    round(value, 2) for value in np.arange(0.20, 0.801, 0.05)
)

OOF_COLUMNS: frozenset[str] = frozenset(
    {"patient_id", "y_true", "y_prob", "fold"}
)


def generate_oof_predictions(
    X: pd.DataFrame,
    y: pd.Series,
    model_builder: Callable[[], object],
    *,
    n_splits: int = 5,
    random_state: int = 42,
) -> pd.DataFrame:
    """Fit one model per fold and return one probability per patient.

    Preprocessing remains inside the supplied model pipeline, so it is fitted
    on the training portion of each fold only.
    """
    if not X.index.is_unique or not y.index.is_unique:
        raise ValueError("X and y must have unique patient indices")
    if not X.index.equals(y.index):
        raise ValueError("X and y patient indices must be identically ordered")
    if n_splits < 2:
        raise ValueError("n_splits must be at least 2")

    labels = y.to_numpy()
    if not set(np.unique(labels)).issubset({0, 1}):
        raise ValueError("y must contain only binary labels 0 and 1")
    if set(np.unique(labels)) != {0, 1}:
        raise ValueError("OOF evaluation requires both outcome classes")
    if int(y.value_counts().min()) < n_splits:
        raise ValueError("Each outcome class needs at least n_splits patients")

    probabilities = np.full(len(X), np.nan, dtype=float)
    folds = np.full(len(X), -1, dtype=int)
    validation_count = np.zeros(len(X), dtype=int)
    splitter = StratifiedKFold(
        n_splits=n_splits,
        shuffle=True,
        random_state=random_state,
    )

    for fold, (train_idx, validation_idx) in enumerate(
        splitter.split(X, labels), start=1
    ):
        if set(train_idx) & set(validation_idx):
            raise RuntimeError("Training and validation patient rows overlap")
        model = model_builder()
        model.fit(X.iloc[train_idx], y.iloc[train_idx])
        classes = list(getattr(model, "classes_", []))
        if len(classes) != 2 or set(classes) != {0, 1}:
            raise RuntimeError("OOF models must expose binary classes_ containing 0 and 1")
        fold_probabilities = model.predict_proba(X.iloc[validation_idx])[:, classes.index(1)]
        if (
            len(fold_probabilities) != len(validation_idx)
            or not np.isfinite(fold_probabilities).all()
            or ((fold_probabilities < 0) | (fold_probabilities > 1)).any()
        ):
            raise RuntimeError("OOF probabilities must be finite and in [0, 1]")
        probabilities[validation_idx] = fold_probabilities
        folds[validation_idx] = fold
        validation_count[validation_idx] += 1

    if not np.all(validation_count == 1):
        raise RuntimeError("Every development patient must be scored OOF once")
    if not np.isfinite(probabilities).all():
        raise RuntimeError("OOF probabilities must all be finite")

    return pd.DataFrame(
        {
            "patient_id": X.index.to_numpy(),
            "y_true": labels,
            "y_prob": probabilities,
            "fold": folds,
        }
    )


def validate_development_oof_predictions(
    predictions: pd.DataFrame,
    development_ids: Sequence[int],
    holdout_ids: Sequence[int],
) -> None:
    """Reject any prediction set that is not exactly the development cohort."""
    missing_columns = OOF_COLUMNS - set(predictions.columns)
    if missing_columns:
        raise ValueError(f"OOF predictions missing columns: {missing_columns}")

    dev_set = {int(value) for value in development_ids}
    holdout_set = {int(value) for value in holdout_ids}
    if dev_set & holdout_set:
        raise ValueError("Development and holdout ID sets overlap")
    if len(dev_set) != len(development_ids):
        raise ValueError("Development IDs must be unique")
    if predictions["patient_id"].duplicated().any():
        raise ValueError("Each patient must have exactly one OOF prediction")

    prediction_ids = {int(value) for value in predictions["patient_id"]}
    leaked_holdout = prediction_ids & holdout_set
    if leaked_holdout:
        raise ValueError(
            f"Held-out patient IDs entered threshold analysis: "
            f"{sorted(leaked_holdout)[:5]}"
        )
    if prediction_ids != dev_set:
        missing = dev_set - prediction_ids
        unexpected = prediction_ids - dev_set
        raise ValueError(
            "OOF patient IDs must equal the development cohort exactly; "
            f"missing={len(missing)}, unexpected={len(unexpected)}"
        )

    labels = predictions["y_true"].to_numpy()
    probabilities = predictions["y_prob"].to_numpy(dtype=float)
    folds = predictions["fold"].to_numpy()
    if not set(np.unique(labels)).issubset({0, 1}):
        raise ValueError("OOF labels must be binary 0/1")
    if not np.isfinite(probabilities).all():
        raise ValueError("OOF probabilities must be finite")
    if ((probabilities < 0) | (probabilities > 1)).any():
        raise ValueError("OOF probabilities must lie in [0, 1]")
    if pd.isna(folds).any() or (folds < 1).any():
        raise ValueError("Every OOF row must have a positive fold number")


def _safe_divide(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def calculate_threshold_metrics(
    y_true: Sequence[int],
    y_prob: Sequence[float],
    thresholds: Iterable[float] = DEFAULT_THRESHOLD_GRID,
) -> pd.DataFrame:
    """Calculate confusion-derived metrics at every fixed threshold."""
    labels = np.asarray(y_true)
    probabilities = np.asarray(y_prob, dtype=float)
    if labels.ndim != 1 or probabilities.ndim != 1:
        raise ValueError("y_true and y_prob must be one-dimensional")
    if len(labels) == 0 or len(labels) != len(probabilities):
        raise ValueError("y_true and y_prob must have equal non-zero length")
    if not set(np.unique(labels)).issubset({0, 1}):
        raise ValueError("y_true must contain only 0 and 1")
    if not np.isfinite(probabilities).all():
        raise ValueError("y_prob must be finite")
    if ((probabilities < 0) | (probabilities > 1)).any():
        raise ValueError("y_prob must lie in [0, 1]")

    threshold_values = [float(value) for value in thresholds]
    if not threshold_values:
        raise ValueError("At least one threshold is required")
    if any(not np.isfinite(value) or value < 0 or value > 1
           for value in threshold_values):
        raise ValueError("Thresholds must be finite and lie in [0, 1]")

    rows: list[dict[str, float | int]] = []
    for threshold in threshold_values:
        predicted = probabilities >= threshold
        positive = labels == 1
        negative = ~positive
        tp = int((predicted & positive).sum())
        fp = int((predicted & negative).sum())
        tn = int((~predicted & negative).sum())
        fn = int((~predicted & positive).sum())
        precision = _safe_divide(tp, tp + fp)
        recall = _safe_divide(tp, tp + fn)
        specificity = _safe_divide(tn, tn + fp)
        fpr = _safe_divide(fp, fp + tn)
        f1 = _safe_divide(2 * precision * recall, precision + recall)
        rows.append(
            {
                "threshold": round(threshold, 4),
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "precision": precision,
                "recall": recall,
                "sensitivity": recall,
                "specificity": specificity,
                "false_positive_rate": fpr,
                "f1": f1,
            }
        )
    return pd.DataFrame(rows)


def analyze_development_oof_thresholds(
    predictions: pd.DataFrame,
    development_ids: Sequence[int],
    holdout_ids: Sequence[int],
    thresholds: Iterable[float] = DEFAULT_THRESHOLD_GRID,
) -> pd.DataFrame:
    """Validate cohort membership, then calculate aggregate threshold metrics."""
    validate_development_oof_predictions(
        predictions, development_ids, holdout_ids,
    )
    return calculate_threshold_metrics(
        predictions["y_true"], predictions["y_prob"], thresholds,
    )


def select_operating_points(metrics: pd.DataFrame) -> pd.DataFrame:
    """Select three deterministic engineering operating points.

    Rules, in order:
      * HIGH_SENSITIVITY: lowest FPR among thresholds with recall >= 0.70.
        If none qualify, use maximum recall then lowest FPR.
      * BALANCED: maximum F1, then lowest FPR.
      * LOWER_FALSE_ALARM: lowest FPR among thresholds with recall >= 0.30.
        If none qualify, use maximum recall then lowest FPR.

    Final ties prefer higher precision and then the higher threshold.
    These are demonstration rules, not clinically validated criteria.
    """
    required = {
        "threshold", "recall", "false_positive_rate", "precision", "f1",
    }
    missing = required - set(metrics.columns)
    if missing:
        raise ValueError(f"Threshold metrics missing columns: {missing}")
    if metrics.empty:
        raise ValueError("Threshold metrics cannot be empty")

    def choose_with_recall_floor(floor: float) -> pd.Series:
        eligible = metrics[metrics["recall"] >= floor]
        if eligible.empty:
            return metrics.sort_values(
                ["recall", "false_positive_rate", "precision", "threshold"],
                ascending=[False, True, False, False],
                kind="stable",
            ).iloc[0]
        return eligible.sort_values(
            ["false_positive_rate", "precision", "threshold"],
            ascending=[True, False, False],
            kind="stable",
        ).iloc[0]

    high_sensitivity = choose_with_recall_floor(0.70)
    balanced = metrics.sort_values(
        ["f1", "false_positive_rate", "precision", "threshold"],
        ascending=[False, True, False, False],
        kind="stable",
    ).iloc[0]
    lower_false_alarm = choose_with_recall_floor(0.30)

    selected = pd.DataFrame(
        [high_sensitivity, balanced, lower_false_alarm]
    ).reset_index(drop=True)
    selected.insert(
        0,
        "operating_point",
        ["HIGH_SENSITIVITY", "BALANCED", "LOWER_FALSE_ALARM"],
    )
    return selected
