"""Fixed candidate comparison and training-only model selection at 85% recall.

Candidate settings are declared here before running. Outer validation outcomes
never choose a model, feature set, or threshold. No predictions are persisted.
"""

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.utils.validation import check_is_fitted

from ml.alert_evaluation import CHECKPOINTS, outcome_detection_metrics, positive_probability, summarize_alert_sequence
from ml.coverage import usable_temporal_counts
from ml.evaluation import scoreable_development_data
from ml.recall_experiments import select_recall_boundaries
from ml.train_models import build_lr_pipeline, build_rf_pipeline

CANDIDATES = {
    "rf_v2": {"label": "Current calibrated Random Forest", "features": "v2", "family": "rf"},
    "rf_recent": {"label": "Random Forest with recent inputs", "features": "recent", "family": "rf"},
    "extra_trees_recent": {"label": "Extra Trees with recent inputs", "features": "recent", "family": "extra_trees"},
    "boosting_v2": {"label": "Gradient boosting with current inputs", "features": "v2", "family": "boosting"},
    "boosting_recent": {"label": "Gradient boosting with recent inputs", "features": "recent", "family": "boosting"},
    "logistic_recent": {"label": "Logistic Regression with recent inputs", "features": "recent", "family": "logistic"},
}
RECALL_TARGET = 0.85
PROMOTION_MINIMUM_FP_REDUCTION = 0.10  # research gate, not a clinical standard


class DropUnobservedColumns(TransformerMixin, BaseEstimator):
    """Avoid installed HGB's all-NaN binning failure; fit the mask on training only."""

    def fit(self, X, y=None):
        values = np.asarray(X, dtype=float)
        if values.ndim != 2 or np.isinf(values).any():
            raise ValueError("Expected finite-or-missing numeric columns")
        self.n_features_in_ = values.shape[1]
        self.observed_columns_ = ~np.isnan(values).all(axis=0)
        if not self.observed_columns_.any():
            raise ValueError("No observed numeric columns")
        return self

    def transform(self, X):
        check_is_fitted(self, "observed_columns_")
        values = np.asarray(X, dtype=float)
        if values.ndim != 2 or values.shape[1] != self.n_features_in_ or np.isinf(values).any():
            raise ValueError("Numeric schema changed")
        return values[:, self.observed_columns_]


def candidate_model(candidate, columns, *, calibration_splits=3):
    family = CANDIDATES[candidate]["family"]
    if family == "rf":
        estimator = build_rf_pipeline(columns)
        estimator.set_params(classifier__n_jobs=1)
    elif family == "logistic":
        estimator = build_lr_pipeline(columns)
    elif family == "extra_trees":
        estimator = build_rf_pipeline(columns)
        estimator.set_params(classifier=ExtraTreesClassifier(
            n_estimators=300, min_samples_leaf=5, class_weight="balanced", random_state=42, n_jobs=1,
        ))
    else:
        # Boosting retains numeric NaNs; categorical processing stays inside CV.
        preprocess = ColumnTransformer([
            ("numeric", DropUnobservedColumns(), [column for column in columns if column != "ICUType"]),
            ("category", Pipeline([
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
            ]), ["ICUType"]),
        ])
        estimator = Pipeline([
            ("preprocess", preprocess),
            ("classifier", HistGradientBoostingClassifier(
                max_iter=200, max_leaf_nodes=15, min_samples_leaf=20, learning_rate=0.05,
                l2_regularization=1.0, class_weight="balanced", early_stopping=False, random_state=42,
            )),
        ])
    return CalibratedClassifierCV(estimator, method="sigmoid", ensemble=False, n_jobs=1,
                                  cv=StratifiedKFold(calibration_splits, shuffle=True, random_state=42))


def choose_training_candidate(selections):
    eligible = [name for name, value in selections.items() if value["recall_floor_met"]["medium"]]
    if not eligible:
        raise ValueError("No candidate meets the training recall target")
    return min(eligible, key=lambda name: (
        selections[name]["inner_training_metrics"]["medium"]["fp"],
        -selections[name]["inner_training_metrics"]["medium"]["tp"],
        -selections[name]["inner_average_precision"], name,
    ))


