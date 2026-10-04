"""Run paired high-recall experiments; save aggregates, never patient scores."""

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn

from ml.alert_evaluation import THRESHOLD_GRID
from ml.coverage import COVERAGE_POLICY
from ml.data_loader import get_outcomes_path, get_patient_dir
from ml.features import build_feature_matrix, get_feature_columns_v2
from ml.recall_experiments import CHECKPOINTS, RECALL_TARGETS, evaluate_recall_targets
from ml.train_models import CUTOFFS, RANDOM_STATE, audit_matrix
from scripts.evaluate_nested_alerts import SOURCE_FILES as BASE_SOURCES
from scripts.evaluate_scoreable_models import calibrated_rf_candidate
from scripts.train_rf_v2_artifacts import (
    cohort_fingerprint, file_sha256, load_development_patients,
    load_development_target, validated_training_cohorts,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/processed/evaluation_v3/recall_target_metrics.json"
FRONTEND_OUTPUT = ROOT / "frontend/src/data/recallExperiments.json"
BASELINE = ROOT / "data/processed/evaluation_v3/nested_alert_metrics.json"
SOURCES = (*BASE_SOURCES, "ml/recall_experiments.py", "scripts/evaluate_recall_targets.py")


def frontend_summary(report):
    return {
        "status": report["status"], "completed_at_utc": report["completed_at_utc"],
        "primary_checkpoint": "12h", "development_patients": report["development_patients"],
        "death_labels": report["death_labels"], "validation_method": "5 outer patient folds; 3 inner threshold folds",
        "models": {kind: [{"training_recall_target": float(floor) / 100,
                            **values["checkpoints"]["12h"]} for floor, values in targets.items()]
                   for kind, targets in report["results"].items()},
    }


def raw_digest(development):
    digest = hashlib.sha256()
    for patient_id in sorted(development):
        digest.update(f"{patient_id}:{file_sha256(get_patient_dir() / f'{patient_id}.txt')}\n".encode("ascii"))
    return digest.hexdigest()


def main():
    development, separated = validated_training_cohorts()
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    protected_paths = list((ROOT / "ml/artifacts").glob("rf_v2*")) + list((ROOT / "ml/artifacts/calibrated_rf_v3").glob("*"))
    protected_paths += [BASELINE, ROOT / "data/processed/evaluation_v3/development_metrics.json"]
    protected = {str(path.relative_to(ROOT)): file_sha256(path) for path in protected_paths if path.is_file()}
    sources = {name: file_sha256(ROOT / name) for name in SOURCES}
    outcomes_hash = file_sha256(get_outcomes_path())
    split_path = ROOT / "data/processed/baseline/split_metadata.json"
    split_hash = file_sha256(split_path)
    raw_hash = raw_digest(development)
    checks = {
        "raw_development_patient_files_sha256": raw_hash, "outcomes_sha256": outcomes_hash,
        "split_sha256": split_hash, "development_cohort_sha256": cohort_fingerprint(development),
        "separated_cohort_sha256": cohort_fingerprint(separated),
    }
    if any(baseline[key] != value for key, value in checks.items()):
        raise RuntimeError("Data or cohort differs from the earlier 70% experiment")
    print("Loading development data only. Recall targets fixed at 70%, 85%, 90% before evaluation.", flush=True)
    patient_data = load_development_patients(development)
    target = load_development_target(development)
    matrices = {}
    for checkpoint in CHECKPOINTS:
        print(f"Building prefix-only features at {checkpoint}", flush=True)
        matrices[checkpoint] = build_feature_matrix(development, patient_data, CUTOFFS[checkpoint], version=2)
        audit_matrix(matrices[checkpoint], f"{checkpoint}_recall_targets")
    del patient_data
    result = evaluate_recall_targets(
        matrices, target, development, separated, lambda: calibrated_rf_candidate(get_feature_columns_v2()),
        outer_splits=5, inner_splits=3, random_state=RANDOM_STATE,
        progress=lambda message: print(message, flush=True),
    )
    for kind in ("raw", "calibrated"):
        if result["results"][kind]["70"] != baseline["results"][f"{kind}_nested"]:
            raise RuntimeError("70% control failed to reproduce the previous aggregate results")
    if any(file_sha256(ROOT / name) != digest for name, digest in protected.items()):
        raise RuntimeError("Protected artifacts or prior reports changed")
    if any(file_sha256(ROOT / name) != digest for name, digest in sources.items()):
        raise RuntimeError("Experiment source changed while running")
    if raw_digest(development) != raw_hash or file_sha256(get_outcomes_path()) != outcomes_hash or file_sha256(split_path) != split_hash:
        raise RuntimeError("Input data changed while running")
    report = {
        "schema_version": 1, "status": "EXPLORATORY_NESTED_DEVELOPMENT_ONLY_NOT_DEPLOYED",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(), "target": "In-hospital_death",
        "coverage_policy": COVERAGE_POLICY, "clinical_checkpoint_eligibility": "UNKNOWN_FROM_AVAILABLE_FIELDS",
        "runtime_versions": {"python": platform.python_version(), "sklearn": sklearn.__version__,
                             "numpy": np.__version__, "pandas": pd.__version__}, "outer_cv": baseline["outer_cv"],
        "calibration": baseline["calibration"], "threshold_selection": {
            **baseline["threshold_selection"], "engineering_recall_floors": {"medium": list(RECALL_TARGETS), "high": 0.30},
            "grid": list(THRESHOLD_GRID), "targets_reuse_same_models_and_patient_folds": True,
        }, "alert_policy": baseline["alert_policy"], "high_boundary_effect": baseline["high_boundary_effect"],
        **checks, "source_sha256": sources, "protected_file_sha256": protected,
        "separated_patients_evaluated": 0, "70_percent_control_reproduced": True, **result,
        "limitations": [
            "Targets refer to any warning (WATCH or HIGH_ALERT) at 12h; they are not guarantees on validation patients.",
            "Higher recall alone does not mean higher overall accuracy or better patient outcomes.",
            "Survivor warnings are false positives against death labels, not proven unnecessary clinical alerts.",
            "Development patients were previously examined; this is not an untouched final test.",
            "Clinical timing and checkpoint eligibility are unknown. These are assessment times, not prediction horizons.",
            "Fold-specific thresholds cannot be averaged into a deployable setting. Runtime thresholds remain unchanged.",
            "No individual patient scores were persisted; no models were installed or replaced.",
        ],
    }
    OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    FRONTEND_OUTPUT.write_text(json.dumps(frontend_summary(report), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("Saved aggregate report and website summary; model bundles and runtime thresholds unchanged.", flush=True)
    for kind, targets in result["results"].items():
        for floor, values in targets.items():
            metrics = values["checkpoints"]["12h"]["any_warning"]
            print(f"{kind} target {floor}%: detected {metrics['tp']}, missed {metrics['fn']}, survivor warnings {metrics['fp']}", flush=True)


if __name__ == "__main__":
    main()
