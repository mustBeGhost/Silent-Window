"""Completed research evidence and the app must agree without exposing patient scores."""

import json
from pathlib import Path

from scripts.evaluate_model_improvements import website_summary
from scripts.train_rf_v2_artifacts import file_sha256

ROOT = Path(__file__).resolve().parents[1]


def test_model_improvement_report_matches_source_models_and_control():
    report = json.loads((ROOT / "data/processed/evaluation_v3/model_improvement_metrics.json").read_text())
    for files in (report["source_sha256"], report["protected_file_sha256"]):
        for name, digest in files.items():
            assert file_sha256(ROOT / name) == digest, name
    baseline = json.loads((ROOT / "data/processed/evaluation_v3/recall_target_metrics.json").read_text())
    assert report["results"]["rf_v2"]["any_warning"] == baseline["results"]["calibrated"]["85"]["checkpoints"]["12h"]["any_warning"]
    assert report["separated_patients_evaluated"] == 0
    assert report["model_selection"]["outer_labels_used_for_selection"] is False
    assert report["control_reproduced"] is True
    assert report["training_selected_timeline"]["checkpoints"]["12h"]["any_warning"] == report["results"]["training_selected"]["any_warning"]


def test_model_improvement_website_export_is_exact_and_aggregate_only():
    report = json.loads((ROOT / "data/processed/evaluation_v3/model_improvement_metrics.json").read_text())
    website = json.loads((ROOT / "frontend/src/data/modelImprovements.json").read_text())
    assert website == website_summary(report)
    assert len(website["candidates"]) == 6
    assert len(website["selected_in_folds"]) == 5
    for key in ("patient_id", "patient_ids", "y_prob", "validation_ids"):
        assert f'"{key}"' not in json.dumps(report)
