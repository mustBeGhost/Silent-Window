import numpy as np
import pytest
from threadpoolctl import threadpool_limits

from ml.model_improvement import CANDIDATES, DropUnobservedColumns, candidate_model, evaluate_improvement_training_fold, evaluate_model_improvements
from tests.test_nested_alert_evaluation import RecordingPair, population


def matrices():
    original, labels = population()
    return {"v2": original, "recent": {checkpoint: X.copy() for checkpoint, X in original.items()}}, labels


def test_model_and_threshold_choice_cannot_see_outer_validation_patients():
    features, labels = matrices()
    recordings = []
    validation = list(labels.index[40:])
    before = evaluate_improvement_training_fold(features, labels.iloc[:40], validation,
                                               lambda name, columns: RecordingPair(recordings), inner_splits=2)
    assert len(recordings) == len(CANDIDATES) * 3 + 2
    for record in recordings:
        assert not record["fit"] & set(validation)
        assert all(not record["fit"] & scored for scored in record["predict"])
    changed = {version: {checkpoint: X.copy() for checkpoint, X in values.items()} for version, values in features.items()}
    for values in changed.values():
        for X in values.values():
            X.loc[validation, "HR_latest"] = 0.99
    after = evaluate_improvement_training_fold(changed, labels.iloc[:40], validation,
                                              lambda name, columns: RecordingPair([]), inner_splits=2)
    assert before[1:3] == after[1:3]


def test_all_models_use_same_outer_patient_groups_and_missing_coverage():
    features, labels = matrices()
    result = evaluate_model_improvements(features, labels, list(labels.index), [999],
                                        lambda name, columns: RecordingPair([]), outer_splits=3, inner_splits=2)
    for values in result["results"].values():
        assert values["any_warning"]["assessed_patients"] == 58
        assert values["any_warning"]["unassessed_death_labels"] == 1
    assert len(result["fold_results"]) == 3
    assert result["training_selected_timeline"]["checkpoints"]["6h"]["state_counts"]["NOT_ASSESSED"] == 2
    # Identical fake candidates cannot qualify as reducing warnings.
    assert result["research_promotion_gate"]["passed"] is False


def test_separated_patients_rejected_before_fitting_any_candidate():
    features, labels = matrices()
    records = []
    with pytest.raises(ValueError, match="overlap"):
        evaluate_model_improvements(features, labels, list(labels.index), [labels.index[0]],
                                    lambda name, columns: RecordingPair(records))
    assert not records


def test_empty_column_mask_uses_training_only_and_retains_partial_missingness():
    transformer = DropUnobservedColumns().fit([[1, np.nan, 2], [np.nan, np.nan, 3]])
    transformed = transformer.transform([[np.nan, 999, 4]])
    assert transformed.shape == (1, 2)
    assert np.isnan(transformed[0, 0])
    assert transformed[0, 1] == 4


@pytest.mark.parametrize("name", ["boosting_v2", "boosting_recent", "extra_trees_recent", "logistic_recent"])
def test_real_builders_handle_missing_values_and_unknown_icu_category(name):
    features, labels = matrices()
    X = features[CANDIDATES[name]["features"]]["12h"].copy()
    X.loc[:, "MAP_latest"] = np.nan if name.startswith("boosting") else 70
    X.loc[:, "ICUType"] = 1
    fit, validation = X.iloc[:40], X.iloc[40:].copy()
    validation.loc[:, "ICUType"] = 99
    model = candidate_model(name, list(X.columns), calibration_splits=2)
    with threadpool_limits(limits=1):
        model.fit(fit, labels.iloc[:40])
        scores = model.predict_proba(validation)
    assert scores.shape == (20, 2)
    assert np.isfinite(scores).all()
    assert ((scores >= 0) & (scores <= 1)).all()
