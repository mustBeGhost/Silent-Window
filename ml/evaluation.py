"""Development evaluation aligned with the minimum runtime coverage guard."""

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from ml.coverage import usable_temporal_counts
from ml.threshold_analysis import calculate_threshold_metrics, validate_development_oof_predictions


def scoreable_development_data(
    X: pd.DataFrame, y: pd.Series, development_ids: list[int], separated_ids: list[int],
) -> tuple[pd.DataFrame, pd.Series]:
    """Select usable rows by observed input coverage, never outcomes or future time.

    This defines scoreability, not confirmed alive-and-in-ICU eligibility.
    """
    if not X.index.is_unique or not y.index.is_unique:
        raise ValueError("Patient indices must be unique")
    if not X.index.equals(y.index) or list(X.index) != list(development_ids):
        raise ValueError("Feature and target rows must match the ordered development cohort")
    if len(set(development_ids)) != len(development_ids) or len(set(separated_ids)) != len(separated_ids):
        raise ValueError("Frozen cohort patient IDs must be unique")
    if set(development_ids) & set(separated_ids):
        raise ValueError("Development and separated cohorts overlap")
    if not y.isin([0, 1]).all():
        raise ValueError("Target labels must be present and binary")
    if np.isinf(X.to_numpy(dtype=float)).any():
        raise ValueError("Infinite features cannot enter evaluation")
    selected = usable_temporal_counts(X) > 0
    return X.loc[selected].copy(), y.loc[selected].copy()


def calibration_bins(labels: np.ndarray, scores: np.ndarray, n_bins: int = 10) -> list[dict]:
    """Return nonempty, fixed-width descriptive reliability bins."""
    rows = []
    indices = np.minimum((scores * n_bins).astype(int), n_bins - 1)
    for bin_index in range(n_bins):
        selected = indices == bin_index
        if not selected.any():
            continue
        rows.append({
            "lower": bin_index / n_bins,
            "upper": (bin_index + 1) / n_bins,
            "upper_inclusive": bin_index == n_bins - 1,
            "patients": int(selected.sum()),
            "mean_model_score": float(scores[selected].mean()),
            "observed_death_rate": float(labels[selected].mean()),
        })
    return rows


def summarize_development_predictions(
    predictions: pd.DataFrame, scoreable_ids: list[int], separated_ids: list[int],
) -> dict:
    """Validate exact OOF membership before reporting any metrics."""
    validate_development_oof_predictions(predictions, scoreable_ids, separated_ids)
    labels = predictions["y_true"].to_numpy(dtype=int)
    scores = predictions["y_prob"].to_numpy(dtype=float)
    if set(np.unique(labels)) != {0, 1}:
        raise ValueError("Evaluation requires both outcome classes")
    bins = calibration_bins(labels, scores)
    fold_aucs = [
        float(roc_auc_score(group["y_true"], group["y_prob"]))
        for _, group in predictions.groupby("fold")
    ]
    return {
        "patients_scored": len(labels),
        "deaths_in_scored_population": int(labels.sum()),
        "observed_death_rate": float(labels.mean()),
        "mean_model_score": float(scores.mean()),
        "pooled_oof_roc_auc": float(roc_auc_score(labels, scores)),
        "fold_mean_roc_auc": float(np.mean(fold_aucs)),
        "average_precision": float(average_precision_score(labels, scores)),
        "brier_score": float(brier_score_loss(labels, scores)),
        "log_loss": float(log_loss(labels, scores, labels=[0, 1])),
        "expected_calibration_error_10_fixed_bins": float(sum(
            row["patients"] * abs(row["mean_model_score"] - row["observed_death_rate"])
            for row in bins
        ) / len(labels)),
        "calibration_bins": bins,
        "fixed_threshold_metrics": calculate_threshold_metrics(labels, scores, [0.4, 0.5, 0.55]).to_dict("records"),
    }
