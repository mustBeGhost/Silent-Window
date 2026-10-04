"""Research bundle integrity, API model identity, chronology, and cache isolation."""

import json
import shutil

import joblib
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
import backend.routes.models as model_routes
import backend.routes.patients as patient_routes
from backend.services.patient_service import (
    DEFAULT_ARTIFACT_DIR, InferenceConfigurationError, PatientInferenceService,
    get_patient_inference_service,
)
from ml.model_profiles import MODEL_PROFILES
from scripts.train_rf_v2_artifacts import MANIFEST_PATH, file_sha256, validated_training_cohorts, cohort_fingerprint
from tests.test_assessment_availability import patient_frame


client = TestClient(app)
CANDIDATE_DIR = DEFAULT_ARTIFACT_DIR / MODEL_PROFILES["calibrated"]["directory"]
CANDIDATE_MANIFEST = CANDIDATE_DIR / MODEL_PROFILES["calibrated"]["manifest_filename"]


@pytest.fixture(scope="module")
def candidate():
    return get_patient_inference_service("calibrated")


def copied_candidate(tmp_path):
    destination = tmp_path / "candidate"
    shutil.copytree(CANDIDATE_DIR, destination)
    return destination


def test_candidate_manifest_proves_training_cohort_coverage_and_preserved_original():
    manifest = json.loads(CANDIDATE_MANIFEST.read_text())
    dev, separated = validated_training_cohorts()
    assert manifest["development_cohort_sha256"] == cohort_fingerprint(dev)
    assert manifest["separated_cohort_sha256"] == cohort_fingerprint(separated)
    assert manifest["separated_patients_excluded_from_fitting"]
    assert manifest["separated_patients_evaluated"] == 0
    assert manifest["training_coverage"]["6h"]["patients_fitted"] == 2506
    assert manifest["training_coverage"]["12h"]["patients_fitted"] == 2554
    assert manifest["training_coverage"]["24h"]["patients_fitted"] == 2559
    assert manifest["threshold_selection"]["diagnostics_are_training_tuning_not_independent_validation"]
    assert file_sha256(MANIFEST_PATH) == manifest["historical_artifact_sha256"]["manifest"]
    original = json.loads(MANIFEST_PATH.read_text())
    for checkpoint, entry in original["artifacts"].items():
        assert file_sha256(DEFAULT_ARTIFACT_DIR / entry["filename"]) == manifest["historical_artifact_sha256"][checkpoint]
    root = DEFAULT_ARTIFACT_DIR.parents[1]
    for name, digest in manifest["source_sha256"].items():
        assert file_sha256(root / name) == digest


def test_model_options_use_loaded_thresholds_and_expose_no_paths(candidate):
    response = client.get("/api/models")
    assert response.status_code == 200
    options = {entry["id"]: entry for entry in response.json()}
    assert options["original"]["medium_threshold"] == 0.4
    assert options["calibrated"]["medium_threshold"] == candidate.medium_threshold == 0.12
    assert options["calibrated"]["high_threshold"] == candidate.high_threshold == 0.28
    assert all(entry["available"] for entry in options.values())
    assert "\\" not in response.text


def test_services_have_independent_cache_and_index_identity(candidate):
    original = get_patient_inference_service()
    assert original._summary_cache is not candidate._summary_cache
    assert original._detail_cache is not candidate._detail_cache
    assert original.global_index_path != candidate.global_index_path
    assert original._global_index_metadata()["model_profile"] == "original"
    assert candidate._global_index_metadata()["model_profile"] == "calibrated"


def test_api_switches_models_and_can_return_to_original(candidate):
    for profile in ("original", "calibrated", "original"):
        service = get_patient_inference_service(profile)
        response = client.get("/api/patients", params={"model_profile": profile, "page_size": 1})
        assert response.status_code == 200
        assert response.headers["X-Silent-Window-Model"] == profile
        expected = service.get_patient_page(page=1, page_size=1).items[0]
        assert response.json()["items"][0] == expected.model_dump(mode="json")


def test_selected_candidate_health_and_historical_view(candidate):
    health = client.get("/api/health?model_profile=calibrated").json()
    assert health["status"] == "ok"
    assert health["model_family"] == "Calibrated Random Forest V3"
    response = client.get("/api/patients/ICU-1001?model_profile=calibrated&as_of_minutes=480")
    assert response.status_code == 200
    assert response.headers["X-Silent-Window-Model"] == "calibrated"
    points = response.json()["risk_trajectory"]
    assert points[0]["assessment_status"] == "READY"
    assert points[1]["risk_probability"] is None
    assert points[2]["risk_probability"] is None


def test_candidate_missing_measurements_never_reach_the_models(candidate, monkeypatch):
    def fail_if_scored(_):
        raise AssertionError("Missing temporal input was scored")
    for model in candidate.models.values():
        monkeypatch.setattr(model, "predict_proba", fail_if_scored)
    points = candidate.score_preprocessed_patient(1, patient_frame(), ("6h", "12h", "24h"))
    assert all(point.risk_probability is None and point.alert_state is None for point in points)


