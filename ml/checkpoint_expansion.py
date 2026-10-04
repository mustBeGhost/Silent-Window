"""Fixed five-checkpoint research protocol, preserving the three-time control.

Thresholds are selected on inner training predictions at 12h for an 85%
any-warning recall target. They apply unchanged to each assessment time.
No validation outcome enters fitting, threshold selection, or coverage.
"""

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold

from ml.alert_policy import probabilities_to_alert_timeline
from ml.alert_evaluation import outcome_detection_metrics, positive_probability, summarize_alert_sequence
from ml.coverage import usable_temporal_counts
from ml.evaluation import scoreable_development_data
from ml.recall_experiments import evaluate_recall_training_fold

CUTOFFS = {"6h": 360, "9h": 540, "12h": 720, "18h": 1080, "24h": 1440}
CONTROL_CHECKPOINTS = ("6h", "12h", "24h")
RECALL_TARGET = 0.85


def summarize_expanded_sequence(scores, labels, boundaries):
    if not scores.index.is_unique or not scores.index.equals(labels.index) or not scores.index.equals(boundaries.index):
        raise ValueError("Scores, outcomes and boundaries must have identical unique order")
    if list(scores.columns) != list(CUTOFFS) or list(boundaries.columns) != ["medium", "high"]:
        raise ValueError("Expected ordered five-checkpoint scores and boundaries")
    values = scores.to_numpy(dtype=float)
    if np.isinf(values).any() or ((values < 0) | (values > 1)).any():
        raise ValueError("Available scores must be finite and within [0, 1]")
    states = np.asarray([
        [entry["alert_state"] for entry in probabilities_to_alert_timeline(
            [None if pd.isna(value) else float(value) for value in row],
            float(boundaries.loc[pid, "medium"]), float(boundaries.loc[pid, "high"]),
        )] for pid, row in scores.iterrows()
    ], dtype=object)
    available = ~np.isnan(values)
    warned = np.isin(states, ["WATCH", "HIGH_ALERT"])
    high = states == "HIGH_ALERT"
    results, cumulative, first = {}, {}, {}
    previously_warned = np.zeros(len(labels), dtype=bool)
    for i, checkpoint in enumerate(CUTOFFS):
        results[checkpoint] = {
            "state_counts": {**{name: int((states[:, i] == name).sum()) for name in ("NO_ALERT", "WATCH", "HIGH_ALERT")},
                             "NOT_ASSESSED": int((~available[:, i]).sum())},
            "any_warning": outcome_detection_metrics(labels, warned[:, i], available[:, i]),
            "persistent_high_alert": outcome_detection_metrics(labels, high[:, i], available[:, i]),
        }
        cumulative[checkpoint] = {
            "any_warning_seen": outcome_detection_metrics(labels, warned[:, :i+1].any(axis=1), available[:, :i+1].any(axis=1)),
            "persistent_high_alert_seen": outcome_detection_metrics(labels, high[:, :i+1].any(axis=1), available[:, :i+1].any(axis=1)),
        }
        new = warned[:, i] & ~previously_warned
        first[checkpoint] = {"patients": int(new.sum()), "death_labels": int((new & (labels.to_numpy() == 1)).sum())}
        previously_warned |= warned[:, i]
    return {"checkpoints": results, "cumulative_through_checkpoint": cumulative, "first_warning_checkpoint_counts": first}


def evaluate_expansion(matrices, target, development, separated, model_builder, *, outer_splits=5, inner_splits=3, progress=None):
    if list(matrices) != list(CUTOFFS):
        raise ValueError("Exactly five ordered checkpoint matrices are required")
    for matrix in matrices.values():
        scoreable_development_data(matrix, target, development, separated)
    scores = pd.DataFrame(np.nan, index=target.index, columns=CUTOFFS)
    boundaries = pd.DataFrame(np.nan, index=target.index, columns=["medium", "high"])
    assignments = pd.Series(0, index=target.index)
    folds = []
    control_matrices = {cp: matrices[cp] for cp in CONTROL_CHECKPOINTS}
    splitter = StratifiedKFold(n_splits=outer_splits, shuffle=True, random_state=42)
    for fold, (train, validation) in enumerate(splitter.split(np.zeros(len(target)), target), 1):
        if progress:
            progress(f"Outer patient fold {fold}/{outer_splits}: three-time control plus 9h and 18h")
        training_target, validation_ids = target.iloc[train], list(target.iloc[validation].index)
        control_scores, selections = evaluate_recall_training_fold(
            control_matrices, training_target, validation_ids, model_builder, inner_splits=inner_splits,
        )
        scores.loc[validation_ids, list(CONTROL_CHECKPOINTS)] = control_scores["calibrated"]
        selection = selections["calibrated"]["85"]
        boundaries.loc[validation_ids] = [selection["medium"], selection["high"]]
        for checkpoint in ("9h", "18h"):
            X = matrices[checkpoint]
            usable = usable_temporal_counts(X) > 0
            fit_ids = [pid for pid in training_target.index if usable.loc[pid]]
            score_ids = [pid for pid in validation_ids if usable.loc[pid]]
            if score_ids:
                model = model_builder()
                model.fit(X.loc[fit_ids], training_target.loc[fit_ids])
                scores.loc[score_ids, checkpoint] = positive_probability(model, X.loc[score_ids])
        assignments.loc[validation_ids] += 1
        folds.append({"fold": fold, "training_patients": len(train), "validation_patients": len(validation), "selected_boundaries": selection})
    if not (assignments == 1).all():
        raise RuntimeError("Each patient must appear in one validation fold")
    for checkpoint in CUTOFFS:
        if not scores[checkpoint].notna().equals(usable_temporal_counts(matrices[checkpoint]) > 0):
            raise RuntimeError("Score availability must match input-only coverage")
    return {
        "development_patients": len(target), "death_labels": int(target.sum()), "fold_results": folds,
        "control": summarize_alert_sequence(scores.loc[:, list(CONTROL_CHECKPOINTS)], target, boundaries),
        "expanded": summarize_expanded_sequence(scores, target, boundaries),
    }


def fit_expanded_candidate(matrices, target, development, separated, model_builder, progress=None):
    for matrix in matrices.values():
        scoreable_development_data(matrix, target, development, separated)
    if list(matrices) != list(CUTOFFS):
        raise ValueError("Exactly five ordered checkpoint matrices are required")
    # Empty validation IDs: only inner training predictions select boundaries.
    _, selections = evaluate_recall_training_fold(
        {cp: matrices[cp] for cp in CONTROL_CHECKPOINTS}, target, [], model_builder,
    )
    selection = selections["calibrated"]["85"]
    models, populations = {}, {}
    for checkpoint, X in matrices.items():
        ids = list(X.index[usable_temporal_counts(X) > 0])
        if progress:
            progress(f"Fitting final {checkpoint} research model on {len(ids)} development patients")
        model = model_builder()
        model.fit(X.loc[ids], target.loc[ids])
        models[checkpoint] = model
        populations[checkpoint] = {"assessed_patients": len(ids), "death_labels": int(target.loc[ids].sum()),
                                   "excluded_missing_observations": len(target) - len(ids)}
    return models, {"selected_boundaries": selection, "training_populations": populations}
