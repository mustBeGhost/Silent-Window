"""Predeclared forest settings and paired threshold-resolution study.

Only the 12h assessment is evaluated. Both grids reuse identical predictions.
Model choice uses fine-grid INNER training predictions, never outer labels.
"""

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import average_precision_score
from sklearn.model_selection import StratifiedKFold

from ml.alert_evaluation import positive_probability
from ml.coverage import usable_temporal_counts
from ml.evaluation import scoreable_development_data
from ml.model_improvement import choose_training_candidate, primary_metrics
from ml.recall_experiments import select_recall_boundaries
from ml.threshold_analysis import calculate_threshold_metrics
from ml.train_models import build_rf_pipeline

RECALL_TARGET = 0.85
GRIDS = {"coarse": tuple(i / 100 for i in range(101)),
         "fine": tuple(i / 1000 for i in range(1001))}
CANDIDATES = {
    "rf_v2": {"label": "Current inputs · depth 12, leaf 10", "features": "v2", "max_depth": 12, "min_samples_leaf": 10},
    "recent_reference": {"label": "Recent inputs · depth 12, leaf 10", "features": "recent", "max_depth": 12, "min_samples_leaf": 10},
    "recent_shallow": {"label": "Recent inputs · depth 8, leaf 10", "features": "recent", "max_depth": 8, "min_samples_leaf": 10},
    "recent_larger_leaf": {"label": "Recent inputs · depth 12, leaf 20", "features": "recent", "max_depth": 12, "min_samples_leaf": 20},
    "recent_unlimited_depth": {"label": "Recent inputs · no depth limit, leaf 10", "features": "recent", "max_depth": None, "min_samples_leaf": 10},
}


def forest_model(name, columns):
    settings = CANDIDATES[name]
    estimator = build_rf_pipeline(columns)
    estimator.set_params(classifier__n_jobs=1, classifier__max_depth=settings["max_depth"],
                         classifier__min_samples_leaf=settings["min_samples_leaf"])
    return CalibratedClassifierCV(estimator, method="sigmoid", ensemble=False, n_jobs=1,
                                  cv=StratifiedKFold(3, shuffle=True, random_state=42))


def select_grid_boundaries(labels, scores, grid):
    if grid not in GRIDS:
        raise ValueError("Unknown threshold grid")
    if grid == "coarse":
        return select_recall_boundaries(labels, scores, RECALL_TARGET)
    if set(np.unique(labels)) != {0, 1}:
        raise ValueError("Both outcome classes are required")
    metrics = calculate_threshold_metrics(labels, scores, GRIDS[grid])

    def choose(candidates, floor):
        eligible = candidates[candidates.recall >= floor]
        if eligible.empty:
            return candidates.sort_values(
                ["recall", "false_positive_rate", "precision", "threshold"],
                ascending=[False, True, False, False], kind="stable").iloc[0]
        return eligible.sort_values(["false_positive_rate", "precision", "threshold"],
                                    ascending=[True, False, False], kind="stable").iloc[0]

    medium = choose(metrics[metrics.threshold < 1], RECALL_TARGET)
    high = choose(metrics[metrics.threshold > medium.threshold], 0.30)
    return {"medium": float(medium.threshold), "high": float(high.threshold),
            "selection_population": "INNER_OOF_SCOREABLE_12H_TRAINING_PATIENTS_ONLY",
            "recall_target": RECALL_TARGET,
            "inner_training_metrics": {"medium": medium.to_dict(), "high": high.to_dict()},
            "recall_floor_met": {"medium": bool(medium.recall >= RECALL_TARGET), "high": bool(high.recall >= 0.30)}}