def test_model_versions_apply_their_own_boundaries(candidate, monkeypatch):
    original = get_patient_inference_service()
    for service in (original, candidate):
        for model in service.models.values():
            monkeypatch.setattr(model, "predict_proba", lambda X: np.tile([0.8, 0.2], (len(X), 1)))
    patient = patient_frame([(60, "HR", 80)])
    raw = original.score_preprocessed_patient(1, patient, ("6h", "12h", "24h"))
    adjusted = candidate.score_preprocessed_patient(1, patient, ("6h", "12h", "24h"))
    assert [point.risk_level for point in raw] == ["LOW"] * 3
    assert [point.risk_level for point in adjusted] == ["MEDIUM"] * 3
    assert [point.alert_state for point in adjusted] == ["WATCH", "HIGH_ALERT", "HIGH_ALERT"]


def test_candidate_score_is_unchanged_by_future_measurements(candidate):
    record_id = candidate._opaque_to_record["ICU-1001"]
    patient, _ = candidate._load_patient_context(record_id)
    changed = patient.copy()
    future = changed["Time_minutes"] > 360
    assert future.any()
    changed.loc[future, "Value"] = changed.loc[future, "Value"] * 100
    before = candidate.score_preprocessed_patient(record_id, patient, ("6h",), available_through_minutes=360)[0]
    after = candidate.score_preprocessed_patient(record_id, changed, ("6h",), available_through_minutes=360)[0]
    assert before == after


@pytest.mark.parametrize("path", ["/api/health", "/api/patients", "/api/patients/ICU-1001", "/api/patients/global-index/status"])
def test_unknown_model_profile_is_rejected(path):
    assert client.get(path, params={"model_profile": "wrong"}).status_code == 422


def test_candidate_failure_does_not_fall_back_to_original(monkeypatch):
    original_get = get_patient_inference_service
    def missing(profile="original"):
        if profile == "calibrated":
            raise InferenceConfigurationError("private local path")
        return original_get()
    monkeypatch.setattr(patient_routes, "get_patient_inference_service", missing)
    for method, path in (("get", "/api/patients"), ("get", "/api/patients/ICU-1001"),
                         ("get", "/api/patients/global-index/status"), ("post", "/api/patients/global-index/prepare")):
        response = getattr(client, method)(path, params={"model_profile": "calibrated"})
        assert response.status_code == 503
        assert "private local path" not in response.text
    assert client.get("/api/patients?page_size=1").status_code == 200


def test_unavailable_candidate_is_disabled_in_metadata(monkeypatch):
    def missing(profile):
        if profile == "calibrated":
            raise InferenceConfigurationError("private local path")
        return get_patient_inference_service()
    monkeypatch.setattr(model_routes, "get_patient_inference_service", missing)
    options = {entry["id"]: entry for entry in client.get("/api/models").json()}
    assert options["original"]["available"]
    assert not options["calibrated"]["available"]
    assert options["calibrated"]["medium_threshold"] is None


def test_corrupt_candidate_is_rejected_before_deserialization(tmp_path, monkeypatch):
    directory = copied_candidate(tmp_path)
    (directory / "rf_v3_6h.joblib").write_bytes(b"corrupt model")
    def should_not_load(_):
        raise AssertionError("Corrupt artifact was deserialized")
    monkeypatch.setattr(joblib, "load", should_not_load)
    with pytest.raises(InferenceConfigurationError, match="integrity mismatch"):
        PatientInferenceService(artifact_dir=directory, model_profile="calibrated")


def test_disagreeing_numeric_and_text_thresholds_are_rejected(tmp_path):
    directory = copied_candidate(tmp_path)
    manifest_path = directory / MODEL_PROFILES["calibrated"]["manifest_filename"]
    manifest = json.loads(manifest_path.read_text())
    manifest["thresholds"]["medium"] = 0.4
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(InferenceConfigurationError, match="thresholds disagree"):
        PatientInferenceService(artifact_dir=directory, model_profile="calibrated")


def test_raw_model_cannot_be_mislabelled_as_a_calibrated_candidate(tmp_path):
    directory = copied_candidate(tmp_path)
    artifact_path = directory / "rf_v3_6h.joblib"
    # Copy the saved file: earlier API checks may temporarily replace methods
    # on the process-wide live model, which should never become test artifacts.
    shutil.copyfile(DEFAULT_ARTIFACT_DIR / MODEL_PROFILES["original"]["filenames"]["6h"], artifact_path)
    manifest_path = directory / MODEL_PROFILES["calibrated"]["manifest_filename"]
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"]["6h"]["sha256"] = file_sha256(artifact_path)
    manifest["artifacts"]["6h"]["size_bytes"] = artifact_path.stat().st_size
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(InferenceConfigurationError, match="sigmoid research calibrator"):
        PatientInferenceService(artifact_dir=directory, model_profile="calibrated")


def test_original_index_is_not_loaded_for_candidate(tmp_path):
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps({"metadata": get_patient_inference_service()._global_index_metadata(), "patients": []}))
    service = PatientInferenceService(model_profile="calibrated", global_index_path=index_path)
    assert service.get_global_index_status().state == "not_started"
