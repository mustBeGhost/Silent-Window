"""Derived, non-patient-level data for model-performance visualization.

The functions in this module operate on development-only out-of-fold (OOF)
predictions in memory and on the existing fitted 12-hour production artifact.
They never persist patient identifiers, labels, or individual probabilities.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import auc, roc_auc_score, roc_curve

from ml.threshold_analysis import validate_development_oof_predictions


STAT_LABELS = {
    "latest": "Latest",
    "mean": "Mean",
    "min": "Minimum",
    "max": "Maximum",
    "std": "Standard Deviation",
    "count": "Measurement Count",
    "time_since_last": "Time Since Last Measurement",
    "slope": "Trend",
}

PARAMETER_LABELS = {
    "Age": "Age",
    "Gender": "Gender",
    "Weight": "Weight",
    "HR": "Heart Rate",
    "GCS": "GCS",
    "Temp": "Temperature",
    "MAP": "MAP",
    "SysABP": "Systolic Arterial Pressure",
    "DiasABP": "Diastolic Arterial Pressure",
    "Glucose": "Glucose",
    "Creatinine": "Creatinine",
    "BUN": "Blood Urea Nitrogen",
    "WBC": "White Blood Cell Count",
    "Platelets": "Platelets",
    "HCT": "Hematocrit",
    "Na": "Sodium",
    "K": "Potassium",
    "HCO3": "Bicarbonate",
    "Mg": "Magnesium",
}

ICU_TYPE_LABELS = {
    "1.0": "CCU",
    "2.0": "CSRU",
    "3.0": "MICU",
    "4.0": "SICU",
}


def build_roc_summary(
    predictions: pd.DataFrame,
    development_ids: Sequence[int],
    separated_ids: Sequence[int],
    *,
    checkpoint: str,
    primary: bool,
) -> dict[str, Any]:
    """Return aggregate ROC coordinates after strict OOF-cohort validation."""
    validate_development_oof_predictions(
        predictions,
        development_ids,
        separated_ids,
    )
    labels = predictions["y_true"].to_numpy(dtype=int)
    probabilities = predictions["y_prob"].to_numpy(dtype=float)
    false_positive_rate, true_positive_rate, _ = roc_curve(
        labels,
        probabilities,
        drop_intermediate=True,
    )
    pooled_auc = float(roc_auc_score(labels, probabilities))
    curve_auc = float(auc(false_positive_rate, true_positive_rate))
    if not np.isclose(pooled_auc, curve_auc, rtol=0.0, atol=1e-12):
        raise RuntimeError("ROC coordinates and OOF ROC-AUC are inconsistent")

    fold_aucs = [
        float(roc_auc_score(fold["y_true"], fold["y_prob"]))
        for _, fold in predictions.groupby("fold", sort=True)
    ]
    return {
        "checkpoint": checkpoint,
        "label": f"{checkpoint} — Primary" if primary else checkpoint,
        "primary": primary,
        "roc_auc": round(pooled_auc, 8),
        "fold_mean_roc_auc": round(float(np.mean(fold_aucs)), 8),
        "fold_std_roc_auc": round(float(np.std(fold_aucs, ddof=1)), 8),
        "points": [
            {
                "fpr": round(float(fpr), 8),
                "tpr": round(float(tpr), 8),
            }
            for fpr, tpr in zip(
                false_positive_rate,
                true_positive_rate,
                strict=True,
            )
        ],
    }


def readable_feature_label(transformed_name: str) -> str:
    """Translate one proven transformed feature name without changing meaning."""
    if transformed_name.startswith("num__"):
        raw_name = transformed_name.removeprefix("num__")
    elif transformed_name.startswith("cat__ICUType_"):
        category = transformed_name.removeprefix("cat__ICUType_")
        return f"ICU Type — {ICU_TYPE_LABELS.get(category, category)}"
    else:
        return transformed_name

    if raw_name in PARAMETER_LABELS:
        return PARAMETER_LABELS[raw_name]
    for statistic in sorted(STAT_LABELS, key=len, reverse=True):
        suffix = f"_{statistic}"
        if raw_name.endswith(suffix):
            parameter = raw_name[: -len(suffix)]
            parameter_label = PARAMETER_LABELS.get(parameter, parameter)
            return f"{parameter_label} — {STAT_LABELS[statistic]}"
    return raw_name.replace("_", " ")


def extract_global_feature_importance(
    artifact_path: Path,
    expected_input_features: Sequence[str],
    *,
    top_n: int = 10,
) -> dict[str, Any]:
    """Read top global importances from the fitted 12-hour RF pipeline."""
    model = joblib.load(artifact_path)
    if list(getattr(model, "feature_names_in_", [])) != list(
        expected_input_features
    ):
        raise ValueError("12h artifact input feature order is inconsistent")

    classifiers = [
        step
        for step in getattr(model, "named_steps", {}).values()
        if isinstance(step, RandomForestClassifier)
    ]
    if len(classifiers) != 1:
        raise ValueError("12h artifact must contain one RandomForestClassifier")
    classifier = classifiers[0]

    preprocessing_steps = [
        step
        for step in getattr(model, "named_steps", {}).values()
        if step is not classifier
        and callable(getattr(step, "get_feature_names_out", None))
    ]
    if len(preprocessing_steps) != 1:
        raise ValueError("12h artifact preprocessing mapping is ambiguous")
    transformed_names = list(
        preprocessing_steps[0].get_feature_names_out()
    )

    # Accessing feature_importances_ parallelizes over trees when n_jobs=-1.
    # A runtime-only single-worker setting avoids Windows named-pipe issues and
    # cannot alter the already fitted trees or their importance values.
    classifier.n_jobs = 1
    importances = np.asarray(classifier.feature_importances_, dtype=float)
    if len(transformed_names) != len(importances):
        raise ValueError("Transformed feature names do not match RF importances")
    if top_n < 1 or top_n > len(importances):
        raise ValueError("top_n is outside the transformed feature range")
    if not np.isclose(importances.sum(), 1.0, rtol=0.0, atol=1e-12):
        raise ValueError("RF feature importances do not sum to one")

    ranked_indices = np.argsort(-importances, kind="stable")[:top_n]
    return {
        "checkpoint": "12h",
        "input_feature_count": len(expected_input_features),
        "transformed_feature_count": len(transformed_names),
        "top_n": top_n,
        "features": [
            {
                "rank": rank,
                "technical_name": transformed_names[index],
                "label": readable_feature_label(transformed_names[index]),
                "importance": round(float(importances[index]), 12),
            }
            for rank, index in enumerate(ranked_indices, start=1)
        ],
    }
