"""Nested development threshold evaluation with patient-grouped checkpoints.

Thresholds are selected from inner predictions at the primary 12h checkpoint.
They are shared across checkpoints, matching the current runtime policy. The
fixed persistence rule is evaluated, never optimized on outer validation labels.
All patient predictions remain in memory.
"""

from collections.abc import Callable

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold

from ml.alert_policy import probabilities_to_alert_timeline
from ml.coverage import usable_temporal_counts
from ml.evaluation import scoreable_development_data
from ml.threshold_analysis import calculate_threshold_metrics


CHECKPOINTS = ("6h", "12h", "24h")
THRESHOLD_GRID = tuple(value / 100 for value in range(101))
RECALL_FLOORS = {"medium": 0.70, "high": 0.30}
HISTORICAL_BOUNDARIES = {"medium": 0.40, "high": 0.55}
STRATEGIES = {
    "raw_historical": ("raw", False),
    "calibrated_historical": ("calibrated", False),
    "raw_nested": ("raw", True),
    "calibrated_nested": ("calibrated", True),
}


def select_boundaries(labels, scores) -> dict:
    """Predeclared engineering recall floors, with explicit infeasible fallbacks.

    Prefer lowest false-positive rate, then precision, then largest threshold.
    Medium must leave room for a strictly greater high boundary on the fixed
    grid. If a floor is infeasible, maximize recall within those constraints.
    """
    if set(np.unique(labels)) != {0, 1}:
        raise ValueError("Threshold selection requires both outcome classes")
    metrics = calculate_threshold_metrics(labels, scores, THRESHOLD_GRID)

    def choose(candidates, floor):
        eligible = candidates[candidates["recall"] >= floor]
        if eligible.empty:
            chosen = candidates.sort_values(
                ["recall", "false_positive_rate", "precision", "threshold"],
                ascending=[False, True, False, False], kind="stable",
            ).iloc[0]
        else:
            chosen = eligible.sort_values(
                ["false_positive_rate", "precision", "threshold"],
                ascending=[True, False, False], kind="stable",
            ).iloc[0]
        return chosen

    medium = choose(metrics[metrics["threshold"] < 1], RECALL_FLOORS["medium"])
    high = choose(metrics[metrics["threshold"] > medium["threshold"]], RECALL_FLOORS["high"])
    return {
        "medium": float(medium["threshold"]), "high": float(high["threshold"]),
        "selection_population": "INNER_OOF_SCOREABLE_12H_TRAINING_PATIENTS_ONLY",
        "inner_training_metrics": {
            "medium": medium.to_dict(), "high": high.to_dict(),
        },
        "recall_floor_met": {
            "medium": bool(medium["recall"] >= RECALL_FLOORS["medium"]),
            "high": bool(high["recall"] >= RECALL_FLOORS["high"]),
        },
    }


def positive_probability(model, X) -> np.ndarray:
    classes = list(getattr(model, "classes_", []))
    if len(classes) != 2 or set(classes) != {0, 1}:
        raise ValueError("Model must expose binary classes_ containing 0 and 1")
    probabilities = np.asarray(model.predict_proba(X), dtype=float)
    if probabilities.shape != (len(X), 2):
        raise ValueError("Unexpected probability matrix shape")
    scores = probabilities[:, classes.index(1)]
    if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError("Scores must be finite and in [0, 1]")
    return scores


def paired_scores(model, X) -> dict[str, np.ndarray]:
    """Use the final base forest of ensemble=False for a paired comparison."""
    calibrated = model.calibrated_classifiers_
    if len(calibrated) != 1:
        raise ValueError("Paired evaluation requires ensemble=False calibration")
    return {
        "raw": positive_probability(calibrated[0].estimator, X),
        "calibrated": positive_probability(model, X),
    }


