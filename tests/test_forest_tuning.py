import numpy as np
import pytest

from ml.forest_tuning import CANDIDATES, evaluate_forest_tuning, evaluate_training_fold, select_grid_boundaries
from ml.recall_experiments import select_recall_boundaries
from tests.test_nested_alert_evaluation import RecordingPair, population


def population_matrices():
    checkpoints, labels = population()
    return {"v2": checkpoints["12h"], "recent": checkpoints["12h"].copy()}, labels


def test_finer_grid_reduces_training_overshoot_without_changing_target():
    labels = np.array([1] * 20 + [0] * 20)
    scores = np.array([0.082] * 17 + [0.02] * 3 + [0.081] * 10 + [0.01] * 10)
    coarse = select_grid_boundaries(labels, scores, "coarse")
    fine = select_grid_boundaries(labels, scores, "fine")
    assert coarse == select_recall_boundaries(labels, scores, 0.85)
    assert coarse["inner_training_metrics"]["medium"]["fp"] == 10
    assert fine["inner_training_metrics"]["medium"]["fp"] == 0
    assert fine["inner_training_metrics"]["medium"]["tp"] == 17
    assert fine["medium"] == 0.082


def test_selection_sees_training_only_and_both_grids_share_fits():
    matrices, labels = population_matrices()
    validation_ids = list(labels.index[40:])
    records = []
    _, before, winner = evaluate_training_fold(matrices, labels.iloc[:40], validation_ids,
                                               lambda name, columns: RecordingPair(records), inner_splits=2)
    assert len(records) == len(CANDIDATES) * 3  # two inner fits + one outer fit, NOT twice per grid
    for record in records:
        assert not record["fit"] & set(validation_ids)
        assert all(not record["fit"] & scored for scored in record["predict"])
    changed = {name: X.copy() for name, X in matrices.items()}
    for X in changed.values():
        X.loc[validation_ids, "HR_latest"] = 0.99
    _, after, after_winner = evaluate_training_fold(changed, labels.iloc[:40], validation_ids,
                                                   lambda name, columns: RecordingPair([]), inner_splits=2)
    assert before == after
    assert winner == after_winner


def test_missing_cases_remain_unassessed_and_grid_does_not_change_ranking():
    matrices, labels = population_matrices()
    results = evaluate_forest_tuning(matrices, labels, list(labels.index), [999],
                                     lambda name, columns: RecordingPair([]), outer_splits=3, inner_splits=2)
    for grid in ("coarse", "fine"):
        for metrics in results["results"][grid].values():
            assert metrics["any_warning"]["assessed_patients"] == 58
            assert metrics["any_warning"]["unassessed_death_labels"] == 1
    for name in results["results"]["coarse"]:
        assert results["results"]["coarse"][name]["roc_auc"] == results["results"]["fine"][name]["roc_auc"]
    assert results["research_promotion_gate"]["passed"] is False


def test_separated_patient_rejected_before_any_fit():
    matrices, labels = population_matrices()
    records = []
    with pytest.raises(ValueError, match="overlap"):
        evaluate_forest_tuning(matrices, labels, list(labels.index), [labels.index[0]],
                               lambda name, columns: RecordingPair(records))
    assert not records


def test_coverage_disagreement_rejected():
    matrices, labels = population_matrices()
    matrices["recent"].loc[labels.index[2], "HR_count"] = 1
    with pytest.raises(ValueError, match="coverage"):
        evaluate_training_fold(matrices, labels.iloc[:40], list(labels.index[40:]), inner_splits=2)
