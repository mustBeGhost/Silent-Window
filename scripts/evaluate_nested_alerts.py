"""Evaluate new thresholds and full alert sequences, without deploying a model.

Run from the project folder: python -m scripts.evaluate_nested_alerts
Only aggregate development results are saved. No patient predictions are saved.
"""

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn

from ml.alert_evaluation import CHECKPOINTS, RECALL_FLOORS, THRESHOLD_GRID, evaluate_nested_alerts
from ml.coverage import COVERAGE_POLICY
from ml.data_loader import get_outcomes_path, get_patient_dir
from ml.features import build_feature_matrix, get_feature_columns_v2
from ml.train_models import CUTOFFS, RANDOM_STATE, audit_matrix
from scripts.evaluate_scoreable_models import calibrated_rf_candidate
from scripts.train_rf_v2_artifacts import (
    ARTIFACT_FILENAMES, MANIFEST_PATH, cohort_fingerprint, file_sha256,
    load_development_patients, load_development_target, validated_training_cohorts,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "data/processed/evaluation_v3/nested_alert_metrics.json"
SOURCE_FILES = (
    "ml/alert_evaluation.py", "ml/alert_policy.py", "ml/coverage.py", "ml/evaluation.py",
    "ml/features.py", "ml/preprocessing.py", "ml/threshold_analysis.py", "ml/train_models.py",
    "ml/data_loader.py", "scripts/evaluate_nested_alerts.py", "scripts/evaluate_scoreable_models.py",
    "scripts/train_rf_v2_artifacts.py",
)


def main():
    development, separated = validated_training_cohorts()
    protected_paths = {"manifest": MANIFEST_PATH, **{
        checkpoint: MANIFEST_PATH.parent / filename for checkpoint, filename in ARTIFACT_FILENAMES.items()
    }}
    protected_hashes = {name: file_sha256(path) for name, path in protected_paths.items()}
    sources = {name: file_sha256(PROJECT_ROOT / name) for name in SOURCE_FILES}
    outcomes_hash = file_sha256(get_outcomes_path())
    split_path = PROJECT_ROOT / "data/processed/baseline/split_metadata.json"
    split_hash = file_sha256(split_path)
    raw_digest = hashlib.sha256()
    for patient_id in sorted(development):
        raw_digest.update(f"{patient_id}:{file_sha256(get_patient_dir() / f'{patient_id}.txt')}\n".encode("ascii"))
    print("Loading development patients only; separated patients will not be scored", flush=True)
    patient_data = load_development_patients(development)
    target = load_development_target(development)
    matrices = {}
    for checkpoint in CHECKPOINTS:
        print(f"Building prefix-only features at {checkpoint}", flush=True)
        matrices[checkpoint] = build_feature_matrix(development, patient_data, CUTOFFS[checkpoint], version=2)
        audit_matrix(matrices[checkpoint], f"{checkpoint}_nested_alert_evaluation")
    del patient_data
    columns = get_feature_columns_v2()
    results = evaluate_nested_alerts(
        matrices, target, development, separated, lambda: calibrated_rf_candidate(columns),
        outer_splits=5, inner_splits=3, random_state=RANDOM_STATE,
        progress=lambda message: print(message, flush=True),
    )
    if any(file_sha256(path) != protected_hashes[name] for name, path in protected_paths.items()):
        raise RuntimeError("Production artifacts changed during evaluation")
    if any(file_sha256(PROJECT_ROOT / name) != digest for name, digest in sources.items()):
        raise RuntimeError("Experiment source changed while running; repeat the evaluation")
    if file_sha256(get_outcomes_path()) != outcomes_hash or file_sha256(split_path) != split_hash:
        raise RuntimeError("Outcomes or frozen split changed while running")
    report = {
        "schema_version": 1,
        "status": "EXPLORATORY_NESTED_DEVELOPMENT_ONLY_NOT_DEPLOYED",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": "In-hospital_death",
        "coverage_policy": COVERAGE_POLICY,
        "clinical_checkpoint_eligibility": "UNKNOWN_FROM_AVAILABLE_FIELDS",
        "runtime_versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__, "pandas": pd.__version__},
        "outer_cv": {"n_splits": 5, "random_state": RANDOM_STATE, "stratified": True,
                     "shuffle": True, "same_patient_fold_at_every_checkpoint": True,
                     "folds_assigned_before_coverage_filter": True},
        "threshold_selection": {
            "primary_checkpoint": "12h", "shared_across_checkpoints": True,
            "inner_cv_splits": 3, "random_state": RANDOM_STATE,
            "grid": list(THRESHOLD_GRID), "engineering_recall_floors": RECALL_FLOORS,
            "objective": "minimum FPR meeting recall floor; precision then higher threshold break ties",
            "fallback": "maximum recall when a floor is infeasible; medium < high always enforced",
            "validation_labels_used_for_selection": False,
            "inner_metrics_are_training_selection_diagnostics_not_validation_performance": True,
        },
        "calibration": {"method": "sigmoid", "inner_cv_splits": 3, "ensemble": False,
                        "fitted_inside_each_threshold_training_fold_and_outer_training_fold": True},
        "paired_raw_reference": "final base forest from each ensemble=False calibrated fit",
        "alert_policy": "LOW: NO_ALERT; isolated MEDIUM/HIGH: WATCH; consecutive MEDIUM/HIGH: HIGH_ALERT; missing breaks persistence",
        "high_boundary_effect": "Changes HIGH risk category; does not change WATCH/HIGH_ALERT persistence",
        "development_cohort_sha256": cohort_fingerprint(development),
        "separated_cohort_sha256": cohort_fingerprint(separated),
        "separated_patients_evaluated": 0,
        "raw_development_patient_files_sha256": raw_digest.hexdigest(),
        "outcomes_sha256": outcomes_hash, "split_sha256": split_hash,
        "production_artifact_sha256": protected_hashes,
        "source_sha256": sources,
        **results,
        "limitations": [
            "Development patients were previously examined; nested CV is not an untouched final test.",
            "Engineering recall floors were declared before this run, not derived from clinical requirements.",
            "False positives mean survivor labels with a warning; they are not proven unnecessary clinical alarms.",
            "First warning checkpoint is not a validated lead time before deterioration or death.",
            "Observation-scoreability does not confirm alive-and-in-ICU eligibility or adequate medical information.",
            "One threshold pair is chosen per outer training fold; there is no deployable global threshold in this report.",
            "No model artifacts, runtime boundaries, or historical website performance data were changed.",
            "No individual patient predictions or alert histories were persisted.",
        ],
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Aggregate results saved to {OUTPUT_PATH}; production model files unchanged", flush=True)


if __name__ == "__main__":
    main()
