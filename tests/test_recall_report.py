"""The website and saved evidence must describe the same completed experiment."""

import json
from pathlib import Path

from scripts.evaluate_recall_targets import frontend_summary
from scripts.train_rf_v2_artifacts import file_sha256

ROOT = Path(__file__).resolve().parents[1]


def test_saved_report_sources_and_protected_models_still_match():
    report = json.loads((ROOT / "data/processed/evaluation_v3/recall_target_metrics.json").read_text())
    for files in (report["source_sha256"], report["protected_file_sha256"]):
        for name, digest in files.items():
            assert file_sha256(ROOT / name) == digest, name
    assert report["separated_patients_evaluated"] == 0
    assert report["70_percent_control_reproduced"] is True


def test_website_summary_is_exact_aggregate_export_and_control_reproduces_prior_report():
    report = json.loads((ROOT / "data/processed/evaluation_v3/recall_target_metrics.json").read_text())
    website = json.loads((ROOT / "frontend/src/data/recallExperiments.json").read_text())
    baseline = json.loads((ROOT / "data/processed/evaluation_v3/nested_alert_metrics.json").read_text())
    assert website == frontend_summary(report)
    assert "patient_id" not in json.dumps(website)
    for kind in ("raw", "calibrated"):
        assert report["results"][kind]["70"] == baseline["results"][f"{kind}_nested"]
