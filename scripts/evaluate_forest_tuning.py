"""Run the fixed focused study; protect earlier evidence and saved models."""

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sklearn
from threadpoolctl import threadpool_limits

from ml.data_loader import get_outcomes_path
from ml.features import get_feature_columns_v2
from ml.forest_tuning import CANDIDATES, GRIDS, RECALL_TARGET, evaluate_forest_tuning, forest_model
from ml.recent_features import build_recent_feature_matrix
from scripts.evaluate_model_improvements import SOURCES as PRIOR_SOURCES
from scripts.evaluate_recall_targets import raw_digest
from scripts.train_rf_v2_artifacts import cohort_fingerprint, file_sha256, load_development_patients, load_development_target, validated_training_cohorts

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/processed/evaluation_v3/forest_tuning_metrics.json"
WEBSITE = ROOT / "frontend/src/data/forestTuning.json"
BASELINE = ROOT / "data/processed/evaluation_v3/model_improvement_metrics.json"
SOURCES = (*PRIOR_SOURCES, "ml/forest_tuning.py", "scripts/evaluate_forest_tuning.py")


def website_summary(report):
    return {key: report[key] for key in (
        "status", "completed_at_utc", "development_patients", "death_labels", "primary_checkpoint",
        "training_recall_target", "candidate_definitions", "results", "research_promotion_gate") } | {
        "selected_in_folds": [fold["training_selected_candidate"] for fold in report["fold_results"]]}


def main():
    development, separated = validated_training_cohorts()
    baseline = json.loads(BASELINE.read_text())
    paths = list((ROOT / "ml/artifacts").rglob("*.joblib")) + list((ROOT / "ml/artifacts").rglob("*manifest.json"))
    paths += [path for path in (ROOT / "data/processed/evaluation_v3").glob("*.json") if path != OUTPUT]
    protected = {str(path.relative_to(ROOT)): file_sha256(path) for path in paths}
    sources = {name: file_sha256(ROOT / name) for name in SOURCES}
    data_hashes = {"raw_development_patient_files_sha256": raw_digest(development),
                   "outcomes_sha256": file_sha256(get_outcomes_path()),
                   "split_sha256": file_sha256(ROOT / "data/processed/baseline/split_metadata.json"),
                   "development_cohort_sha256": cohort_fingerprint(development),
                   "separated_cohort_sha256": cohort_fingerprint(separated)}
    if any(baseline[name] != value for name, value in data_hashes.items()):
        raise RuntimeError("Input data changed since the prior comparison")
    print("Fixed five-forest study: paired 0.01/0.001 grids, 85% training target, 12h only.", flush=True)
    print("The fine grid is the predeclared selection procedure. No separated patients evaluated.", flush=True)
    patient_data = load_development_patients(development)
    recent = build_recent_feature_matrix(development, patient_data, 720)
    del patient_data
    matrices = {"recent": recent, "v2": recent[get_feature_columns_v2()].copy()}
    with threadpool_limits(limits=1):
        results = evaluate_forest_tuning(matrices, load_development_target(development), development, separated,
                                         progress=lambda message: print(message, flush=True))
    for name, prior_name in (("rf_v2", "rf_v2"), ("recent_reference", "rf_recent")):
        if results["results"]["coarse"][name] != baseline["results"][prior_name]:
            raise RuntimeError(f"Previous control did not reproduce: {name}")
    for hashes in (protected, sources):
        if any(file_sha256(ROOT / name) != digest for name, digest in hashes.items()):
            raise RuntimeError("Protected evidence or experiment source changed during the run")
    if raw_digest(development) != data_hashes["raw_development_patient_files_sha256"] or file_sha256(get_outcomes_path()) != data_hashes["outcomes_sha256"] or file_sha256(ROOT / "data/processed/baseline/split_metadata.json") != data_hashes["split_sha256"]:
        raise RuntimeError("Input data changed during the run")
    definitions = {name: {**settings, "feature_count": len(matrices[settings["features"]].columns),
                          "classifier_settings": forest_model(name, list(matrices[settings["features"]].columns)).estimator.named_steps["classifier"].get_params()}
                   for name, settings in CANDIDATES.items()}
    report = {"schema_version": 1, "status": "EXPLORATORY_NESTED_DEVELOPMENT_ONLY_NOT_DEPLOYED",
              "completed_at_utc": datetime.now(timezone.utc).isoformat(), "target": "In-hospital_death",
              "primary_checkpoint": "12h", "training_recall_target": RECALL_TARGET,
              "runtime_versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__},
              "outer_cv": baseline["outer_cv"], "calibration": baseline["calibration"],
              "threshold_grids": {name: list(grid) for name, grid in GRIDS.items()},
              "model_selection": {"population": "INNER_OOF_TRAINING_ONLY", "selection_grid": "fine",
                                  "objective": "minimum inner FP meeting 85% recall; TP then AP then name break ties",
                                  "settings_declared_before_run": True, "outer_labels_used_for_selection": False,
                                  "both_grids_reuse_identical_predictions": True},
              "candidate_definitions": definitions, **data_hashes, "source_sha256": sources,
              "protected_file_sha256": protected, "controls_reproduced": True,
              "separated_patients_evaluated": 0, **results,
              "limitations": ["Repeated known development data; not an untouched final test.",
                              "85% is a training goal, not guaranteed validation detection.",
                              "Survivor warnings are false positives against death labels; actual clinical need is unknown.",
                              "No event times, validated advance warning, or clinical probability claims.",
                              "Only 12h warning eligibility was evaluated; persistence and other checkpoints were not retuned.",
                              "No individual predictions saved; queue models and runtime thresholds unchanged."]}
    OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    WEBSITE.write_text(json.dumps(website_summary(report), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for grid, candidates in results["results"].items():
        for name, metrics in candidates.items():
            c = metrics["any_warning"]
            print(f"{grid}/{name}: detected {c['tp']}, missed {c['fn']}, survivors warned {c['fp']}", flush=True)
    print(f"Research promotion check passed: {results['research_promotion_gate']['passed']}", flush=True)


if __name__ == "__main__":
    main()