def evaluate_improvement_training_fold(matrices, training_target, validation_ids, builder=candidate_model,
                                       *, inner_splits=3, progress=None):
    """Fit without access to outer validation labels; select one family on inner OOF."""
    train_ids = list(training_target.index)
    if not training_target.index.is_unique or len(set(validation_ids)) != len(validation_ids):
        raise ValueError("Patient IDs must be unique")
    if set(train_ids) & set(validation_ids):
        raise ValueError("Training and validation patients overlap")
    if set(training_target.unique()) != {0, 1} or training_target.value_counts().min() < inner_splits or inner_splits < 2:
        raise ValueError("Insufficient binary training classes")
    if set(matrices) != {"v2", "recent"}:
        raise ValueError("Both feature sets are required")
    for checkpoints in matrices.values():
        if set(checkpoints) != set(CHECKPOINTS):
            raise ValueError("All three checkpoints are required")
        for X in checkpoints.values():
            if not X.index.is_unique or not set(train_ids + validation_ids).issubset(X.index):
                raise ValueError("Feature patients are missing or duplicated")
    usable = usable_temporal_counts(matrices["v2"]["12h"]) > 0
    eligible = [patient_id for patient_id in train_ids if usable.loc[patient_id]]
    validation_eligible = [patient_id for patient_id in validation_ids if usable.loc[patient_id]]
    splitter = StratifiedKFold(inner_splits, shuffle=True, random_state=42)
    folds = list(splitter.split(np.zeros(len(train_ids)), training_target))
    selections, scores = {}, {}
    for name, settings in CANDIDATES.items():
        if progress:
            progress(f"  Candidate: {settings['label']}")
        X = matrices[settings["features"]]["12h"]
        inner = pd.Series(np.nan, index=train_ids)
        counts = pd.Series(0, index=train_ids)
        for train, validation in folds:
            fit_ids = [train_ids[i] for i in train if usable.loc[train_ids[i]]]
            score_ids = [train_ids[i] for i in validation if usable.loc[train_ids[i]]]
            if not score_ids:
                continue
            model = builder(name, list(X.columns))
            model.fit(X.loc[fit_ids], training_target.loc[fit_ids])
            inner.loc[score_ids] = positive_probability(model, X.loc[score_ids])
            counts.loc[score_ids] += 1
        if not (counts.loc[eligible] == 1).all():
            raise RuntimeError("Every scoreable training patient needs one inner OOF score")
        selections[name] = {
            **select_recall_boundaries(training_target.loc[eligible], inner.loc[eligible], RECALL_TARGET),
            "inner_average_precision": float(average_precision_score(training_target.loc[eligible], inner.loc[eligible])),
        }
        scores[name] = pd.Series(np.nan, index=validation_ids)
        if validation_eligible:
            model = builder(name, list(X.columns))
            model.fit(X.loc[eligible], training_target.loc[eligible])
            scores[name].loc[validation_eligible] = positive_probability(model, X.loc[validation_eligible])
    winner = choose_training_candidate(selections)
    sequence = pd.DataFrame(np.nan, index=validation_ids, columns=CHECKPOINTS)
    sequence["12h"] = scores[winner]
    for checkpoint in ("6h", "24h"):
        X = matrices[CANDIDATES[winner]["features"]][checkpoint]
        covered = usable_temporal_counts(X) > 0
        fit_ids = [patient_id for patient_id in train_ids if covered.loc[patient_id]]
        score_ids = [patient_id for patient_id in validation_ids if covered.loc[patient_id]]
        if score_ids:
            model = builder(winner, list(X.columns))
            model.fit(X.loc[fit_ids], training_target.loc[fit_ids])
            sequence.loc[score_ids, checkpoint] = positive_probability(model, X.loc[score_ids])
    return scores, selections, winner, sequence


def primary_metrics(scores, labels, thresholds):
    available = scores.notna()
    outcome = outcome_detection_metrics(labels, scores >= thresholds, available)
    y, p = labels.loc[available], scores.loc[available]
    return {"any_warning": outcome, "roc_auc": float(roc_auc_score(y, p)),
            "average_precision": float(average_precision_score(y, p)), "brier_score": float(brier_score_loss(y, p))}


