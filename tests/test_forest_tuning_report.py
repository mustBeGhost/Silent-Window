"""Saved study, prior controls, and displayed counts must agree."""

import json
from pathlib import Path

from scripts.evaluate_forest_tuning import website_summary
from scripts.train_rf_v2_artifacts import file_sha256

ROOT = Path(__file__).resolve().parents[1]


def test_report_preserves_prior_evidence_and_reproduces_controls():
    report = json.loads((ROOT / "data/processed/evaluation_v3/forest_tuning_metrics.json").read_text())
    for hashes in (report["source_sha256"], report["protected_file_sha256"]):
        for path, digest in hashes.items():
            assert file_sha256(ROOT / path) == digest, path
    prior = json.loads((ROOT / "data/processed/evaluation_v3/model_improvement_metrics.json").read_text())
    for name, old_name in (("rf_v2", "rf_v2"), ("recent_reference", "rf_recent")):
        assert report["results"]["coarse"][name] == prior["results"][old_name]
    assert report["separated_patients_evaluated"] == 0
    assert report["controls_reproduced"] is True
    assert report["model_selection"]["outer_labels_used_for_selection"] is False
    assert report["model_selection"]["selection_grid"] == "fine"
    assert report["model_selection"]["both_grids_reuse_identical_predictions"] is True
    for fold in report["fold_results"]:
        for selection in fold["selections"].values():
            fine = selection["fine"]["inner_training_metrics"]["medium"]
            coarse = selection["coarse"]["inner_training_metrics"]["medium"]
            assert fine["recall"] >= 0.85
            assert fine["fp"] <= coarse["fp"]
    for name in report["results"]["coarse"]:
        for metric in ("roc_auc", "average_precision", "brier_score"):
            assert report["results"]["coarse"][name][metric] == report["results"]["fine"][name][metric]
    selected = report["results"]["fine"]["training_selected"]["any_warning"]
    expected = all(selected["tp"] >= report["results"][grid]["rf_v2"]["any_warning"]["tp"] and
                   selected["fp"] <= report["results"][grid]["rf_v2"]["any_warning"]["fp"] * 0.9
                   for grid in ("coarse", "fine"))
    assert report["research_promotion_gate"]["passed"] == expected


def test_website_is_exact_aggregate_export():
    report = json.loads((ROOT / "data/processed/evaluation_v3/forest_tuning_metrics.json").read_text())
    website = json.loads((ROOT / "frontend/src/data/forestTuning.json").read_text())
    assert website == website_summary(report)
    assert len(website["candidate_definitions"]) == 5
    assert len(website["selected_in_folds"]) == 5
    for key in ("patient_id", "patient_ids", "validation_ids", "y_prob", "y_true"):
        assert f'"{key}"' not in json.dumps(report)
