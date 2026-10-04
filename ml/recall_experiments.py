"""Predeclared recall-target experiments; no deployed thresholds are changed.

All targets reuse the same inner predictions and outer patient folds. Selection
sees training labels only; validation labels enter aggregate reporting only.
"""

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold

from ml.alert_evaluation import CHECKPOINTS, THRESHOLD_GRID, paired_scores, summarize_alert_sequence
from ml.coverage import usable_temporal_counts
from ml.evaluation import scoreable_development_data
from ml.threshold_analysis import calculate_threshold_metrics

RECALL_TARGETS = (0.70, 0.85, 0.90)


def select_recall_boundaries(labels, scores, recall_target):
    if not np.isfinite(recall_target) or not 0 < recall_target <= 1:
        raise ValueError("Recall target must be finite and in (0, 1]")
    if set(np.unique(labels)) != {0, 1}:
        raise ValueError("Threshold selection requires both outcome classes")
    metrics = calculate_threshold_metrics(labels, scores, THRESHOLD_GRID)

    def choose(candidates, floor):
        eligible = candidates[candidates.recall >= floor]
        if eligible.empty:
            return candidates.sort_values(
                ["recall", "false_positive_rate", "precision", "threshold"],
                ascending=[False, True, False, False], kind="stable",
            ).iloc[0]
        return eligible.sort_values(
            ["false_positive_rate", "precision", "threshold"],
            ascending=[True, False, False], kind="stable",
        ).iloc[0]

    medium = choose(metrics[metrics.threshold < 1], recall_target)
    high = choose(metrics[metrics.threshold > medium.threshold], 0.30)
    return {
        "medium": float(medium.threshold), "high": float(high.threshold),
        "selection_population": "INNER_OOF_SCOREABLE_12H_TRAINING_PATIENTS_ONLY",
        "recall_target": recall_target,
        "inner_training_metrics": {"medium": medium.to_dict(), "high": high.to_dict()},
        "recall_floor_met": {"medium": bool(medium.recall >= recall_target), "high": bool(high.recall >= 0.30)},
    }


def evaluate_recall_training_fold(matrices, training_target, validation_ids, model_builder,
                                 *, inner_splits=3, random_state=42):
    """Validation labels are deliberately absent from this interface."""
    train_ids = list(training_target.index)
    if not training_target.index.is_unique or len(set(validation_ids)) != len(validation_ids):
        raise ValueError("Fold patient IDs must be unique")
    if set(train_ids) & set(validation_ids):
        raise ValueError("Training and validation patients overlap")
    if not training_target.isin([0, 1]).all() or set(training_target.unique()) != {0, 1}:
        raise ValueError("Training requires both binary outcome classes")
    if inner_splits < 2 or training_target.value_counts().min() < inner_splits:
        raise ValueError("Insufficient class counts for inner folds")
    if set(matrices) != set(CHECKPOINTS):
        raise ValueError("Exactly three checkpoint matrices are required")
    for X in matrices.values():
        if not X.index.is_unique or not set(train_ids + validation_ids).issubset(X.index):
            raise ValueError("Feature matrices must contain unique fold patients")
    primary = matrices["12h"]
    usable = usable_temporal_counts(primary) > 0
    inner_scores = {kind: pd.Series(np.nan, index=train_ids) for kind in ("raw", "calibrated")}
    counts = pd.Series(0, index=train_ids)
    splitter = StratifiedKFold(n_splits=inner_splits, shuffle=True, random_state=random_state)
    for train, validation in splitter.split(np.zeros(len(train_ids)), training_target):
        fit_ids = [train_ids[i] for i in train if usable.loc[train_ids[i]]]
        score_ids = [train_ids[i] for i in validation if usable.loc[train_ids[i]]]
        if not score_ids:
            continue
        model = model_builder()
        model.fit(primary.loc[fit_ids], training_target.loc[fit_ids])
        for kind, values in paired_scores(model, primary.loc[score_ids]).items():
            inner_scores[kind].loc[score_ids] = values
        counts.loc[score_ids] += 1
    eligible = [patient_id for patient_id in train_ids if usable.loc[patient_id]]
    if not (counts.loc[eligible] == 1).all():
        raise RuntimeError("Every eligible training patient needs one inner prediction")
    selections = {
        kind: {str(int(floor * 100)): select_recall_boundaries(
            training_target.loc[eligible], values.loc[eligible], floor,
        ) for floor in RECALL_TARGETS} for kind, values in inner_scores.items()
    }
    scores = {kind: pd.DataFrame(np.nan, index=validation_ids, columns=CHECKPOINTS) for kind in inner_scores}
    for checkpoint, X in matrices.items():
        usable = usable_temporal_counts(X) > 0
        fit_ids = [patient_id for patient_id in train_ids if usable.loc[patient_id]]
        score_ids = [patient_id for patient_id in validation_ids if usable.loc[patient_id]]
        if not score_ids:
            continue
        model = model_builder()
        model.fit(X.loc[fit_ids], training_target.loc[fit_ids])
        for kind, values in paired_scores(model, X.loc[score_ids]).items():
            scores[kind].loc[score_ids, checkpoint] = values
    return scores, selections