def evaluate_training_fold(
    matrices: dict[str, pd.DataFrame], training_target: pd.Series,
    validation_ids: list[int], model_builder: Callable,
    *, inner_splits: int = 3, random_state: int = 42,
) -> tuple[dict, dict]:
    """Select and fit using training labels only; validation labels are absent.

    The inner split is assigned on all training patients before applying the
    coverage mask. The same outer validation IDs apply to every checkpoint.
    """
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
        raise ValueError("Exactly the 6h, 12h, and 24h matrices are required")
    for X in matrices.values():
        if not X.index.is_unique or not set(train_ids + validation_ids).issubset(X.index):
            raise ValueError("Feature matrices must contain unique fold patients")

    primary = matrices["12h"]
    primary_usable = usable_temporal_counts(primary) > 0
    inner_scores = {kind: pd.Series(np.nan, index=train_ids) for kind in ("raw", "calibrated")}
    assignment_count = pd.Series(0, index=train_ids)
    splitter = StratifiedKFold(n_splits=inner_splits, shuffle=True, random_state=random_state)
    for inner_train, inner_validation in splitter.split(np.zeros(len(train_ids)), training_target):
        fit_ids = [train_ids[i] for i in inner_train if primary_usable.loc[train_ids[i]]]
        score_ids = [train_ids[i] for i in inner_validation if primary_usable.loc[train_ids[i]]]
        if not score_ids:
            continue
        model = model_builder()
        model.fit(primary.loc[fit_ids], training_target.loc[fit_ids])
        for kind, values in paired_scores(model, primary.loc[score_ids]).items():
            inner_scores[kind].loc[score_ids] = values
        assignment_count.loc[score_ids] += 1
    usable_train = [patient_id for patient_id in train_ids if primary_usable.loc[patient_id]]
    if not (assignment_count.loc[usable_train] == 1).all():
        raise RuntimeError("Every scoreable training patient needs one inner OOF prediction")
    selections = {
        kind: select_boundaries(training_target.loc[usable_train], values.loc[usable_train])
        for kind, values in inner_scores.items()
    }
    scores = {kind: pd.DataFrame(np.nan, index=validation_ids, columns=CHECKPOINTS)
              for kind in ("raw", "calibrated")}
    for checkpoint in CHECKPOINTS:
        X = matrices[checkpoint]
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


def outcome_detection_metrics(labels, predicted, assessed) -> dict:
    """Missing assessments are reported separately, never counted as TN or FN."""
    labels = np.asarray(labels)
    predicted = np.asarray(predicted, dtype=bool)
    assessed = np.asarray(assessed, dtype=bool)
    if labels.ndim != 1 or predicted.shape != labels.shape or assessed.shape != labels.shape:
        raise ValueError("Labels, predictions, and availability must align")
    if not np.isin(labels, [0, 1]).all():
        raise ValueError("Labels must be binary")
    positive = labels == 1
    tp = int((positive & predicted & assessed).sum())
    fp = int((~positive & predicted & assessed).sum())
    tn = int((~positive & ~predicted & assessed).sum())
    fn = int((positive & ~predicted & assessed).sum())
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "assessed_patients": int(assessed.sum()),
        "unassessed_patients": int((~assessed).sum()),
        "unassessed_death_labels": int((positive & ~assessed).sum()),
        "recall_in_assessed_population": tp / (tp + fn) if tp + fn else None,
        "false_positive_rate_in_assessed_population": fp / (fp + tn) if fp + tn else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "fraction_of_all_death_labels_detected": tp / int(positive.sum()) if positive.any() else None,
    }


