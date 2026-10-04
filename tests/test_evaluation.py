"""Evaluation cohort safety, class identity, and nested calibration checks."""

import numpy as np
import pandas as pd
import pytest
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import StratifiedKFold

from ml.evaluation import calibration_bins, scoreable_development_data, summarize_development_predictions
from ml.features import get_feature_columns_v2
from ml.threshold_analysis import generate_oof_predictions
import ml.train_models as train_models


def matrix_and_target():
    X = pd.DataFrame(0.0, index=[1, 2, 3, 4], columns=get_feature_columns_v2())
    X.loc[[1, 2, 3], "HR_count"] = 1
    y = pd.Series([0, 1, 0, 1], index=X.index)
    return X, y


def test_scoreability_selection_is_label_independent_and_preserves_order():
    X, y = matrix_and_target()
    selected, target = scoreable_development_data(X, y, [1, 2, 3, 4], [5, 6])
    assert list(selected.index) == list(target.index) == [1, 2, 3]
    reversed_labels = 1 - y
    selected_again, _ = scoreable_development_data(X, reversed_labels, [1, 2, 3, 4], [5, 6])
    pd.testing.assert_frame_equal(selected, selected_again)
    assert len(X) == 4


def test_holdout_cannot_enter_feature_selection():
    X, y = matrix_and_target()
    with pytest.raises(ValueError, match="overlap"):
        scoreable_development_data(X, y, [1, 2, 3, 4], [4, 5])


def test_row_target_misalignment_is_rejected():
    X, y = matrix_and_target()
    with pytest.raises(ValueError, match="ordered development"):
        scoreable_development_data(X, y.iloc[::-1], [1, 2, 3, 4], [5, 6])


def test_summary_requires_exact_scoreable_cohort_before_metrics():
    predictions = pd.DataFrame({
        "patient_id": [1, 2, 3, 5], "y_true": [0, 1, 0, 1],
        "y_prob": [0.1, 0.8, 0.2, 0.9], "fold": [1, 1, 2, 2],
    })
    with pytest.raises(ValueError, match="Held-out"):
        summarize_development_predictions(predictions, [1, 2, 3, 4], [5, 6])


def test_calibration_bins_include_score_one_and_omit_empty_bins():
    bins = calibration_bins(np.array([0, 1]), np.array([0.0, 1.0]))
    assert len(bins) == 2
    assert sum(row["patients"] for row in bins) == 2
    assert bins[-1]["upper_inclusive"]
    assert bins[-1]["observed_death_rate"] == 1


def test_calibration_summary_reports_overestimated_scores():
    predictions = pd.DataFrame({
        "patient_id": [1, 2, 3, 4], "y_true": [0, 1, 0, 1],
        "y_prob": [0.7, 0.9, 0.7, 0.9], "fold": [1, 1, 2, 2],
    })
    result = summarize_development_predictions(predictions, [1, 2, 3, 4], [5, 6])
    assert result["observed_death_rate"] == 0.5
    assert result["mean_model_score"] == pytest.approx(0.8)
    assert result["brier_score"] == pytest.approx(0.25)
    assert result["pooled_oof_roc_auc"] == 1


def test_oof_selects_death_class_when_probability_columns_are_reversed():
    class ReversedClassModel:
        def fit(self, X, y):
            self.classes_ = np.array([1, 0])
            return self

        def predict_proba(self, X):
            return np.tile([0.2, 0.8], (len(X), 1))

    X = pd.DataFrame({"x": range(8)}, index=range(10, 18))
    y = pd.Series([0, 1] * 4, index=X.index)
    result = generate_oof_predictions(X, y, ReversedClassModel, n_splits=2)
    assert (result["y_prob"] == 0.2).all()


def test_nested_calibration_never_fits_outer_validation_patients():
    recordings = []
    current_recording = None

    class RecordingClassifier(ClassifierMixin, BaseEstimator):
        def fit(self, X, y):
            current_recording["fit_ids"].append(set(X.index))
            self.classes_ = np.array([0, 1])
            return self

        def predict_proba(self, X):
            current_recording["predict_ids"].append(set(X.index))
            scores = np.clip(X["x"].to_numpy(dtype=float), 0.1, 0.9)
            return np.column_stack([1 - scores, scores])

        def predict(self, X):
            return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    def builder():
        nonlocal current_recording
        current_recording = {"fit_ids": [], "predict_ids": []}
        recordings.append(current_recording)
        return CalibratedClassifierCV(
            estimator=RecordingClassifier(), method="sigmoid", ensemble=False,
            cv=StratifiedKFold(n_splits=2, shuffle=True, random_state=42),
            n_jobs=1,
        )

    X = pd.DataFrame({"x": np.linspace(0.1, 0.9, 24)}, index=range(100, 124))
    y = pd.Series([0, 1] * 12, index=X.index)
    generate_oof_predictions(X, y, builder, n_splits=2)
    assert len(recordings) == 2
    for recording in recordings:
        outer_validation = recording["predict_ids"][-1]
        assert len(outer_validation) == 12
        assert all(not (fit_ids & outer_validation) for fit_ids in recording["fit_ids"])
        assert set.union(*recording["fit_ids"]) == set(X.index) - outer_validation


def test_too_few_positive_cases_for_requested_folds_is_rejected():
    X = pd.DataFrame({"x": [1, 2, 3, 4]})
    y = pd.Series([0, 0, 0, 1])
    with pytest.raises(ValueError, match="at least n_splits"):
        generate_oof_predictions(X, y, lambda: None, n_splits=2)


def test_development_loader_does_not_read_separated_patient_files(monkeypatch):
    requested = []
    monkeypatch.setattr(train_models, "discover_patient_ids", lambda: [1, 2, 3, 4])
    def loader(patient_id):
        requested.append(patient_id)
        return pd.DataFrame()
    monkeypatch.setattr(train_models, "load_patient", loader)
    monkeypatch.setattr(train_models, "preprocess_patient", lambda value: value)
    loaded = train_models.load_all_patients([1, 2])
    assert requested == [1, 2]
    assert set(loaded) == {1, 2}
