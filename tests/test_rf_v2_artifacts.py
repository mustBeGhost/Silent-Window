"""Integrity and chronology checks for deployable RF V2 artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from ml.data_loader import load_patient
from ml.features import build_feature_matrix, get_feature_columns_v2
from ml.preprocessing import observations_up_to, preprocess_patient
from ml.train_models import CUTOFFS, get_development_ids
from scripts.train_rf_v2_artifacts import (
    ARTIFACT_FILENAMES,
    EXPECTED_DEVELOPMENT_SIZE,
    EXPECTED_SEPARATED_SIZE,
    RF_HYPERPARAMETERS,
    cohort_fingerprint,
    file_sha256,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = PROJECT_ROOT / "ml" / "artifacts"
MANIFEST_PATH = ARTIFACT_DIR / "rf_v2_manifest.json"


@pytest.fixture(scope="module")
def manifest() -> dict[str, object]:
    assert MANIFEST_PATH.is_file()
    with MANIFEST_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def loaded_artifacts(manifest):
    return {
        cutoff_label: joblib.load(
            ARTIFACT_DIR / artifact_info["filename"]
        )
        for cutoff_label, artifact_info in manifest["artifacts"].items()
    }


@pytest.fixture(scope="module")
def development_patient_with_future_observations():
    development_ids, separated_ids = get_development_ids()
    assert set(development_ids).isdisjoint(separated_ids)

    for patient_id in development_ids:
        raw = load_patient(patient_id)
        if raw["Time_minutes"].max() > CUTOFFS["24h"]:
            return patient_id, preprocess_patient(raw)
    raise AssertionError(
        "No development patient has observations after the 24h cutoff"
    )


@pytest.mark.parametrize("cutoff_label", tuple(CUTOFFS))
def test_artifact_files_exist_and_match_manifest(manifest, cutoff_label):
    artifact_info = manifest["artifacts"][cutoff_label]
    artifact_path = ARTIFACT_DIR / artifact_info["filename"]

    assert artifact_path.is_file()
    assert artifact_path.stat().st_size == artifact_info["size_bytes"]
    assert file_sha256(artifact_path) == artifact_info["sha256"]


def test_manifest_matches_selected_artifact_filenames(manifest):
    filenames = {
        cutoff_label: artifact_info["filename"]
        for cutoff_label, artifact_info in manifest["artifacts"].items()
    }
    assert filenames == ARTIFACT_FILENAMES


def test_manifest_records_v2_schema_and_configuration(manifest):
    expected_columns = get_feature_columns_v2()

    assert manifest["model_type"] == "RandomForestClassifier"
    assert manifest["feature_version"] == "V2"
    assert manifest["feature_count"] == 132
    assert manifest["ordered_input_features"] == expected_columns
    assert manifest["supported_cutoffs"] == CUTOFFS
    assert manifest["primary_cutoff"] == "12h"
    assert manifest["rf_hyperparameters"] == RF_HYPERPARAMETERS
    assert manifest["risk_boundaries"] == {
        "LOW": "probability < 0.40",
        "MEDIUM": "0.40 <= probability < 0.55",
        "HIGH": "probability >= 0.55",
    }


@pytest.mark.parametrize("cutoff_label", tuple(CUTOFFS))
def test_loaded_artifact_accepts_exact_v2_schema(
    loaded_artifacts,
    cutoff_label,
):
    model = loaded_artifacts[cutoff_label]
    expected_columns = get_feature_columns_v2()
    classifier = model.named_steps["classifier"]

    assert callable(model.predict_proba)
    assert model.n_features_in_ == 132
    assert list(model.feature_names_in_) == expected_columns
    for parameter, expected in RF_HYPERPARAMETERS.items():
        assert classifier.get_params(deep=False)[parameter] == expected


def test_manifest_proves_separated_cohort_excluded(manifest):
    development_ids, separated_ids = get_development_ids()

    assert len(development_ids) == EXPECTED_DEVELOPMENT_SIZE
    assert len(separated_ids) == EXPECTED_SEPARATED_SIZE
    assert set(development_ids).isdisjoint(separated_ids)
    assert manifest["development_cohort_size"] == len(development_ids)
    assert manifest["development_cohort_sha256"] == cohort_fingerprint(
        development_ids
    )
    assert manifest["separated_cohort_size"] == len(separated_ids)
    assert manifest["separated_cohort_sha256"] == cohort_fingerprint(
        separated_ids
    )
    assert manifest["separated_patients_excluded_from_fitting"] is True


@pytest.mark.parametrize(
    ("cutoff_label", "cutoff_minutes"),
    tuple(CUTOFFS.items()),
)
def test_prediction_is_invariant_to_future_observations(
    loaded_artifacts,
    development_patient_with_future_observations,
    cutoff_label,
    cutoff_minutes,
):
    patient_id, prepared = development_patient_with_future_observations
    visible = observations_up_to(prepared, cutoff_minutes)
    assert (prepared["Time_minutes"] > cutoff_minutes).any()
    assert visible["Time_minutes"].max() <= cutoff_minutes

    from_complete_file = build_feature_matrix(
        [patient_id],
        {patient_id: prepared},
        cutoff_minutes,
        version=2,
    )
    from_truncated_file = build_feature_matrix(
        [patient_id],
        {patient_id: visible},
        cutoff_minutes,
        version=2,
    )
    pd.testing.assert_frame_equal(from_complete_file, from_truncated_file)
    assert list(from_complete_file.columns) == get_feature_columns_v2()

    model = loaded_artifacts[cutoff_label]
    complete_probability = model.predict_proba(from_complete_file)[0, 1]
    truncated_probability = model.predict_proba(from_truncated_file)[0, 1]

    assert np.isfinite(complete_probability)
    assert 0.0 <= complete_probability <= 1.0
    assert complete_probability == pytest.approx(
        truncated_probability,
        rel=0.0,
        abs=1e-15,
    )