def summarize_alert_sequence(scores: pd.DataFrame, labels: pd.Series, boundaries: pd.DataFrame) -> dict:
    if not scores.index.is_unique or not scores.index.equals(labels.index) or not scores.index.equals(boundaries.index):
        raise ValueError("Scores, labels, and boundaries need identical unique patient order")
    if list(scores.columns) != list(CHECKPOINTS) or list(boundaries.columns) != ["medium", "high"]:
        raise ValueError("Unexpected checkpoint or boundary columns")
    values = scores.to_numpy(dtype=float)
    if np.isinf(values).any() or ((values < 0) | (values > 1)).any():
        raise ValueError("Available scores must be finite and in [0, 1]")
    states, risks = [], []
    for patient_id, row in scores.iterrows():
        timeline = probabilities_to_alert_timeline(
            [None if pd.isna(value) else float(value) for value in row],
            float(boundaries.loc[patient_id, "medium"]), float(boundaries.loc[patient_id, "high"]),
        )
        states.append([entry["alert_state"] for entry in timeline])
        risks.append([entry["risk_level"] for entry in timeline])
    states, risks = np.asarray(states, dtype=object), np.asarray(risks, dtype=object)
    available = ~np.isnan(values)
    elevated = np.isin(states, ["WATCH", "HIGH_ALERT"])
    persistent = states == "HIGH_ALERT"
    checkpoint_results, cumulative = {}, {}
    for i, checkpoint in enumerate(CHECKPOINTS):
        checkpoint_results[checkpoint] = {
            "state_counts": {
                **{name: int((states[:, i] == name).sum()) for name in ("NO_ALERT", "WATCH", "HIGH_ALERT")},
                "NOT_ASSESSED": int((~available[:, i]).sum()),
            },
            "any_warning": outcome_detection_metrics(labels, elevated[:, i], available[:, i]),
            "persistent_high_alert": outcome_detection_metrics(labels, persistent[:, i], available[:, i]),
            "high_risk_category": outcome_detection_metrics(labels, risks[:, i] == "HIGH", available[:, i]),
        }
        # Prefixes exclude later checkpoints, including their coverage status.
        cumulative[checkpoint] = {
            "any_warning_seen": outcome_detection_metrics(labels, elevated[:, :i + 1].any(axis=1), available[:, :i + 1].any(axis=1)),
            "persistent_high_alert_seen": outcome_detection_metrics(labels, persistent[:, :i + 1].any(axis=1), available[:, :i + 1].any(axis=1)),
        }
    first_warning = {}
    previously_warned = np.zeros(len(scores), dtype=bool)
    for i, checkpoint in enumerate(CHECKPOINTS):
        first = elevated[:, i] & ~previously_warned
        first_warning[checkpoint] = {"patients": int(first.sum()), "death_labels": int((first & (labels.to_numpy() == 1)).sum())}
        previously_warned |= elevated[:, i]
    return {"checkpoints": checkpoint_results, "cumulative_through_checkpoint": cumulative,
            "first_warning_checkpoint_counts": first_warning}


def evaluate_nested_alerts(matrices, target, development_ids, separated_ids, model_builder,
                           *, outer_splits=5, inner_splits=3, random_state=42, progress=None) -> dict:
    """Full development OOF evaluation; assign patient folds before coverage filtering."""
    if set(matrices) != set(CHECKPOINTS):
        raise ValueError("Exactly three checkpoint matrices are required")
    for X in matrices.values():
        scoreable_development_data(X, target, development_ids, separated_ids)
    if outer_splits < 2 or set(target.unique()) != {0, 1} or target.value_counts().min() < outer_splits:
        raise ValueError("Insufficient outcome classes for outer folds")
    scores = {kind: pd.DataFrame(np.nan, index=target.index, columns=CHECKPOINTS) for kind in ("raw", "calibrated")}
    boundaries = {kind: pd.DataFrame(np.nan, index=target.index, columns=["medium", "high"]) for kind in scores}
    counts = pd.Series(0, index=target.index)
    fold_results = []
    splitter = StratifiedKFold(n_splits=outer_splits, shuffle=True, random_state=random_state)
    for fold, (train, validation) in enumerate(splitter.split(np.zeros(len(target)), target), start=1):
        if progress:
            progress(f"Outer fold {fold}/{outer_splits}: selecting thresholds from training patients, then evaluating all checkpoints")
        train_target = target.iloc[train]
        val_ids = list(target.iloc[validation].index)
        val_scores, selections = evaluate_training_fold(
            matrices, train_target, val_ids, model_builder, inner_splits=inner_splits, random_state=random_state,
        )
        for kind in scores:
            scores[kind].loc[val_ids] = val_scores[kind]
            boundaries[kind].loc[val_ids, "medium"] = selections[kind]["medium"]
            boundaries[kind].loc[val_ids, "high"] = selections[kind]["high"]
        counts.loc[val_ids] += 1
        fold_results.append({"fold": fold, "training_patients": len(train), "validation_patients": len(validation),
                             "selected_boundaries": selections})
    if not (counts == 1).all():
        raise RuntimeError("Each development patient must enter exactly one outer validation fold")
    for kind, frame in scores.items():
        for checkpoint in CHECKPOINTS:
            expected = usable_temporal_counts(matrices[checkpoint]) > 0
            if not frame[checkpoint].notna().equals(expected):
                raise RuntimeError("OOF availability differs from input-only coverage")
    results = {}
    for name, (kind, tuned) in STRATEGIES.items():
        limits = boundaries[kind] if tuned else pd.DataFrame(HISTORICAL_BOUNDARIES, index=target.index)
        results[name] = summarize_alert_sequence(scores[kind], target, limits)
    return {"development_patients": len(target), "death_labels": int(target.sum()),
            "fold_results": fold_results, "results": results}
