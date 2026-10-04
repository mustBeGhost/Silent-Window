"""The five-checkpoint research bundle must remain separate and prefix safe."""
import json
import shutil

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.patient_service import PatientInferenceService, InferenceConfigurationError, get_patient_inference_service
from ml.checkpoint_expansion import CUTOFFS
from scripts.train_rf_v2_artifacts import file_sha256
from tests.test_assessment_availability import patient_frame

client = TestClient(app)


@pytest.fixture(scope="module")
def expanded():
    return get_patient_inference_service("expanded")


@pytest.mark.parametrize("minute,ready_count", [(0, 0), (359, 0), (360, 1), (539, 1), (540, 2),
                                              (719, 2), (720, 3), (1079, 3), (1080, 4), (1440, 5)])
def test_expanded_api_hides_future_and_keeps_primary_at_12h(expanded, minute, ready_count):
    response = client.get(f"/api/patients/ICU-1001?model_profile=expanded&as_of_minutes={minute}")
    assert response.status_code == 200
    assert response.headers["X-Silent-Window-Model"] == "expanded"
    body = response.json()
    assert [point["checkpoint"] for point in body["risk_trajectory"]] == list(CUTOFFS)
    assert [point["assessment_status"] for point in body["risk_trajectory"]] == ["READY"] * ready_count + ["NOT_YET_AVAILABLE"] * (5 - ready_count)
    assert body["risk_probability"] == body["risk_trajectory"][2]["risk_probability"]
    assert body["alert_state"] == body["risk_trajectory"][2]["alert_state"]
    assert all(obs["time_minutes"] <= minute for series in body["vital_histories"] for obs in series["measurements"])


def test_12h_persistence_uses_9h_and_queue_matches_detail(expanded, monkeypatch):
    scores = {"6h": 0.5, "9h": 0.01, "12h": 0.5, "18h": 0.5, "24h": 0.5}
    for cp, model in expanded.models.items():
        monkeypatch.setattr(model, "predict_proba", lambda X, p=scores[cp]: np.tile([1 - p, p], (len(X), 1)))
    patient = patient_frame([(60, "HR", 80)])
    monkeypatch.setattr(expanded, "_load_patient_context", lambda _rid: (patient, "MICU"))
    points = expanded.score_preprocessed_patient(1, patient, tuple(CUTOFFS))
    assert [point.alert_state for point in points] == ["WATCH", "NO_ALERT", "WATCH", "HIGH_ALERT", "HIGH_ALERT"]
    detail = expanded._compute_detail("ICU-1001", 1)
    single = expanded._compute_summary("ICU-1001", 1)
    batch = expanded._compute_summaries(["ICU-1001"])["ICU-1001"]
    assert single == batch
    assert detail.alert_state == single.alert_state == "WATCH"


def test_missing_and_future_measurements_never_call_new_models(expanded, monkeypatch):
    def fail(_):
        raise AssertionError("Unavailable data reached a model")
    for model in expanded.models.values():
        monkeypatch.setattr(model, "predict_proba", fail)
    points = expanded.score_preprocessed_patient(1, patient_frame(), tuple(CUTOFFS))
    assert all(point.assessment_status == "INSUFFICIENT_DATA" and point.risk_probability is None for point in points)
    future = expanded.score_preprocessed_patient(1, patient_frame([(600, "HR", 80)]), tuple(CUTOFFS), available_through_minutes=540)
    assert [point.assessment_status for point in future] == ["INSUFFICIENT_DATA"] * 2 + ["NOT_YET_AVAILABLE"] * 3


def test_new_9h_score_is_unchanged_by_later_observations(expanded):
    rid = expanded._opaque_to_record["ICU-1001"]
    patient, _ = expanded._load_patient_context(rid)
    changed = patient.copy()
    changed.loc[changed.Time_minutes > 540, "Value"] *= 100
    before = expanded.score_preprocessed_patient(rid, patient, ("6h", "9h"), available_through_minutes=540)
    after = expanded.score_preprocessed_patient(rid, changed, ("6h", "9h"), available_through_minutes=540)
    assert before == after


def test_expanded_integrity_metadata_and_separate_caches(expanded):
    manifest = expanded.manifest
    assert expanded.medium_threshold == 0.08 and expanded.high_threshold == 0.28
    assert manifest["separated_patients_excluded_from_fitting"]
    assert manifest["separated_patients_evaluated"] == 0
    assert manifest["training_populations"]["9h"]["assessed_patients"] == 2541
    assert manifest["training_populations"]["18h"]["assessed_patients"] == 2557
    root = expanded.artifact_dir.parents[2]
    for group in ("source_sha256", "protected_file_sha256", "evaluation_evidence_sha256"):
        for name, digest in manifest[group].items():
            assert file_sha256(root / name) == digest, name
    assert expanded._global_index_metadata()["supported_cutoffs"] == CUTOFFS
    for old in (get_patient_inference_service(), get_patient_inference_service("calibrated")):
        assert old.global_index_path != expanded.global_index_path
        assert old._detail_cache is not expanded._detail_cache
        assert list(old.cutoffs) == ["6h", "12h", "24h"]
    health = client.get("/api/health?model_profile=expanded").json()
    assert health["status"] == "ok" and health["supported_checkpoints"] == list(CUTOFFS)


def test_corrupt_checkpoint_bundle_is_rejected_before_loading(expanded, tmp_path):
    shutil.copytree(expanded.artifact_dir, tmp_path / "bundle")
    path = tmp_path / "bundle" / expanded.artifact_filenames["9h"]
    path.write_bytes(b"invalid")
    with pytest.raises(InferenceConfigurationError, match="integrity mismatch"):
        PatientInferenceService(artifact_dir=path.parent, global_index_path=tmp_path / "index.json", model_profile="expanded")
