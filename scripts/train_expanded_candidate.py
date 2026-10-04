"""Fit a separate five-time research bundle after checking evaluation provenance."""
import json
import os
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import joblib
import sklearn
from threadpoolctl import threadpool_limits
from ml.checkpoint_expansion import CUTOFFS, fit_expanded_candidate
from ml.checkpoint_profiles import MODEL_PROFILES
from ml.coverage import COVERAGE_POLICY
from ml.data_loader import get_outcomes_path
from ml.features import build_feature_matrix, get_feature_columns_v2
from scripts.evaluate_checkpoint_expansion import SOURCES as EVALUATION_SOURCES
from scripts.evaluate_recall_targets import raw_digest
from scripts.evaluate_scoreable_models import calibrated_rf_candidate
from scripts.train_rf_v2_artifacts import (cohort_fingerprint, file_sha256, load_development_patients,
                                         load_development_target, validated_training_cohorts)

ROOT = Path(__file__).resolve().parents[1]
PROFILE = MODEL_PROFILES["expanded"]
SOURCE_FILES = (*EVALUATION_SOURCES, "ml/checkpoint_profiles.py", "scripts/train_expanded_candidate.py")


def main():
    destination = ROOT / "ml/artifacts" / PROFILE["directory"]
    if destination.exists():
        raise RuntimeError("Research destination exists; refusing to overwrite")
    evidence_path = ROOT / "data/processed/evaluation_v3/checkpoint_expansion_metrics.json"
    evidence = json.loads(evidence_path.read_text())
    development, separated = validated_training_cohorts()
    checks = {"raw_development_patient_files_sha256": raw_digest(development),
              "outcomes_sha256": file_sha256(get_outcomes_path()),
              "split_sha256": file_sha256(ROOT / "data/processed/baseline/split_metadata.json"),
              "development_cohort_sha256": cohort_fingerprint(development),
              "separated_cohort_sha256": cohort_fingerprint(separated)}
    if any(evidence[key] != value for key, value in checks.items()) or evidence["separated_patients_evaluated"] != 0 or not evidence["control_reproduced"]:
        raise RuntimeError("Research evidence does not match the frozen protocol")
    if any(file_sha256(ROOT / name) != digest for name, digest in evidence["source_sha256"].items()):
        raise RuntimeError("Research evidence sources are stale")
    protected = dict(evidence["protected_file_sha256"])
    protected[str(evidence_path.relative_to(ROOT))] = file_sha256(evidence_path)
    sources = {name: file_sha256(ROOT / name) for name in SOURCE_FILES}
    print("Fitting separate five-checkpoint research bundle; earlier bundles preserved.", flush=True)
    patients = load_development_patients(development)
    target = load_development_target(development)
    matrices = {}
    for cp, cutoff in CUTOFFS.items():
        print(f"Building {cp} development training features", flush=True)
        matrices[cp] = build_feature_matrix(development, patients, cutoff, version=2)
    del patients
    with threadpool_limits(limits=1):
        models, training = fit_expanded_candidate(matrices, target, development, separated,
                    lambda: calibrated_rf_candidate(get_feature_columns_v2()), progress=lambda message: print(message, flush=True))
    for hashes in (protected, sources):
        if any(file_sha256(ROOT / name) != digest for name, digest in hashes.items()):
            raise RuntimeError("Protected source or evidence changed during training")
    if raw_digest(development) != checks["raw_development_patient_files_sha256"] or file_sha256(get_outcomes_path()) != checks["outcomes_sha256"] or file_sha256(ROOT / "data/processed/baseline/split_metadata.json") != checks["split_sha256"]:
        raise RuntimeError("Training inputs changed during the run")
    staging = Path(tempfile.mkdtemp(prefix=".expanded_rf_v4.build-", dir=destination.parent))
    artifacts = {}
    for cp, model in models.items():
        path = staging / PROFILE["filenames"][cp]
        joblib.dump(model, path, compress=3)
        artifacts[cp] = {"filename": path.name, "cutoff_minutes": CUTOFFS[cp], "size_bytes": path.stat().st_size, "sha256": file_sha256(path)}
    medium, high = (training["selected_boundaries"][name] for name in ("medium", "high"))
    manifest = {"model_profile": "expanded", "bundle_version": "expanded_rf_v4", "status": "RESEARCH_CANDIDATE_NOT_CLINICALLY_VALIDATED",
                "created_at_utc": datetime.now(timezone.utc).isoformat(), "target": "In-hospital_death",
                "feature_version": "V2", "feature_count": len(get_feature_columns_v2()), "ordered_input_features": get_feature_columns_v2(),
                "supported_cutoffs": CUTOFFS, "primary_cutoff": "12h", "coverage_policy": COVERAGE_POLICY,
                "calibration": {"method": "sigmoid", "cv_splits": 3, "ensemble": False, "random_state": 42},
                "thresholds": {"medium": medium, "high": high},
                "risk_boundaries": {"LOW": f"probability < {medium:.2f}", "MEDIUM": f"{medium:.2f} <= probability < {high:.2f}", "HIGH": f"probability >= {high:.2f}"},
                "threshold_selection": {"checkpoint": "12h", "engineering_recall_floor": 0.85, "cv_splits": 3,
                                        "diagnostics_are_training_tuning_not_independent_validation": True},
                **training, **checks, "development_cohort_size": len(development), "separated_cohort_size": len(separated),
                "separated_patients_excluded_from_fitting": True, "separated_patients_evaluated": 0,
                "source_sha256": sources, "protected_file_sha256": protected,
                "evaluation_evidence_sha256": {str(evidence_path.relative_to(ROOT)): file_sha256(evidence_path)},
                "runtime_versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "joblib": joblib.__version__},
                "artifacts": artifacts, "limitations": evidence["limitations"]}
    (staging / PROFILE["manifest_filename"]).write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    if destination.exists():
        raise RuntimeError("Research destination appeared during training")
    os.replace(staging, destination)
    print(f"Saved five research models. Training-selected boundaries: {medium:.2f}/{high:.2f}", flush=True)


if __name__ == "__main__":
    main()
