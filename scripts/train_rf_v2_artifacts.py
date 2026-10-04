"""Fit deployable RF V2 pipelines on the frozen development cohort.

This command performs no model selection or performance evaluation.  It uses
the same 2,560-patient development population, V2 feature construction, and
Random Forest configuration as the validated cross-validation work.

Run from the project root::

    python -m scripts.train_rf_v2_artifacts
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

import joblib
import pandas as pd

from ml.data_loader import discover_patient_ids, load_outcomes, load_patient
from ml.features import build_feature_matrix, get_feature_columns_v2
from ml.preprocessing import preprocess_patient
from ml.train_models import (
    CUTOFFS,
    FEATURE_VERSION,
    RANDOM_STATE,
    audit_matrix,
    build_rf_pipeline,
    get_development_ids,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = PROJECT_ROOT / "ml" / "artifacts"
MANIFEST_PATH = ARTIFACT_DIR / "rf_v2_manifest.json"

EXPECTED_DEVELOPMENT_SIZE = 2_560
EXPECTED_SEPARATED_SIZE = 640
PRIMARY_CUTOFF = "12h"

ARTIFACT_FILENAMES = {
    "6h": "rf_v2_6h.joblib",
    "12h": "rf_v2_12h.joblib",
    "24h": "rf_v2_24h.joblib",
}

RF_HYPERPARAMETERS = {
    "n_estimators": 200,
    "max_depth": 12,
    "min_samples_leaf": 10,
    "class_weight": "balanced",
    "random_state": RANDOM_STATE,
    "n_jobs": -1,
}

RISK_BOUNDARIES = {
    "LOW": "probability < 0.40",
    "MEDIUM": "0.40 <= probability < 0.55",
    "HIGH": "probability >= 0.55",
}


def cohort_fingerprint(patient_ids: Sequence[int]) -> str:
    """Return a stable SHA-256 fingerprint without persisting patient IDs."""
    canonical = ",".join(str(int(value)) for value in sorted(patient_ids))
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of one artifact file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validated_training_cohorts() -> tuple[list[int], list[int]]:
    """Return the frozen development/separated cohorts after strict checks."""
    development_ids, separated_ids = get_development_ids()
    development_set = set(development_ids)
    separated_set = set(separated_ids)
    all_ids = set(discover_patient_ids())

    if len(development_ids) != EXPECTED_DEVELOPMENT_SIZE:
        raise RuntimeError(
            f"Expected {EXPECTED_DEVELOPMENT_SIZE} development patients, "
            f"found {len(development_ids)}"
        )
    if len(separated_ids) != EXPECTED_SEPARATED_SIZE:
        raise RuntimeError(
            f"Expected {EXPECTED_SEPARATED_SIZE} separated patients, "
            f"found {len(separated_ids)}"
        )
    if len(development_set) != len(development_ids):
        raise RuntimeError("Development patient IDs are not unique")
    if len(separated_set) != len(separated_ids):
        raise RuntimeError("Separated patient IDs are not unique")
    if development_set & separated_set:
        raise RuntimeError("Development and separated patient IDs overlap")
    if development_set | separated_set != all_ids:
        raise RuntimeError("Frozen cohorts do not partition the patient files")

    return development_ids, separated_ids


def load_development_patients(
    development_ids: Sequence[int],
) -> dict[int, pd.DataFrame]:
    """Load only development-cohort patient observations."""
    patient_data: dict[int, pd.DataFrame] = {}
    for position, patient_id in enumerate(development_ids, start=1):
        patient_data[int(patient_id)] = preprocess_patient(
            load_patient(int(patient_id))
        )
        if position % 500 == 0:
            print(
                f"  Loaded {position}/{len(development_ids)} "
                "development patients"
            )
    return patient_data


def load_development_target(development_ids: Sequence[int]) -> pd.Series:
    """Return labels ordered to the development cohort and no other rows."""
    outcomes = load_outcomes().set_index("RecordID")
    missing = set(development_ids) - set(outcomes.index)
    if missing:
        raise RuntimeError(
            f"Outcomes missing {len(missing)} development patient IDs"
        )
    target = outcomes.loc[list(development_ids), "In-hospital_death"].copy()
    target.index = [int(value) for value in target.index]
    target.name = "target"
    if not target.index.is_unique:
        raise RuntimeError("Development target index is not unique")
    if set(target.unique()) - {0, 1}:
        raise RuntimeError("Development target must contain only 0 and 1")
    return target


def build_manifest(
    development_ids: Sequence[int],
    separated_ids: Sequence[int],
    feature_columns: list[str],
) -> dict[str, object]:
    """Build the small tracked runtime-artifact manifest."""
    artifacts: dict[str, dict[str, object]] = {}
    for cutoff_label, filename in ARTIFACT_FILENAMES.items():
        artifact_path = ARTIFACT_DIR / filename
        artifacts[cutoff_label] = {
            "filename": filename,
            "cutoff_minutes": CUTOFFS[cutoff_label],
            "size_bytes": artifact_path.stat().st_size,
            "sha256": file_sha256(artifact_path),
        }

    return {
        "model_type": "RandomForestClassifier",
        "feature_version": "V2",
        "feature_count": len(feature_columns),
        "ordered_input_features": feature_columns,
        "supported_cutoffs": CUTOFFS,
        "primary_cutoff": PRIMARY_CUTOFF,
        "rf_hyperparameters": RF_HYPERPARAMETERS,
        "development_cohort_size": len(development_ids),
        "development_cohort_sha256": cohort_fingerprint(development_ids),
        "separated_cohort_size": len(separated_ids),
        "separated_cohort_sha256": cohort_fingerprint(separated_ids),
        "separated_patients_excluded_from_fitting": True,
        "risk_boundaries": RISK_BOUNDARIES,
        "artifacts": artifacts,
    }


def main() -> None:
    """Fit and persist the three selected deployment pipelines."""
    print("Silent Window -- Train Deployable RF V2 Artifacts")
    print("=" * 56)

    development_ids, separated_ids = validated_training_cohorts()
    print(f"Development cohort: {len(development_ids)}")
    print(f"Separated cohort excluded from fitting: {len(separated_ids)}")

    print("Loading development observations only...")
    patient_data = load_development_patients(development_ids)
    target = load_development_target(development_ids)
    feature_columns = get_feature_columns_v2()
    if len(feature_columns) != 132:
        raise RuntimeError(
            f"Expected 132 V2 features, found {len(feature_columns)}"
        )

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for cutoff_label, cutoff_minutes in CUTOFFS.items():
        print(
            f"Building V2 development matrix at {cutoff_label} "
            f"({cutoff_minutes} minutes)..."
        )
        matrix = build_feature_matrix(
            development_ids,
            patient_data,
            cutoff_minutes,
            version=FEATURE_VERSION,
        )
        audit_matrix(matrix, f"{cutoff_label}_deployment")
        if list(matrix.columns) != feature_columns:
            raise RuntimeError(
                f"{cutoff_label} feature order does not match V2 schema"
            )
        if list(matrix.index) != list(development_ids):
            raise RuntimeError(
                f"{cutoff_label} matrix does not contain the exact "
                "development cohort in order"
            )

        pipeline = build_rf_pipeline(feature_columns)
        classifier_params = pipeline.named_steps["classifier"].get_params(
            deep=False
        )
        for name, expected in RF_HYPERPARAMETERS.items():
            if classifier_params[name] != expected:
                raise RuntimeError(
                    f"RF parameter {name}={classifier_params[name]!r}; "
                    f"expected {expected!r}"
                )

        print(f"Fitting RF V2 at {cutoff_label} on {len(matrix)} patients...")
        pipeline.fit(matrix, target.loc[matrix.index])
        artifact_path = ARTIFACT_DIR / ARTIFACT_FILENAMES[cutoff_label]
        joblib.dump(pipeline, artifact_path, compress=3)
        print(f"Saved {artifact_path.name} ({artifact_path.stat().st_size} bytes)")

    manifest = build_manifest(
        development_ids,
        separated_ids,
        feature_columns,
    )
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Saved {MANIFEST_PATH.name}")
    print("No performance evaluation was performed.")


if __name__ == "__main__":
    main()
