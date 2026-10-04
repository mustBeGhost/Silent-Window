"""Extra times must preserve patient separation, missing data and chronology."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.checkpoint_expansion import CUTOFFS, evaluate_expansion, fit_expanded_candidate, summarize_expanded_sequence
from scripts.train_rf_v2_artifacts import file_sha256
from tests.test_nested_alert_evaluation import RecordingPair, population

ROOT = Path(__file__).resolve().parents[1]


def expanded_population():
    matrices, labels = population()
    return {cp: matrices[cp if cp in matrices else "12h"].copy() for cp in CUTOFFS}, labels


def test_new_times_keep_validation_patients_out_of_fit_and_count_missing_separately():
    matrices, labels = expanded_population()
    records = []
    result = evaluate_expansion(matrices, labels, list(labels.index), [999],
                               lambda: RecordingPair(records), outer_splits=3, inner_splits=2)
    assert len(records) == 21  # 2 inner fits + 5 checkpoint fits per fold
    for record in records:
        assert all(record["fit"].isdisjoint(scored) for scored in record["predict"])
    for checkpoint in CUTOFFS:
        expected_missing = int((matrices[checkpoint]["HR_count"] == 0).sum())
        assert result["expanded"]["checkpoints"][checkpoint]["any_warning"]["unassessed_patients"] == expected_missing
    assert result["expanded"]["checkpoints"]["6h"]["persistent_high_alert"]["tp"] == 0


def test_final_fitting_selects_thresholds_without_self_predictions():
    matrices, labels = expanded_population()
    records = []
    models, diagnostics = fit_expanded_candidate(matrices, labels, list(labels.index), [999], lambda: RecordingPair(records))
    assert list(models) == list(CUTOFFS)
    assert len(records) == 8
    for record in records[:3]:
        assert all(record["fit"].isdisjoint(scored) for scored in record["predict"])
    assert all(not record["predict"] for record in records[3:])
    assert diagnostics["selected_boundaries"]["recall_target"] == 0.85


def test_separated_population_rejected_before_any_fit():
    matrices, labels = expanded_population()
    records = []
    with pytest.raises(ValueError, match="overlap"):
        evaluate_expansion(matrices, labels, list(labels.index), [labels.index[0]], lambda: RecordingPair(records))
    assert records == []


def test_missing_breaks_persistence_and_cumulative_counts_each_patient_once():
    scores = pd.DataFrame([[0.5, np.nan, 0.5, 0.5, 0.5], [0.5, 0.5, 0.1, 0.1, 0.1]], columns=CUTOFFS)
    labels = pd.Series([1, 0])
    limits = pd.DataFrame({"medium": [0.2, 0.2], "high": [0.4, 0.4]})
    result = summarize_expanded_sequence(scores, labels, limits)
    assert result["checkpoints"]["12h"]["persistent_high_alert"]["tp"] == 0
    assert result["checkpoints"]["18h"]["persistent_high_alert"]["tp"] == 1
    assert result["checkpoints"]["9h"]["persistent_high_alert"]["fp"] == 1
    assert result["cumulative_through_checkpoint"]["24h"]["any_warning_seen"]["tp"] == 1
    assert sum(item["patients"] for item in result["first_warning_checkpoint_counts"].values()) == 2


def test_report_preserves_hashes_reproduces_control_and_matches_website():
    report = json.loads((ROOT / "data/processed/evaluation_v3/checkpoint_expansion_metrics.json").read_text())
    baseline = json.loads((ROOT / "data/processed/evaluation_v3/recall_target_metrics.json").read_text())
    website = json.loads((ROOT / "frontend/src/data/checkpointExpansion.json").read_text())
    for group in ("source_sha256", "protected_file_sha256"):
        for name, digest in report[group].items():
            assert file_sha256(ROOT / name) == digest, name
    assert report["control"] == baseline["results"]["calibrated"]["85"]
    assert all(website[key] == report[key] for key in website)
    assert report["separated_patients_evaluated"] == 0
    assert "3h" not in report["supported_cutoffs"]
    assert report["expanded"]["cumulative_through_checkpoint"]["24h"]["any_warning_seen"]["tp"] == 345
    assert report["expanded"]["checkpoints"]["12h"]["any_warning"]["tp"] == 311