def evaluate_recall_targets(matrices, target, development_ids, separated_ids, model_builder,
                            *, outer_splits=5, inner_splits=3, random_state=42, progress=None):
    if set(matrices) != set(CHECKPOINTS):
        raise ValueError("Exactly three checkpoint matrices are required")
    for X in matrices.values():
        scoreable_development_data(X, target, development_ids, separated_ids)
    if outer_splits < 2 or set(target.unique()) != {0, 1} or target.value_counts().min() < outer_splits:
        raise ValueError("Insufficient outcome classes for outer folds")
    scores = {kind: pd.DataFrame(np.nan, index=target.index, columns=CHECKPOINTS) for kind in ("raw", "calibrated")}
    boundaries = {kind: {str(int(floor * 100)): pd.DataFrame(np.nan, index=target.index, columns=["medium", "high"])
                         for floor in RECALL_TARGETS} for kind in scores}
    counts = pd.Series(0, index=target.index)
    fold_results = []
    splitter = StratifiedKFold(n_splits=outer_splits, shuffle=True, random_state=random_state)
    for fold, (train, validation) in enumerate(splitter.split(np.zeros(len(target)), target), start=1):
        if progress:
            progress(f"Outer fold {fold}/{outer_splits}: select 70%, 85%, 90% targets on training; evaluate held-out patients")
        validation_ids = list(target.iloc[validation].index)
        val_scores, selections = evaluate_recall_training_fold(
            matrices, target.iloc[train], validation_ids, model_builder,
            inner_splits=inner_splits, random_state=random_state,
        )
        for kind in scores:
            scores[kind].loc[validation_ids] = val_scores[kind]
            for floor, limits in boundaries[kind].items():
                limits.loc[validation_ids, "medium"] = selections[kind][floor]["medium"]
                limits.loc[validation_ids, "high"] = selections[kind][floor]["high"]
        counts.loc[validation_ids] += 1
        fold_results.append({"fold": fold, "training_patients": len(train), "validation_patients": len(validation),
                             "selected_boundaries": selections})
    if not (counts == 1).all():
        raise RuntimeError("Each development patient needs exactly one outer validation fold")
    for frame in scores.values():
        for checkpoint in CHECKPOINTS:
            if not frame[checkpoint].notna().equals(usable_temporal_counts(matrices[checkpoint]) > 0):
                raise RuntimeError("OOF availability differs from input-only coverage")
    results = {kind: {floor: summarize_alert_sequence(scores[kind], target, limits)
                      for floor, limits in targets.items()} for kind, targets in boundaries.items()}
    return {"development_patients": len(target), "death_labels": int(target.sum()),
            "fold_results": fold_results, "results": results}
