"""Generate the aggregate data used by the Model Performance page.

This development-time command reproduces RF V2 out-of-fold probabilities for
the frozen 2,560-patient development cohort using the original stratified
5-fold method. The separated 640-patient cohort is used only as an exclusion
set for integrity validation and is never scored or evaluated.

Only aggregate ROC coordinates/AUC values and global 12-hour feature
importances are written. Patient IDs, labels, probabilities, observations,
and outcomes are never persisted in the visualization artifact.

Run from the project root::

    python -m scripts.generate_model_performance_data
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from ml.features import build_feature_matrix, get_feature_columns_v2
from ml.model_performance import (
    build_roc_summary,
    extract_global_feature_importance,
)
from ml.threshold_analysis import generate_oof_predictions
from ml.train_models import (
    CUTOFFS,
    FEATURE_VERSION,
    N_SPLITS,
    RANDOM_STATE,
    audit_matrix,
    build_rf_pipeline,
)
from scripts.train_rf_v2_artifacts import (
    ARTIFACT_FILENAMES,
    MANIFEST_PATH,
    cohort_fingerprint,
    file_sha256,
    load_development_patients,
    load_development_target,
    validated_training_cohorts,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = (
    PROJECT_ROOT / "frontend" / "src" / "data"
    / "modelPerformance.json"
)

EXPECTED_FOLD_MEAN_AUC = {
    "6h": 0.7256,
    "12h": 0.7494,
    "24h": 0.7806,
}


def main() -> None:
    """Reproduce development OOF ROC data and write one safe JSON artifact."""
    print("Silent Window -- Generate Model Performance Visualization Data")
    print("=" * 68)
    development_ids, separated_ids = validated_training_cohorts()
    print(f"Development cohort: {len(development_ids)}")
    print(f"Separated cohort excluded from evaluation: {len(separated_ids)}")

    patient_data = load_development_patients(development_ids)
    target = load_development_target(development_ids)
    feature_columns = get_feature_columns_v2()

    curves = []
    for checkpoint, cutoff_minutes in CUTOFFS.items():
        print(f"Generating RF V2 OOF ROC data at {checkpoint}...")
        matrix = build_feature_matrix(
            development_ids,
            patient_data,
            cutoff_minutes,
            version=FEATURE_VERSION,
        )
        audit_matrix(matrix, f"{checkpoint}_model_performance")
        if list(matrix.index) != list(development_ids):
            raise RuntimeError("Feature matrix is not the frozen development cohort")
        if list(matrix.columns) != feature_columns:
            raise RuntimeError("Feature matrix does not match the V2 schema")

        predictions = generate_oof_predictions(
            matrix,
            target.loc[matrix.index],
            lambda: build_rf_pipeline(feature_columns),
            n_splits=N_SPLITS,
            random_state=RANDOM_STATE,
        )
        curve = build_roc_summary(
            predictions,
            development_ids,
            separated_ids,
            checkpoint=checkpoint,
            primary=checkpoint == "12h",
        )
        expected = EXPECTED_FOLD_MEAN_AUC[checkpoint]
        if round(curve["fold_mean_roc_auc"], 4) != expected:
            raise RuntimeError(
                f"{checkpoint} fold-mean ROC-AUC differs from the verified "
                f"value: {curve['fold_mean_roc_auc']:.8f} vs {expected:.4f}"
            )
        curves.append(curve)
        print(
            f"  pooled OOF ROC-AUC={curve['roc_auc']:.8f}; "
            f"fold mean={curve['fold_mean_roc_auc']:.8f}"
        )
        del predictions, matrix

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    primary_artifact_path = (
        MANIFEST_PATH.parent / ARTIFACT_FILENAMES["12h"]
    )
    feature_importance = extract_global_feature_importance(
        primary_artifact_path,
        feature_columns,
        top_n=10,
    )
    feature_importance["source_model_sha256"] = file_sha256(
        primary_artifact_path
    )
    if feature_importance["source_model_sha256"] != (
        manifest["artifacts"]["12h"]["sha256"]
    ):
        raise RuntimeError("12h artifact hash does not match its manifest")

    payload = {
        "metadata": {
            "model_family": "Random Forest V2",
            "primary_checkpoint": "12h",
            "validation_method": "Development 5-fold cross-validation",
            "development_cohort_size": len(development_ids),
            "development_cohort_sha256": cohort_fingerprint(development_ids),
            "n_splits": N_SPLITS,
            "random_state": RANDOM_STATE,
            "feature_version": "V2",
        },
        "roc_curves": curves,
        "feature_importance": feature_importance,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = OUTPUT_PATH.with_name(
        f".{OUTPUT_PATH.name}.{uuid4().hex}.tmp"
    )
    try:
        temporary_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, OUTPUT_PATH)
    finally:
        temporary_path.unlink(missing_ok=True)

    print(f"Saved aggregate visualization data: {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
    print("No patient-level prediction data was persisted.")
    print("Separated 640 patients: NOT EVALUATED")


if __name__ == "__main__":
    main()
