"""Final candidate fitting preserves training-only selection and coverage guards."""

import numpy as np
import pytest

from ml.candidate_training import fit_research_candidate
from tests.test_nested_alert_evaluation import RecordingPair, population


def test_final_threshold_selection_has_no_self_fit_predictions_and_masks_missing_inputs():
    matrices, labels = population()
    recordings = []
    models, diagnostics = fit_research_candidate(
        matrices, labels, list(labels.index), [999], lambda: RecordingPair(recordings), n_splits=3,
    )
    assert len(recordings) == 6
    selected_ids = set()
    for record in recordings[:3]:
        prediction_ids = set.union(*record["predict"])
        assert record["fit"].isdisjoint(prediction_ids)
        assert record["fit"].isdisjoint(set(labels.index[2:4]))
        assert selected_ids.isdisjoint(prediction_ids)
        selected_ids |= prediction_ids
    assert selected_ids == set(labels.index) - set(labels.index[2:4])
    for record, checkpoint in zip(recordings[3:], ("6h", "12h", "24h"), strict=True):
        expected = set(matrices[checkpoint].index[matrices[checkpoint]["HR_count"] > 0])
        assert record["fit"] == expected
        assert not record["predict"]  # final fitting performs no evaluation
        assert diagnostics["training_coverage"][checkpoint]["patients_fitted"] == len(expected)
    assert set(models) == {"6h", "12h", "24h"}
    assert 0 <= diagnostics["selected_boundaries"]["medium"] < diagnostics["selected_boundaries"]["high"] <= 1


def test_separated_patient_cannot_enter_final_fitting():
    matrices, labels = population()
    recordings = []
    with pytest.raises(ValueError, match="overlap"):
        fit_research_candidate(matrices, labels, list(labels.index), [labels.index[0]], lambda: RecordingPair(recordings))
    assert not recordings


def test_invalid_inputs_abort_before_candidate_fitting():
    matrices, labels = population()
    matrices["6h"].loc[labels.index[0], "HR_latest"] = np.inf
    recordings = []
    with pytest.raises(ValueError, match="Infinite"):
        fit_research_candidate(matrices, labels, list(labels.index), [999], lambda: RecordingPair(recordings))
    assert not recordings