def evaluate_model_improvements(matrices, target, development_ids, separated_ids, builder=candidate_model,
                                *, outer_splits=5, inner_splits=3, progress=None):
    if set(matrices) != {"v2", "recent"}:
        raise ValueError("Both feature sets are required")
    for checkpoints in matrices.values():
        if set(checkpoints) != set(CHECKPOINTS):
            raise ValueError("All three checkpoints are required")
        for checkpoint, X in checkpoints.items():
            scoreable_development_data(X, target, development_ids, separated_ids)
            if not (usable_temporal_counts(X) > 0).equals(usable_temporal_counts(matrices["v2"][checkpoint]) > 0):
                raise ValueError("Feature sets must retain identical observation coverage")
    if outer_splits < 2 or set(target.unique()) != {0, 1} or target.value_counts().min() < outer_splits:
        raise ValueError("Insufficient binary outer fold classes")
    names = list(CANDIDATES) + ["training_selected"]
    scores = {name: pd.Series(np.nan, index=target.index) for name in names}
    thresholds = {name: pd.Series(np.nan, index=target.index) for name in names}
    sequence = pd.DataFrame(np.nan, index=target.index, columns=CHECKPOINTS)
    boundaries = pd.DataFrame(np.nan, index=target.index, columns=["medium", "high"])
    counts = pd.Series(0, index=target.index)
    fold_results = []
    for fold, (train, validation) in enumerate(StratifiedKFold(outer_splits, shuffle=True, random_state=42).split(np.zeros(len(target)), target), 1):
        if progress:
            progress(f"Outer patient fold {fold}/{outer_splits}")
        val_ids = list(target.iloc[validation].index)
        val_scores, selected, winner, timeline = evaluate_improvement_training_fold(
            matrices, target.iloc[train], val_ids, builder, inner_splits=inner_splits, progress=progress,
        )
        for name in CANDIDATES:
            scores[name].loc[val_ids] = val_scores[name]
            thresholds[name].loc[val_ids] = selected[name]["medium"]
        scores["training_selected"].loc[val_ids] = val_scores[winner]
        thresholds["training_selected"].loc[val_ids] = selected[winner]["medium"]
        sequence.loc[val_ids] = timeline
        boundaries.loc[val_ids, "medium"] = selected[winner]["medium"]
        boundaries.loc[val_ids, "high"] = selected[winner]["high"]
        counts.loc[val_ids] += 1
        fold_results.append({"fold": fold, "training_patients": len(train), "validation_patients": len(validation),
                             "training_selected_candidate": winner, "selections": selected})
    if not (counts == 1).all():
        raise RuntimeError("Every patient needs exactly one outer validation assignment")
    coverage = usable_temporal_counts(matrices["v2"]["12h"]) > 0
    if any(not values.notna().equals(coverage) for values in scores.values()):
        raise RuntimeError("Candidate score availability differs from coverage")
    for checkpoint in CHECKPOINTS:
        if not sequence[checkpoint].notna().equals(usable_temporal_counts(matrices["v2"][checkpoint]) > 0):
            raise RuntimeError("Selected timeline availability differs from coverage")
    results = {name: primary_metrics(scores[name], target, thresholds[name]) for name in names}
    reference, chosen = results["rf_v2"]["any_warning"], results["training_selected"]["any_warning"]
    gate = chosen["tp"] >= reference["tp"] and chosen["fp"] <= reference["fp"] * (1 - PROMOTION_MINIMUM_FP_REDUCTION)
    return {"development_patients": len(target), "death_labels": int(target.sum()), "fold_results": fold_results,
            "results": results, "training_selected_timeline": summarize_alert_sequence(sequence, target, boundaries),
            "research_promotion_gate": {"passed": bool(gate), "no_fewer_detected_than_control": chosen["tp"] >= reference["tp"],
                                        "minimum_survivor_warning_reduction": PROMOTION_MINIMUM_FP_REDUCTION,
                                        "is_clinical_standard": False}}
