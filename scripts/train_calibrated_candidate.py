"""Build a separate research bundle; never replace the historical model files.

Run: python -m scripts.train_calibrated_candidate
An existing destination is refused. Use --output-dir for a separate rerun.
"""

import argparse
import hashlib
import json
import os
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import joblib
import sklearn

from ml.alert_evaluation import RECALL_FLOORS, THRESHOLD_GRID
from ml.candidate_training import fit_research_candidate
from ml.coverage import COVERAGE_POLICY
from ml.data_loader import get_outcomes_path, get_patient_dir
from ml.features import build_feature_matrix, get_feature_columns_v2
from ml.model_profiles import MODEL_PROFILES
from ml.train_models import CUTOFFS, RANDOM_STATE, audit_matrix
from scripts.evaluate_scoreable_models import calibrated_rf_candidate
from scripts.train_rf_v2_artifacts import (
    ARTIFACT_FILENAMES, MANIFEST_PATH, cohort_fingerprint, file_sha256,
    load_development_patients, load_development_target, validated_training_cohorts,
)


ROOT = Path(__file__).resolve().parents[1]
PROFILE = MODEL_PROFILES["calibrated"]
DEFAULT_OUTPUT = ROOT / "ml/artifacts" / PROFILE["directory"]
SOURCE_FILES = (
    "ml/candidate_training.py", "ml/model_profiles.py", "ml/alert_evaluation.py",
    "ml/alert_policy.py", "ml/coverage.py", "ml/evaluation.py", "ml/features.py",
    "ml/preprocessing.py", "ml/threshold_analysis.py", "ml/train_models.py", "ml/data_loader.py",
    "scripts/evaluate_scoreable_models.py", "scripts/train_rf_v2_artifacts.py", "scripts/train_calibrated_candidate.py",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    destination = parser.parse_args().output_dir.resolve()
    if destination.exists():
        raise RuntimeError("Candidate destination already exists; choose a new --output-dir")
    development, separated = validated_training_cohorts()
    protected = {"manifest": MANIFEST_PATH, **{
        checkpoint: MANIFEST_PATH.parent / filename for checkpoint, filename in ARTIFACT_FILENAMES.items()
    }}
    original_hashes = {name: file_sha256(path) for name, path in protected.items()}
    source_hashes = {name: file_sha256(ROOT / name) for name in SOURCE_FILES}
    evidence_paths = {
        "score_comparison": ROOT / "data/processed/evaluation_v3/development_metrics.json",
        "nested_alert_evaluation": ROOT / "data/processed/evaluation_v3/nested_alert_metrics.json",
    }
    evidence_hashes = {name: file_sha256(path) for name, path in evidence_paths.items()}
    for path in evidence_paths.values():
        evidence = json.loads(path.read_text())
        if evidence["development_cohort_sha256"] != cohort_fingerprint(development) or evidence["separated_patients_evaluated"] != 0:
            raise RuntimeError("Candidate evidence does not match the frozen development protocol")
        if any(file_sha256(ROOT / name) != digest for name, digest in evidence["source_sha256"].items()):
            raise RuntimeError("Evaluation evidence has stale source hashes; review and repeat before training")
    raw_digest = hashlib.sha256()
    for patient_id in sorted(development):
        raw_digest.update(f"{patient_id}:{file_sha256(get_patient_dir() / f'{patient_id}.txt')}\n".encode("ascii"))
    outcomes_hash = file_sha256(get_outcomes_path())
    split_path = ROOT / "data/processed/baseline/split_metadata.json"
    split_hash = file_sha256(split_path)
    print("Loading only development patients for the research candidate", flush=True)
    patient_data = load_development_patients(development)
    target = load_development_target(development)
    matrices = {}
    for checkpoint, cutoff in CUTOFFS.items():
        print(f"Building prefix-only training features at {checkpoint}", flush=True)
        matrices[checkpoint] = build_feature_matrix(development, patient_data, cutoff, version=2)
        audit_matrix(matrices[checkpoint], f"{checkpoint}_calibrated_candidate_training")
    del patient_data
    columns = get_feature_columns_v2()
    models, training = fit_research_candidate(
        matrices, target, development, separated, lambda: calibrated_rf_candidate(columns),
        n_splits=3, random_state=RANDOM_STATE, progress=lambda message: print(message, flush=True),
    )
    medium, high = (training["selected_boundaries"][name] for name in ("medium", "high"))
    if any(file_sha256(ROOT / name) != digest for name, digest in source_hashes.items()):
        raise RuntimeError("Training source changed during the run")
    if any(file_sha256(path) != original_hashes[name] for name, path in protected.items()):
        raise RuntimeError("Historical artifacts changed during training")
    if file_sha256(get_outcomes_path()) != outcomes_hash or file_sha256(split_path) != split_hash:
        raise RuntimeError("Outcomes or frozen split changed during training")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".calibrated_rf_v3.build-", dir=destination.parent))
    artifacts = {}
    for checkpoint, model in models.items():
        filename = PROFILE["filenames"][checkpoint]
        artifact_path = staging / filename
        joblib.dump(model, artifact_path, compress=3)
        artifacts[checkpoint] = {
            "filename": filename, "cutoff_minutes": CUTOFFS[checkpoint],
            "size_bytes": artifact_path.stat().st_size, "sha256": file_sha256(artifact_path),
        }
    manifest = {
        "model_profile": "calibrated", "bundle_version": "calibrated_rf_v3",
        "status": "RESEARCH_CANDIDATE_NOT_CLINICALLY_VALIDATED",
        "model_type": "SigmoidCalibratedRandomForestClassifier",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": "In-hospital_death", "clinical_checkpoint_eligibility": "UNKNOWN_FROM_AVAILABLE_FIELDS",
        "feature_version": "V2", "feature_count": len(columns), "ordered_input_features": columns,
        "supported_cutoffs": CUTOFFS, "primary_cutoff": "12h",
        "coverage_policy": COVERAGE_POLICY,
        "calibration": {"method": "sigmoid", "cv_splits": 3, "ensemble": False, "random_state": RANDOM_STATE},
        "thresholds": {"medium": medium, "high": high},
        "risk_boundaries": {"LOW": f"probability < {medium:.2f}",
                            "MEDIUM": f"{medium:.2f} <= probability < {high:.2f}",
                            "HIGH": f"probability >= {high:.2f}"},
        "threshold_selection": {"checkpoint": "12h", "cv_splits": 3, "random_state": RANDOM_STATE,
                                "folds_assigned_before_coverage_filter": True, "grid": list(THRESHOLD_GRID),
                                "engineering_recall_floors": RECALL_FLOORS,
                                "diagnostics_are_training_tuning_not_independent_validation": True},
        **training,
        "development_cohort_size": len(development), "development_cohort_sha256": cohort_fingerprint(development),
        "separated_cohort_size": len(separated), "separated_cohort_sha256": cohort_fingerprint(separated),
        "separated_patients_excluded_from_fitting": True, "separated_patients_evaluated": 0,
        "raw_development_patient_files_sha256": raw_digest.hexdigest(),
        "outcomes_sha256": outcomes_hash, "split_sha256": split_hash,
        "historical_artifact_sha256": original_hashes, "evaluation_evidence_sha256": evidence_hashes,
        "source_sha256": source_hashes,
        "runtime_versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "joblib": joblib.__version__},
        "artifacts": artifacts,
        "limitations": ["No untouched final test was used.", "Calibration has not established individual clinical probability accuracy.",
                        "Nested development evaluation showed no clear gain in warning accuracy.",
                        "Final training-selection diagnostics are not the candidate's independently tested performance.",
                        "No individual OOF predictions are persisted."],
    }
    (staging / PROFILE["manifest_filename"]).write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if destination.exists():
        raise RuntimeError("Destination appeared during training; staged bundle retained for review")
    os.replace(staging, destination)
    print(f"Saved separate research bundle: {destination}; boundaries {medium:.2f}/{high:.2f}", flush=True)


if __name__ == "__main__":
    main()
