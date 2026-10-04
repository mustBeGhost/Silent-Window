"""Regression checks for missing assessments and recorded-time views."""

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.main import app
from backend.schemas.patient import RiskTrajectoryPoint
from backend.services.patient_service import (
    EXPECTED_CUTOFFS, PatientInferenceError, PatientInferenceService,
)
from ml.alert_policy import probabilities_to_alert_timeline
from ml.features import build_feature_matrix


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    return PatientInferenceService(
        global_index_path=tmp_path_factory.mktemp("availability") / "index.json",
    )


def patient_frame(extra=()):
    rows = [(0, "Age", 55), (0, "Gender", 1), (0, "Weight", 70), (0, "ICUType", 3)]
    return pd.DataFrame(rows + list(extra), columns=["Time_minutes", "Parameter", "Value"])


@pytest.mark.parametrize("extra", [(), [(60, "HR", np.nan)], [(60, "Urine", 100)]])
def test_no_usable_supported_measurements_never_calls_models(service, monkeypatch, extra):
    def unexpected_inference(_matrix):
        raise AssertionError("Static-only/missing/unsupported measurements must not be scored")

    for model in service.models.values():
        monkeypatch.setattr(model, "predict_proba", unexpected_inference)
    points = service.score_preprocessed_patient(1, patient_frame(extra), tuple(EXPECTED_CUTOFFS))
    for point in points:
        assert point.assessment_status == "INSUFFICIENT_DATA"
        assert point.temporal_observation_count == 0
        assert point.risk_probability is None
        assert point.risk_level is None
        assert point.alert_state is None


def test_later_measurements_do_not_rescue_an_earlier_checkpoint(service):
    points = service.score_preprocessed_patient(
        1, patient_frame([(600, "HR", 80)]), tuple(EXPECTED_CUTOFFS),
    )
    assert points[0].assessment_status == "INSUFFICIENT_DATA"
    assert points[1].assessment_status == "READY"
    assert points[1].temporal_observation_count == 1
    assert points[1].alert_state != "HIGH_ALERT"
    assert points[2].assessment_status == "READY"


def test_missing_assessment_breaks_alert_persistence():
    timeline = probabilities_to_alert_timeline([0.7, None, 0.7], 0.4, 0.55)
    assert [point["alert_state"] for point in timeline] == ["WATCH", None, "WATCH"]


def test_eligible_scores_match_saved_models(service):
    record_id = service._opaque_to_record["ICU-1001"]
    patient, _ = service._load_patient_context(record_id)
    points = service.score_preprocessed_patient(record_id, patient, tuple(EXPECTED_CUTOFFS))
    for checkpoint, point in zip(EXPECTED_CUTOFFS, points, strict=True):
        matrix = build_feature_matrix([record_id], {record_id: patient}, EXPECTED_CUTOFFS[checkpoint], version=2)
        expected = service.models[checkpoint].predict_proba(matrix)[0, service.positive_class_indices[checkpoint]]
        assert point.assessment_status == "READY"
        assert point.risk_probability == pytest.approx(expected, abs=1e-15)


def test_batch_and_single_missing_assessments_match(service, monkeypatch):
    patient = patient_frame()
    monkeypatch.setattr(service, "_load_patient_context", lambda _rid: (patient, "MICU"))
    batch = service._compute_summaries(["ICU-1001"])["ICU-1001"]
    single = service._compute_summary("ICU-1001", service._opaque_to_record["ICU-1001"])
    assert batch == single
    assert batch.assessment_status == "INSUFFICIENT_DATA"
    assert batch.risk_trend is None


