"""Evaluate fixed 6/9/12/18/24h timeline; persist aggregates only."""

import json
from datetime import datetime, timezone
from pathlib import Path

from threadpoolctl import threadpool_limits
from ml.checkpoint_expansion import CUTOFFS, evaluate_expansion
from ml.coverage import COVERAGE_POLICY
from ml.data_loader import get_outcomes_path
from ml.features import build_feature_matrix, get_feature_columns_v2
from scripts.evaluate_recall_targets import SOURCES as BASE_SOURCES, raw_digest
from scripts.evaluate_scoreable_models import calibrated_rf_candidate
from scripts.train_rf_v2_artifacts import (cohort_fingerprint, file_sha256, load_development_patients,
                                         load_development_target, validated_training_cohorts)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/processed/evaluation_v3/checkpoint_expansion_metrics.json"
FRONTEND_OUTPUT = ROOT / "frontend/src/data/checkpointExpansion.json"
SOURCES = (*BASE_SOURCES, "ml/checkpoint_expansion.py", "scripts/evaluate_checkpoint_expansion.py")


def main():
    if OUTPUT.exists():
        raise RuntimeError("Expansion report already exists; refusing to overwrite evidence")
    development, separated = validated_training_cohorts()
    baseline_path = ROOT / "data/processed/evaluation_v3/recall_target_metrics.json"
    baseline = json.loads(baseline_path.read_text())
    protected_paths = list((ROOT / "ml/artifacts").rglob("*")) + list((ROOT / "data/processed/evaluation_v3").glob("*.json"))
    protected = {str(path.relative_to(ROOT)): file_sha256(path) for path in protected_paths if path.is_file()}
    source_hashes = {name: file_sha256(ROOT / name) for name in SOURCES}
    checks = {"raw_development_patient_files_sha256": raw_digest(development),
              "outcomes_sha256": file_sha256(get_outcomes_path()),
              "split_sha256": file_sha256(ROOT / "data/processed/baseline/split_metadata.json"),
              "development_cohort_sha256": cohort_fingerprint(development),
              "separated_cohort_sha256": cohort_fingerprint(separated)}
    if any(baseline[key] != value for key, value in checks.items()):
        raise RuntimeError("Inputs differ from the existing 85% control")
    print("Fixed protocol: five checkpoints, same calibrated RF and training-only 85% target. No 3h.", flush=True)
    patients = load_development_patients(development)
    target = load_development_target(development)
    matrices = {}
    for checkpoint, cutoff in CUTOFFS.items():
        print(f"Building prefix-only features at {checkpoint}", flush=True)
        matrices[checkpoint] = build_feature_matrix(development, patients, cutoff, version=2)
    del patients
    with threadpool_limits(limits=1):
        result = evaluate_expansion(matrices, target, development, separated,
                                   lambda: calibrated_rf_candidate(get_feature_columns_v2()),
                                   progress=lambda message: print(message, flush=True))
    if result["control"] != baseline["results"]["calibrated"]["85"]:
        raise RuntimeError("Three-time control failed to reproduce earlier results")
    for hashes in (protected, source_hashes):
        if any(file_sha256(ROOT / name) != digest for name, digest in hashes.items()):
            raise RuntimeError("Protected evidence or source changed while running")
    if raw_digest(development) != checks["raw_development_patient_files_sha256"] or file_sha256(get_outcomes_path()) != checks["outcomes_sha256"]:
        raise RuntimeError("Input data changed while running")
    report = {"schema_version": 1, "status": "EXPLORATORY_NESTED_DEVELOPMENT_ONLY",
              "completed_at_utc": datetime.now(timezone.utc).isoformat(), "target": "In-hospital_death",
              "supported_cutoffs": CUTOFFS, "primary_checkpoint": "12h", "training_recall_target": 0.85,
              "coverage_policy": COVERAGE_POLICY, "validation_method": "5 outer patient folds; 3 inner threshold folds",
              "same_scores_and_thresholds_for_shared_times": True, "control_reproduced": True,
              "separated_patients_evaluated": 0, "source_sha256": source_hashes,
              "protected_file_sha256": protected, **checks, **result,
              "limitations": ["These are assessment times, not death prediction horizons.",
                             "Exact death and ICU exit times are unavailable; warning lead time is unverified.",
                             "An 85% training recall target is not a guarantee at any assessment time.",
                             "Survivor warnings are errors against death labels, not proof that clinical review was unnecessary.",
                             "Development patients have been examined before; this is not an untouched final test.",
                             "One usable reading is only a minimum technical requirement.",
                             "Extra checkpoints may increase warnings and change persistence; they do not establish better clinical accuracy."]}
    OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    summary = {key: report[key] for key in ("completed_at_utc", "supported_cutoffs", "validation_method", "development_patients",
                                          "death_labels", "training_recall_target", "control", "expanded", "limitations")}
    FRONTEND_OUTPUT.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    for label in ("control", "expanded"):
        for cp, values in report[label]["cumulative_through_checkpoint"].items():
            m = values["any_warning_seen"]
            print(f"{label} through {cp}: death labels warned {m['tp']}, survivor labels warned {m['fp']}", flush=True)


if __name__ == "__main__":
    main()
