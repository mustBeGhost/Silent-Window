"""Final candidate fitting and threshold choice using development training only."""

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold

from ml.alert_evaluation import CHECKPOINTS, positive_probability, select_boundaries
from ml.coverage import usable_temporal_counts
from ml.evaluation import scoreable_development_data
from ml.threshold_analysis import validate_development_oof_predictions


def fit_research_candidate(matrices, target, development_ids, separated_ids, model_builder,
                           *, n_splits=3, random_state=42, progress=None):
    """Choose one final pair from training OOF scores, then fit three final models.

    These OOF scores are threshold-selection diagnostics, not a fresh estimate
    of the selected thresholds' performance. Nested validation remains separate.
    Only coverage counts and aggregate selection diagnostics leave this function.
    """
    if set(matrices) != set(CHECKPOINTS):
        raise ValueError("Exactly three checkpoint matrices are required")
    scoreable = {
        checkpoint: scoreable_development_data(X, target, development_ids, separated_ids)
        for checkpoint, X in matrices.items()
    }
    if n_splits < 2 or set(target.unique()) != {0, 1} or target.value_counts().min() < n_splits:
        raise ValueError("Insufficient class counts for threshold training folds")
    primary = matrices["12h"]
    usable = usable_temporal_counts(primary) > 0
    predictions = pd.DataFrame({"patient_id": target.index, "y_true": target.to_numpy(),
                                "y_prob": np.nan, "fold": 0}, index=target.index)
    visits = pd.Series(0, index=target.index)
    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    for fold, (train, validation) in enumerate(splitter.split(np.zeros(len(target)), target), start=1):
        if progress:
            progress(f"Training threshold-selection fold {fold}/{n_splits} at 12h")
        fit_ids = [target.index[i] for i in train if usable.iloc[i]]
        score_ids = [target.index[i] for i in validation if usable.iloc[i]]
        model = model_builder()
        model.fit(primary.loc[fit_ids], target.loc[fit_ids])
        if score_ids:
            predictions.loc[score_ids, "y_prob"] = positive_probability(model, primary.loc[score_ids])
            predictions.loc[score_ids, "fold"] = fold
            visits.loc[score_ids] += 1
    predictions = predictions.loc[usable]
    if not (visits.loc[usable] == 1).all():
        raise RuntimeError("Every usable training patient must receive one OOF score")
    validate_development_oof_predictions(predictions, list(scoreable["12h"][0].index), separated_ids)
    selected = select_boundaries(predictions["y_true"], predictions["y_prob"])
    models, coverage = {}, {}
    for checkpoint, (X, y) in scoreable.items():
        if progress:
            progress(f"Fitting final calibrated model at {checkpoint}: {len(X)} training patients")
        model = model_builder()
        model.fit(X, y)
        models[checkpoint] = model
        coverage[checkpoint] = {
            "patients_fitted": len(X), "patients_excluded_for_missing_measurements": len(target) - len(X),
            "death_labels_fitted": int(y.sum()),
            "death_labels_excluded_for_missing_measurements": int(target.sum() - y.sum()),
        }
    return models, {"selected_boundaries": selected, "training_coverage": coverage}