@pytest.mark.parametrize("as_of,expected", [
    (0, ["NOT_YET_AVAILABLE"] * 3),
    (359, ["NOT_YET_AVAILABLE"] * 3),
    (360, ["READY", "NOT_YET_AVAILABLE", "NOT_YET_AVAILABLE"]),
    (480, ["READY", "NOT_YET_AVAILABLE", "NOT_YET_AVAILABLE"]),
    (720, ["READY", "READY", "NOT_YET_AVAILABLE"]),
    (1440, ["READY"] * 3),
])
def test_selected_time_controls_checkpoints_and_vitals(service, as_of, expected):
    # Warm the full-record cache before requesting an earlier view.
    full = service.get_patient_detail("ICU-1001")
    detail = service.get_patient_detail("ICU-1001", as_of_minutes=as_of)
    assert detail.available_through_minutes == as_of
    assert [point.assessment_status for point in detail.risk_trajectory] == expected
    assert all(
        measurement.time_minutes <= as_of
        for series in detail.vital_histories for measurement in series.measurements
    )
    if as_of >= 360:
        assert detail.risk_trajectory[0].risk_probability == full.risk_trajectory[0].risk_probability
    assert service.get_patient_detail("ICU-1001") == full


def test_future_models_are_not_called(service, monkeypatch):
    def unexpected_inference(_matrix):
        raise AssertionError("Future model called")

    for checkpoint in ("12h", "24h"):
        monkeypatch.setattr(service.models[checkpoint], "predict_proba", unexpected_inference)
    detail = service.get_patient_detail("ICU-1001", as_of_minutes=480)
    assert detail.risk_trajectory[0].assessment_status == "READY"
    assert detail.risk_probability is None
    assert detail.alert_state is None


@pytest.mark.parametrize("as_of", [-1, 1441, "bad"])
def test_invalid_view_time_returns_422(as_of):
    response = TestClient(app).get("/api/patients/ICU-1001", params={"as_of_minutes": as_of})
    assert response.status_code == 422


def test_api_eight_hour_view_excludes_future_results():
    response = TestClient(app).get("/api/patients/ICU-1001?as_of_minutes=480")
    assert response.status_code == 200
    payload = response.json()
    assert payload["assessment_status"] == "NOT_YET_AVAILABLE"
    assert payload["risk_probability"] is None
    assert payload["risk_trajectory"][0]["assessment_status"] == "READY"
    assert payload["risk_trajectory"][2]["risk_probability"] is None


@pytest.mark.parametrize("record_id", [140501, 141264])
def test_real_static_only_patients_return_no_score(service, record_id):
    public_id = service._record_to_opaque[record_id]
    summary = service.get_patient_summary(public_id)
    detail = service.get_patient_detail(public_id)
    assert summary.assessment_status == detail.assessment_status == "INSUFFICIENT_DATA"
    assert summary.risk_probability is detail.risk_probability is None
    assert all(point.alert_state is None for point in detail.risk_trajectory)


def test_unavailable_patients_are_not_counted_as_no_alert(service):
    index = {"ICU-1001": service.get_patient_summary("ICU-1001")}
    public_id = service._record_to_opaque[141264]
    index[public_id] = service.get_patient_summary(public_id)
    previous_index, previous_state = service._global_index, service._global_index_state
    service._global_index, service._global_index_state = index, "ready"
    try:
        page = service.get_patient_page(page=1, page_size=25, scope="all")
        assert page.assessment_counts.not_assessed == 1
        assert page.assessment_counts.no_alert == 1
    finally:
        service._global_index, service._global_index_state = previous_index, previous_state


def test_unavailable_schema_rejects_fake_low_score():
    with pytest.raises(ValidationError, match="cannot contain a score"):
        RiskTrajectoryPoint(
            checkpoint="6h", assessment_status="INSUFFICIENT_DATA",
            assessment_reason="Missing measurements", temporal_observation_count=0,
            risk_probability=0.0, risk_level="LOW", alert_state="NO_ALERT",
        )


def test_infinite_measurement_is_rejected(service):
    with pytest.raises(PatientInferenceError, match="Non-finite"):
        service.score_preprocessed_patient(1, patient_frame([(60, "HR", np.inf)]), ("6h",))
