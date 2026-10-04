"""Evaluate fixed candidate models on scoreable DEVELOPMENT patients only.

No production artifact, threshold, or website performance data is changed.
No individual predictions are saved. Results are exploratory development
evidence, not a final test or verified clinical landmark evaluation.

Run: python -m scripts.evaluate_scoreable_models
"""

import hashlib
import json
from pathlib import Path

from sklearn.calibration import CalibratedClassifierCV
from sklearn.dummy import DummyClassifier
from sklearn.model_selection import StratifiedKFold

from ml.coverage import COVERAGE_POLICY
from ml.data_loader import get_outcomes_path, get_patient_dir
from ml.evaluation import scoreable_development_data, summarize_development_predictions
from ml.features import build_feature_matrix, get_feature_columns_v2
from ml.threshold_analysis import generate_oof_predictions
from ml.train_models import CUTOFFS, N_SPLITS, RANDOM_STATE, audit_matrix, build_lr_pipeline, build_rf_pipeline
from scripts.train_rf_v2_artifacts import (
    ARTIFACT_FILENAMES, MANIFEST_PATH, cohort_fingerprint, file_sha256,
    load_development_patients, load_development_target, validated_training_cohorts,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "data" / "processed" / "evaluation_v3" / "development_metrics.json"


def rf_candidate(columns):
    pipeline = build_rf_pipeline(columns)
    pipeline.set_params(classifier__n_jobs=1)
    return pipeline


def calibrated_rf_candidate(columns):
    # The calibrator sees ONLY the outer training fold. Inner OOF predictions
    # fit sigmoid calibration; the outer validation fold never fits any step.
    return CalibratedClassifierCV(
        estimator=rf_candidate(columns), method="sigmoid", ensemble=False,
        cv=StratifiedKFold(n_splits=3, shuffle=True, random_state=RANDOM_STATE),
        n_jobs=1,
    )


def main() -> None:
    development, separated = validated_training_cohorts()
    manifest_hash = file_sha256(MANIFEST_PATH)
    artifact_hashes = {
        name: file_sha256(MANIFEST_PATH.parent / filename)
        for name, filename in ARTIFACT_FILENAMES.items()
    }
    raw_digest = hashlib.sha256()
    for patient_id in sorted(development):
        raw_digest.update(f"{patient_id}:{file_sha256(get_patient_dir() / f'{patient_id}.txt')}\n".encode("ascii"))
    patient_data = load_development_patients(development)
    target = load_development_target(development)
    columns = get_feature_columns_v2()
    builders = {
        "prevalence_baseline": lambda: DummyClassifier(strategy="prior"),
        "logistic_regression": lambda: build_lr_pipeline(columns),
        "random_forest": lambda: rf_candidate(columns),
        "random_forest_sigmoid": lambda: calibrated_rf_candidate(columns),
    }
    results = []
    coverage = {}
    for checkpoint, cutoff in CUTOFFS.items():
        matrix = build_feature_matrix(development, patient_data, cutoff, version=2)
        audit_matrix(matrix, f"{checkpoint}_scoreable_evaluation")
        X, y = scoreable_development_data(matrix, target.loc[matrix.index], development, separated)
        scoreable_ids = list(X.index)
        coverage[checkpoint] = {
            "development_patients": len(development), "patients_scored": len(X),
            "patients_not_scored": len(development) - len(X),
            "scoreable_cohort_sha256": cohort_fingerprint(scoreable_ids),
            "death_labels_not_scored": int(target.loc[~target.index.isin(scoreable_ids)].sum()),
        }
        for name, builder in builders.items():
            print(f"Evaluating {name} at {checkpoint}: {len(X)} scoreable development patients", flush=True)
            predictions = generate_oof_predictions(
                X, y, builder, n_splits=N_SPLITS, random_state=RANDOM_STATE,
            )
            metrics = summarize_development_predictions(predictions, scoreable_ids, separated)
            results.append({"model": name, "checkpoint": checkpoint, **metrics})
            print(
                f"  ROC-AUC={metrics['pooled_oof_roc_auc']:.4f}, AP={metrics['average_precision']:.4f}, "
                f"Brier={metrics['brier_score']:.4f}, mean score={metrics['mean_model_score']:.4f}",
                flush=True,
            )
            del predictions
    if file_sha256(MANIFEST_PATH) != manifest_hash or any(
        file_sha256(MANIFEST_PATH.parent / ARTIFACT_FILENAMES[name]) != digest
        for name, digest in artifact_hashes.items()
    ):
        raise RuntimeError("Production artifacts unexpectedly changed during evaluation")
    report = {
        "schema_version": 1,
        "status": "EXPLORATORY_DEVELOPMENT_ONLY_NOT_DEPLOYED",
        "target": "In-hospital_death",
        "coverage_policy": COVERAGE_POLICY,
        "clinical_checkpoint_eligibility": "UNKNOWN_FROM_AVAILABLE_FIELDS",
        "outer_cv": {"n_splits": N_SPLITS, "stratified": True, "shuffle": True, "random_state": RANDOM_STATE},
        "calibration": {"method": "sigmoid", "inner_cv_splits": 3, "ensemble": False, "fitted_within_outer_training_only": True},
        "thresholds": {"values": [0.4, 0.5, 0.55], "status": "FIXED_HISTORICAL_REFERENCE_NOT_RETUNED"},
        "development_cohort_sha256": cohort_fingerprint(development),
        "raw_development_patient_files_sha256": raw_digest.hexdigest(),
        "outcomes_sha256": file_sha256(get_outcomes_path()),
        "split_sha256": file_sha256(PROJECT_ROOT / "data" / "processed" / "baseline" / "split_metadata.json"),
        "separated_cohort_sha256": cohort_fingerprint(separated),
        "separated_patients_evaluated": 0,
        "production_manifest_sha256": manifest_hash,
        "production_artifact_sha256": artifact_hashes,
        "source_sha256": {
            name: file_sha256(PROJECT_ROOT / name)
            for name in ("ml/evaluation.py", "ml/coverage.py", "ml/features.py", "ml/preprocessing.py", "ml/threshold_analysis.py", "ml/train_models.py", "scripts/evaluate_scoreable_models.py")
        },
        "coverage": coverage,
        "results": results,
        "limitations": [
            "Known development data were reused; model comparisons and calibration diagnostics are exploratory.",
            "Clinical eligibility at each checkpoint cannot be proved from the available rounded hospital outcomes.",
            "Scoreable means at least one usable temporal measurement, not clinically sufficient information.",
            "Fixed historical score thresholds need separate development tuning for any calibrated model.",
            "No candidate was deployed, and no individual predictions were persisted.",
        ],
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("Evaluation complete. Production models and thresholds are unchanged.", flush=True)


if __name__ == "__main__":
    main()
