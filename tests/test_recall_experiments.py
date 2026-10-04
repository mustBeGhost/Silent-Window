"""Higher recall must preserve patient separation and expose warning burden."""

import numpy as np
import pytest

from ml.alert_evaluation import select_boundaries
from ml.recall_experiments import evaluate_recall_targets, evaluate_recall_training_fold, select_recall_boundaries
from tests.test_nested_alert_evaluation import RecordingPair, population


def test_70_percent_control_matches_original_selector_exactly():
    labels = [0, 1, 0, 1, 0, 1]
    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    selection = select_recall_boundaries(labels, scores, 0.70)
    selection.pop("recall_target")
    assert selection == select_boundaries(labels, scores)


@pytest.mark.parametrize("floor", [0, -0.1, 1.01, np.nan, np.inf])
def test_invalid_target_is_rejected(floor):
    with pytest.raises(ValueError, match="Recall target"):
        select_recall_boundaries([0, 1], [0.1, 0.2], floor)


def test_higher_target_lowers_threshold_and_exposes_extra_false_positives():
    labels = [1] * 20 + [0] * 20
    scores = np.linspace(0.02, 0.9, 40)
    results = [select_recall_boundaries(labels, scores, floor) for floor in (0.70, 0.85, 0.90)]
    assert results[0]["medium"] >= results[1]["medium"] >= results[2]["medium"]
    assert all(result["recall_floor_met"]["medium"] for result in results)
    assert all(result["medium"] < result["high"] for result in results)
    assert results[2]["inner_training_metrics"]["medium"]["fp"] >= results[0]["inner_training_metrics"]["medium"]["fp"]


def test_all_targets_reuse_fits_without_validation_leakage():
    matrices, labels = population()
    records = []
    validation = list(labels.index[40:])
    _, selected = evaluate_recall_training_fold(matrices, labels.iloc[:40], validation,
                                               lambda: RecordingPair(records), inner_splits=2)
    assert len(records) == 5
    assert set(selected["calibrated"]) == {"70", "85", "90"}
    for record in records:
        assert not record["fit"] & set(validation)
        assert all(not record["fit"] & scored for scored in record["predict"])
    changed = {checkpoint: X.copy() for checkpoint, X in matrices.items()}
    for X in changed.values():
        X.loc[validation, "HR_latest"] = 0.99
    _, after = evaluate_recall_training_fold(changed, labels.iloc[:40], validation,
                                            lambda: RecordingPair([]), inner_splits=2)
    assert after == selected


def test_missing_counts_and_detection_are_reported_for_every_target():
    matrices, labels = population()
    records = []
    report = evaluate_recall_targets(matrices, labels, list(labels.index), [999],
                                     lambda: RecordingPair(records), outer_splits=3, inner_splits=2)
    assert len(records) == 15  # independent of number of targets
    for targets in report["results"].values():
        detected, survivor_warnings = [], []
        for result in targets.values():
            checkpoint = result["checkpoints"]["12h"]
            any_warning = checkpoint["any_warning"]
            high_alert = checkpoint["persistent_high_alert"]
            assert checkpoint["state_counts"]["NOT_ASSESSED"] == 2
            assert any_warning["tp"] + any_warning["fn"] == 29
            assert high_alert["tp"] <= any_warning["tp"]
            assert high_alert["fp"] <= any_warning["fp"]
            detected.append(any_warning["tp"])
            survivor_warnings.append(any_warning["fp"])
        assert detected == sorted(detected)
        assert survivor_warnings == sorted(survivor_warnings)


def test_separated_patients_rejected_before_fitting():
    matrices, labels = population()
    records = []
    with pytest.raises(ValueError, match="overlap"):
        evaluate_recall_targets(matrices, labels, list(labels.index), [labels.index[0]],
                                lambda: RecordingPair(records))
    assert records == []