def evaluate_training_fold(matrices, training_target, validation_ids, builder=forest_model,
                           *, inner_splits=3, progress=None):
    """No validation-label argument; both grids use exactly the same model fits."""
    train_ids = list(training_target.index)
    if not training_target.index.is_unique or len(set(validation_ids)) != len(validation_ids):
        raise ValueError("Patient IDs must be unique")
    if set(train_ids) & set(validation_ids):
        raise ValueError("Training and validation patients overlap")
    if inner_splits < 2 or set(training_target.unique()) != {0, 1} or training_target.value_counts().min() < inner_splits:
        raise ValueError("Insufficient binary training classes")
    if set(matrices) != {"v2", "recent"}:
        raise ValueError("Both feature sets are required")
    for X in matrices.values():
        if not X.index.is_unique or not set(train_ids + validation_ids).issubset(X.index):
            raise ValueError("Missing or duplicated feature patients")
    usable = usable_temporal_counts(matrices["v2"]) > 0
    if not usable.equals(usable_temporal_counts(matrices["recent"]) > 0):
        raise ValueError("Feature sets must retain identical coverage")
    fit_all = [pid for pid in train_ids if usable.loc[pid]]
    score_all = [pid for pid in validation_ids if usable.loc[pid]]
    folds = list(StratifiedKFold(inner_splits, shuffle=True, random_state=42).split(np.zeros(len(train_ids)), training_target))
    scores, selections = {}, {}
    for name, settings in CANDIDATES.items():
        if progress:
            progress(f"  {settings['label']}")
        X = matrices[settings["features"]]
        inner = pd.Series(np.nan, index=train_ids)
        counts = pd.Series(0, index=train_ids)
        for train, validation in folds:
            fit_ids = [train_ids[i] for i in train if usable.loc[train_ids[i]]]
            score_ids = [train_ids[i] for i in validation if usable.loc[train_ids[i]]]
            if score_ids:
                model = builder(name, list(X.columns))
                model.fit(X.loc[fit_ids], training_target.loc[fit_ids])
                inner.loc[score_ids] = positive_probability(model, X.loc[score_ids])
                counts.loc[score_ids] += 1
        if not (counts.loc[fit_all] == 1).all():
            raise RuntimeError("Each scoreable training patient needs one inner prediction")
        ap = float(average_precision_score(training_target.loc[fit_all], inner.loc[fit_all]))
        selections[name] = {grid: {**select_grid_boundaries(training_target.loc[fit_all], inner.loc[fit_all], grid),
                                   "inner_average_precision": ap} for grid in GRIDS}
        scores[name] = pd.Series(np.nan, index=validation_ids)
        if score_all:
            model = builder(name, list(X.columns))
            model.fit(X.loc[fit_all], training_target.loc[fit_all])
            scores[name].loc[score_all] = positive_probability(model, X.loc[score_all])
    winner = choose_training_candidate({name: value["fine"] for name, value in selections.items()})
    return scores, selections, winner


def evaluate_forest_tuning(matrices, target, development_ids, separated_ids, builder=forest_model,
                           *, outer_splits=5, inner_splits=3, progress=None):
    if set(matrices) != {"v2", "recent"}:
        raise ValueError("Both feature sets are required")
    for X in matrices.values():
        scoreable_development_data(X, target, development_ids, separated_ids)
    if outer_splits < 2 or set(target.unique()) != {0, 1} or target.value_counts().min() < outer_splits:
        raise ValueError("Insufficient binary outer fold classes")
    names = list(CANDIDATES) + ["training_selected"]
    scores = {name: pd.Series(np.nan, index=target.index) for name in names}
    thresholds = {grid: {name: pd.Series(np.nan, index=target.index) for name in names} for grid in GRIDS}
    counts = pd.Series(0, index=target.index)
    fold_results = []
    splitter = StratifiedKFold(outer_splits, shuffle=True, random_state=42)
    for fold, (train, validation) in enumerate(splitter.split(np.zeros(len(target)), target), 1):
        if progress:
            progress(f"Outer patient fold {fold}/{outer_splits}")
        val_ids = list(target.iloc[validation].index)
        val_scores, selections, winner = evaluate_training_fold(
            matrices, target.iloc[train], val_ids, builder, inner_splits=inner_splits, progress=progress)
        for name in names:
            source = winner if name == "training_selected" else name
            scores[name].loc[val_ids] = val_scores[source]
            for grid in GRIDS:
                thresholds[grid][name].loc[val_ids] = selections[source][grid]["medium"]
        counts.loc[val_ids] += 1
        fold_results.append({"fold": fold, "training_patients": len(train), "validation_patients": len(validation),
                             "training_selected_candidate": winner, "selections": selections})
    if not (counts == 1).all():
        raise RuntimeError("Each patient needs exactly one validation assignment")
    coverage = usable_temporal_counts(matrices["v2"]) > 0
    if any(not values.notna().equals(coverage) for values in scores.values()):
        raise RuntimeError("Scores do not match observation coverage")
    results = {grid: {name: primary_metrics(scores[name], target, thresholds[grid][name]) for name in names} for grid in GRIDS}
    chosen = results["fine"]["training_selected"]["any_warning"]
    controls = {grid: results[grid]["rf_v2"]["any_warning"] for grid in GRIDS}
    checks = {grid: {"no_fewer_detected": chosen["tp"] >= control["tp"],
                     "at_least_10_percent_fewer_survivor_warnings": chosen["fp"] <= control["fp"] * 0.90}
              for grid, control in controls.items()}
    return {"development_patients": len(target), "death_labels": int(target.sum()),
            "fold_results": fold_results, "results": results,
            "research_promotion_gate": {"passed": all(all(check.values()) for check in checks.values()),
                                        "checks_against_current_inputs": checks, "is_clinical_standard": False}}
