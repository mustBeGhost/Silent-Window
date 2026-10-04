"""Leakage boundaries, missing assessments, and chronological alert evaluation."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ml.alert_evaluation import (
    CHECKPOINTS, evaluate_nested_alerts, evaluate_training_fold, outcome_detection_metrics,
    positive_probability, select_boundaries, summarize_alert_sequence,
)
from ml.features import get_feature_columns_v2


def population(n=60):
    ids = list(range(100, 100 + n))
    labels = pd.Series([0, 1] * (n // 2), index=ids)
    matrices = {}
    for i, checkpoint in enumerate(CHECKPOINTS):
        X = pd.DataFrame(0.0, index=ids, columns=get_feature_columns_v2())
        X["HR_count"] = 1
        X["HR_latest"] = np.linspace(0.05, 0.95, n)
        # The selected feature records checkpoint identity for fit auditing.
        X["Age"] = i
        matrices[checkpoint] = X
    matrices["6h"].loc[ids[:2], "HR_count"] = 0
    matrices["12h"].loc[ids[2:4], "HR_count"] = 0
    return matrices, labels


class RecordingPair:
    def __init__(self, records):
        self.record = {"fit": set(), "predict": [], "checkpoint": None}
        records.append(self.record)
        self.classes_ = np.array([0, 1])
        self.calibrated_classifiers_ = [SimpleNamespace(estimator=self.Raw(self))]

    class Raw:
        classes_ = np.array([0, 1])

        def __init__(self, parent):
            self.parent = parent

        def predict_proba(self, X):
            self.parent.record["predict"].append(set(X.index))
            values = X["HR_latest"].to_numpy()
            return np.column_stack([1 - values, values])

    def fit(self, X, y):
        assert X.index.equals(y.index)
        self.record["fit"] = set(X.index)
        self.record["checkpoint"] = int(X["Age"].iloc[0])
        return self

    def predict_proba(self, X):
        values = self.calibrated_classifiers_[0].estimator.predict_proba(X)[:, 1] / 2
        return np.column_stack([1 - values, values])


def test_threshold_selection_uses_predeclared_recall_and_false_positive_tradeoff():
    selected = select_boundaries([0, 0, 1, 1], [0.1, 0.2, 0.3, 0.4])
    assert selected["medium"] == 0.3
    assert selected["high"] == 0.4
    assert selected["recall_floor_met"] == {"medium": True, "high": True}
    assert selected["inner_training_metrics"]["medium"]["fp"] == 0


def test_degenerate_scores_report_an_infeasible_high_recall_floor():
    selected = select_boundaries([0, 1, 0, 1], [0, 0, 0, 0])
    assert selected["medium"] == 0
    assert 0 < selected["high"] <= 1
    assert selected["recall_floor_met"]["high"] is False


@pytest.mark.parametrize("labels,scores", [([0, 0], [0.1, 0.2]), ([0, 1], [0.1, np.nan]), ([0, 1], [0.1, 1.1])])
def test_invalid_threshold_inputs_fail(labels, scores):
    with pytest.raises(ValueError):
        select_boundaries(labels, scores)


def test_nested_threshold_fits_exclude_outer_validation_and_inner_score_patients():
    matrices, labels = population()
    train_ids, val_ids = list(labels.index[:40]), list(labels.index[40:])
    recordings = []
    scores, _ = evaluate_training_fold(matrices, labels.loc[train_ids], val_ids,
                                      lambda: RecordingPair(recordings), inner_splits=2)
    assert len(recordings) == 5  # two threshold models plus three checkpoint fits
    for record in recordings:
        assert not record["fit"] & set(val_ids)
        assert all(not record["fit"] & score_ids for score_ids in record["predict"])
        checkpoint = CHECKPOINTS[record["checkpoint"]]
        assert all(matrices[checkpoint].loc[list(record["fit"]), "HR_count"] > 0)
    inner_scored = set.union(*(record["predict"][0] for record in recordings[:2]))
    assert inner_scored == set(train_ids) - set(labels.index[2:4])
    assert all(frame.index.tolist() == val_ids for frame in scores.values())


def test_outer_validation_values_cannot_change_selected_thresholds():
    matrices, labels = population()
    train, validation = labels.iloc[:40], list(labels.index[40:])
    _, before = evaluate_training_fold(matrices, train, validation, lambda: RecordingPair([]), inner_splits=2)
    changed = {checkpoint: X.copy() for checkpoint, X in matrices.items()}
    for X in changed.values():
        X.loc[validation, "HR_latest"] = 0.99
    _, after = evaluate_training_fold(changed, train, validation, lambda: RecordingPair([]), inner_splits=2)
    assert before == after


def test_outer_patient_folds_are_shared_before_checkpoint_coverage_filtering():
    matrices, labels = population()
    recordings = []
    report = evaluate_nested_alerts(matrices, labels, list(labels.index), [999],
                                    lambda: RecordingPair(recordings), outer_splits=3, inner_splits=2)
    assert report["development_patients"] == 60
    assert len(recordings) == 15
    validation_membership = []
    for start in range(0, 15, 5):
        final_models = recordings[start + 2:start + 5]
        assert [entry["checkpoint"] for entry in final_models] == [0, 1, 2]
        # All 24h patients have observations; that fit reveals the full outer fold.
        fold_validation = final_models[2]["predict"][0]
        for entry in final_models:
            assert not entry["fit"] & fold_validation
            assert entry["predict"][0].issubset(fold_validation)
        validation_membership.append(fold_validation)
    assert set.union(*validation_membership) == set(labels.index)
    assert sum(len(group) for group in validation_membership) == len(labels)
    result = report["results"]["calibrated_nested"]["checkpoints"]
    assert result["6h"]["state_counts"]["NOT_ASSESSED"] == 2
    assert result["12h"]["state_counts"]["NOT_ASSESSED"] == 2
    assert result["24h"]["state_counts"]["NOT_ASSESSED"] == 0


def test_separated_patient_overlap_is_rejected_before_any_model_fits():
    matrices, labels = population()
    recordings = []
    with pytest.raises(ValueError, match="overlap"):
        evaluate_nested_alerts(matrices, labels, list(labels.index), [labels.index[0]], lambda: RecordingPair(recordings))
    assert recordings == []


def test_missing_positive_patients_are_not_counted_as_false_negatives_or_true_negatives():
    result = outcome_detection_metrics([1, 1, 0], [True, False, False], [True, False, True])
    assert (result["tp"], result["fn"], result["tn"]) == (1, 0, 1)
    assert result["unassessed_death_labels"] == 1
    assert result["recall_in_assessed_population"] == 1
    assert result["fraction_of_all_death_labels_detected"] == 0.5


def test_gap_breaks_persistence_and_future_warning_does_not_enter_earlier_prefix():
    scores = pd.DataFrame([[0.5, np.nan, 0.5], [0.1, 0.1, 0.5], [0.5, 0.5, 0.5]], index=[1, 2, 3], columns=CHECKPOINTS)
    labels = pd.Series([1, 1, 0], index=scores.index)
    boundaries = pd.DataFrame({"medium": 0.4, "high": 0.55}, index=scores.index)
    result = summarize_alert_sequence(scores, labels, boundaries)
    assert result["checkpoints"]["24h"]["state_counts"] == {"NO_ALERT": 0, "WATCH": 2, "HIGH_ALERT": 1, "NOT_ASSESSED": 0}
    assert result["cumulative_through_checkpoint"]["12h"]["any_warning_seen"]["tp"] == 1
    assert result["cumulative_through_checkpoint"]["24h"]["any_warning_seen"]["tp"] == 2
    assert result["first_warning_checkpoint_counts"]["24h"] == {"patients": 1, "death_labels": 1}


def test_high_risk_boundary_does_not_change_the_persistence_alert_rule():
    scores = pd.DataFrame([[0.5, 0.5, 0.5]], index=[1], columns=CHECKPOINTS)
    labels = pd.Series([1], index=[1])
    before = summarize_alert_sequence(scores, labels, pd.DataFrame({"medium": 0.4, "high": 0.6}, index=[1]))
    after = summarize_alert_sequence(scores, labels, pd.DataFrame({"medium": 0.4, "high": 0.45}, index=[1]))
    assert before["checkpoints"]["12h"]["persistent_high_alert"] == after["checkpoints"]["12h"]["persistent_high_alert"]
    assert before["checkpoints"]["12h"]["high_risk_category"]["tp"] == 0
    assert after["checkpoints"]["12h"]["high_risk_category"]["tp"] == 1


def test_probability_extraction_respects_class_identity():
    model = SimpleNamespace(classes_=np.array([1, 0]), predict_proba=lambda X: np.tile([0.3, 0.7], (len(X), 1)))
    assert positive_probability(model, pd.DataFrame({"x": [1, 2]})).tolist() == [0.3, 0.3]


def test_real_sigmoid_calibrator_supports_paired_nested_evaluation():
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import StratifiedKFold

    matrices, labels = population()
    def builder():
        return CalibratedClassifierCV(
            RandomForestClassifier(n_estimators=5, max_depth=2, random_state=42, n_jobs=1),
            method="sigmoid", ensemble=False,
            cv=StratifiedKFold(n_splits=2, shuffle=True, random_state=42), n_jobs=1,
        )
    report = evaluate_nested_alerts(matrices, labels, list(labels.index), [999], builder, outer_splits=3, inner_splits=2)
    assert report["results"]["calibrated_nested"]["checkpoints"]["12h"]["any_warning"]["assessed_patients"] == 58


def test_alert_summary_rejects_label_order_mismatch():
    scores = pd.DataFrame([[0.1] * 3, [0.5] * 3], index=[1, 2], columns=CHECKPOINTS)
    with pytest.raises(ValueError, match="order"):
        summarize_alert_sequence(scores, pd.Series([0, 1], index=[2, 1]), pd.DataFrame({"medium": 0.4, "high": 0.55}, index=[1, 2]))
