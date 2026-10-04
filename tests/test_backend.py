"""API and safety tests for Silent Window RF V2 full-cohort inference."""

from __future__ import annotations

import json
import re

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.routes.patients as patient_routes_module
import backend.routes.health as health_routes_module
import backend.services.patient_service as patient_service_module
from backend.main import app
from backend.services.patient_service import (
    EXPECTED_CUTOFFS,
    InferenceConfigurationError,
    PRESERVED_PUBLIC_ID_RECORDS,
    PatientInferenceError,
    PatientInferenceService,
    VITAL_PARAMETERS,
    build_patient_id_mapping,
    get_patient_inference_service,
)
from ml.alert_policy import probabilities_to_alert_timeline
from ml.data_loader import discover_patient_ids, load_patient
from ml.features import LEAKAGE_COLUMNS, get_feature_columns_v2
from ml.preprocessing import observations_up_to, preprocess_patient


client = TestClient(app)
FORBIDDEN_RESPONSE_FIELDS = {
    "recordid",
    "record_id",
    "in-hospital_death",
    "in_hospital_death",
    "survival",
    "length_of_stay",
    "saps-i",
    "saps_i",
    "sofa",
}


def _all_keys(value) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        for child in value.values():
            keys.update(_all_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(_all_keys(child))
        return keys
    return set()


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def service() -> PatientInferenceService:
    return get_patient_inference_service()


@pytest.fixture(scope="module")
def id_mapping() -> dict[str, int]:
    mapping, _ = build_patient_id_mapping()
    return mapping


@pytest.fixture(scope="module")
def default_page() -> dict:
    response = client.get("/api/patients")
    assert response.status_code == 200
    return response.json()


@pytest.fixture(scope="module")
def summaries(default_page) -> list[dict]:
    return default_page["items"]


@pytest.fixture(scope="module")
def first_patient_id(id_mapping) -> str:
    return next(iter(id_mapping))


@pytest.fixture(scope="module")
def detail(first_patient_id) -> dict:
    response = client.get(f"/api/patients/{first_patient_id}")
    assert response.status_code == 200
    return response.json()


# ── ID mapping tests ─────────────────────────────────────────────────────


def test_mapping_covers_full_dataset(id_mapping) -> None:
    all_record_ids = set(discover_patient_ids())
    assert len(id_mapping) == 3200
    assert set(id_mapping.values()) == all_record_ids


def test_mapping_has_more_than_five_patients(id_mapping) -> None:
    assert len(id_mapping) > 5


def test_mapping_is_deterministic() -> None:
    first, _ = build_patient_id_mapping()
    second, _ = build_patient_id_mapping()
    assert first == second


def test_mapping_opaque_ids_are_unique(id_mapping) -> None:
    assert len(id_mapping) == len(set(id_mapping.keys()))


def test_mapping_preserves_original_public_ids(id_mapping) -> None:
    for public_id, record_id in PRESERVED_PUBLIC_ID_RECORDS.items():
        assert id_mapping[public_id] == record_id


def test_mapping_does_not_use_outcomes() -> None:
    # The build function must not import or use load_outcomes
    import inspect
    source = inspect.getsource(build_patient_id_mapping)
    assert "load_outcomes" not in source
    assert "outcome" not in source.lower()
    assert "death" not in source.lower()


# ── Patient list endpoint tests ──────────────────────────────────────────


def test_health_endpoint() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "api": "online",
        "models": "ready",
        "patient_data": "available",
        "model_family": "Random Forest V2",
        "primary_checkpoint": "12h",
        "supported_checkpoints": ["6h", "12h", "24h"],
    }


def test_health_response_is_safe() -> None:
    payload = client.get("/api/health").json()
    assert set(payload) == {
        "status", "api", "models", "patient_data", "model_family",
        "primary_checkpoint", "supported_checkpoints",
    }
    assert _all_keys(payload).isdisjoint(FORBIDDEN_RESPONSE_FIELDS)
    serialized = json.dumps(payload).lower()
    assert "\\" not in serialized
    assert "outcome" not in serialized
    assert "recordid" not in serialized


def test_health_model_status_uses_runtime_readiness(monkeypatch) -> None:
    service = get_patient_inference_service()
    monkeypatch.setattr(service, "models", {})

    payload = client.get("/api/health").json()

    assert payload["status"] == "degraded"
    assert payload["models"] == "unavailable"
    assert payload["patient_data"] == "available"


def test_health_patient_data_status_uses_data_source(monkeypatch) -> None:
    def missing_patient_dir():
        raise FileNotFoundError("synthetic missing data source")

    monkeypatch.setattr(
        patient_service_module, "get_patient_dir", missing_patient_dir,
    )

    payload = client.get("/api/health").json()

    assert payload["status"] == "degraded"
    assert payload["models"] == "ready"
    assert payload["patient_data"] == "unavailable"


def test_health_handles_unavailable_service_without_details(monkeypatch) -> None:
    def unavailable_service():
        raise RuntimeError("private internal detail")

    monkeypatch.setattr(
        health_routes_module,
        "get_patient_inference_service",
        unavailable_service,
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["models"] == "unavailable"
    assert response.json()["patient_data"] == "unavailable"
    assert "private internal detail" not in response.text


def test_health_does_not_run_inference(monkeypatch) -> None:
    service = get_patient_inference_service()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("health check must not run inference")

    monkeypatch.setattr(service, "_compute_summaries", fail_if_called)
    monkeypatch.setattr(service, "_compute_detail", fail_if_called)
    for model in service.models.values():
        monkeypatch.setattr(model, "predict_proba", fail_if_called)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_default_patient_pagination(default_page, id_mapping) -> None:
    assert len(default_page["items"]) == 25
    assert default_page["page"] == 1
    assert default_page["page_size"] == 25
    assert default_page["total"] == len(id_mapping) == 3200
    assert default_page["total_pages"] == 128
    assert default_page["cohort_total"] == 3200
    assert default_page["result_scope"] == "cohort"
    assert [item["patient_id"] for item in default_page["items"]] == [
        f"ICU-{number}" for number in range(1001, 1026)
    ]


def test_patients_returns_more_than_five(summaries) -> None:
    assert len(summaries) > 5


@pytest.mark.parametrize(
    "query",
    ["page=0", "page_size=0", "page_size=101", "risk=UNKNOWN",
     "alert=UNKNOWN", "scope=unknown", "sort_by=risk",
     "sort_order=sideways"],
)
def test_patient_query_validation(query) -> None:
    response = client.get(f"/api/patients?{query}")

    assert response.status_code == 422


def test_last_page_behavior() -> None:
    response = client.get("/api/patients?page=128&page_size=25")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 25
    assert payload["items"][0]["patient_id"] == "ICU-4176"
    assert payload["items"][-1]["patient_id"] == "ICU-4200"


def test_exact_public_id_search_is_case_insensitive() -> None:
    response = client.get("/api/patients?search=icu-2050")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["patient_id"] for item in payload["items"]] == ["ICU-2050"]


def test_unknown_public_id_search_is_empty() -> None:
    response = client.get("/api/patients?search=ICU-9999")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["total"] == 0
    assert payload["total_pages"] == 0


def test_patient_id_sorting_descending() -> None:
    response = client.get("/api/patients?sort_order=desc&page_size=5")

    assert response.status_code == 200
    assert [item["patient_id"] for item in response.json()["items"]] == [
        "ICU-4200", "ICU-4199", "ICU-4198", "ICU-4197", "ICU-4196",
    ]


def test_risk_and_alert_filters_use_cached_assessments(summaries) -> None:
    expected = summaries[0]
    response = client.get(
        "/api/patients",
        params={
            "risk": expected["risk_level"],
            "alert": expected["alert_state"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result_scope"] == "cached_assessments"
    assert payload["cached_assessments"] >= 25
    assert all(
        item["risk_level"] == expected["risk_level"]
        and item["alert_state"] == expected["alert_state"]
        for item in payload["items"]
    )


def test_patients_summaries_have_correct_schema(summaries) -> None:
    expected_fields = {
        "assessment_status",
        "assessment_reason",
        "temporal_observation_count",
        "patient_id",
        "icu_type",
        "checkpoint",
        "risk_probability",
        "risk_level",
        "alert_state",
        "risk_trend",
    }
    for patient in summaries:
        assert set(patient) == expected_fields
        assert patient["checkpoint"] == "12h"
        assert 0 <= patient["risk_probability"] <= 1
        assert patient["risk_level"] in {"LOW", "MEDIUM", "HIGH"}
        assert patient["alert_state"] in {
            "NO_ALERT", "WATCH", "HIGH_ALERT",
        }
        assert patient["risk_trend"] in {"Rising", "Stable", "Falling"}


def test_summary_response_contains_no_identifiers_or_outcomes(
    summaries, id_mapping
) -> None:
    assert _all_keys(summaries).isdisjoint(FORBIDDEN_RESPONSE_FIELDS)
    # Verify no raw RecordID appears in the serialized JSON.
    # Use set intersection rather than O(n²) substring search.
    serialized = json.dumps(summaries)
    record_id_strings = {str(rid) for rid in id_mapping.values()}
    # Extract all contiguous digit sequences from the serialized JSON
    found_numbers = set(re.findall(r"\d{5,}", serialized))
    leaked = record_id_strings & found_numbers
    assert not leaked, f"RecordIDs leaked in summary response: {leaked}"


# ── Detail endpoint tests ────────────────────────────────────────────────


def test_detail_endpoint_has_exact_prefix_safe_trajectory(detail) -> None:
    assert detail["primary_checkpoint"] == "12h"
    assert [point["checkpoint"] for point in detail["risk_trajectory"]] == [
        "6h", "12h", "24h",
    ]
    for point in detail["risk_trajectory"]:
        assert 0 <= point["risk_probability"] <= 1
        assert point["risk_level"] in {"LOW", "MEDIUM", "HIGH"}
        assert point["alert_state"] in {
            "NO_ALERT", "WATCH", "HIGH_ALERT",
        }

    primary = detail["risk_trajectory"][1]
    assert detail["risk_probability"] == pytest.approx(
        primary["risk_probability"], abs=1e-15
    )
    assert detail["risk_level"] == primary["risk_level"]
    assert detail["alert_state"] == primary["alert_state"]


def test_unknown_patient_id_returns_404() -> None:
    response = client.get("/api/patients/ICU-NOT-IN-COHORT")

    assert response.status_code == 404
    assert response.json() == {"detail": "Patient not found"}


def test_arbitrary_non_first_patient_detail(id_mapping) -> None:
    """A patient that was NOT in the original 5-patient allowlist must work."""
    # Pick the 100th patient (arbitrary, well beyond the original 5)
    opaque_ids = list(id_mapping.keys())
    chosen_id = opaque_ids[min(99, len(opaque_ids) - 1)]
    response = client.get(f"/api/patients/{chosen_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == chosen_id
    assert data["primary_checkpoint"] == "12h"
    assert 0 <= data["risk_probability"] <= 1
    assert len(data["risk_trajectory"]) == 3


def test_last_mapped_patient_detail(id_mapping) -> None:
    last_patient_id = next(reversed(id_mapping))
    response = client.get(f"/api/patients/{last_patient_id}")

    assert last_patient_id == "ICU-4200"
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == last_patient_id
    assert 0 <= data["risk_probability"] <= 1
    assert [point["checkpoint"] for point in data["risk_trajectory"]] == [
        "6h", "12h", "24h",
    ]


def test_detail_vitals_are_observations_through_24h(detail) -> None:
    histories = detail["vital_histories"]
    assert {series["parameter"] for series in histories} == set(VITAL_PARAMETERS)

    for series in histories:
        times = [point["time_minutes"] for point in series["measurements"]]
        assert times == sorted(times)
        assert all(0 <= time <= EXPECTED_CUTOFFS["24h"] for time in times)
        assert all(isinstance(point["value"], (int, float))
                   for point in series["measurements"])


def test_detail_response_contains_no_identifiers_or_outcomes(
    detail, id_mapping
) -> None:
    assert _all_keys(detail).isdisjoint(FORBIDDEN_RESPONSE_FIELDS)
    serialized = json.dumps(detail)
    record_id = id_mapping[detail["patient_id"]]
    assert str(record_id) not in serialized


# ── ML safety tests ──────────────────────────────────────────────────────


def test_record_id_and_outcomes_are_not_model_features() -> None:
    feature_columns = get_feature_columns_v2()

    assert "RecordID" not in feature_columns
    assert set(feature_columns).isdisjoint(LEAKAGE_COLUMNS)


def test_backend_predictions_are_invariant_to_future_observations(
    service, id_mapping
) -> None:
    # Use the first patient from the mapping
    first_opaque = next(iter(id_mapping))
    record_id = id_mapping[first_opaque]
    prepared = preprocess_patient(load_patient(record_id))
    full_trajectory = service.score_preprocessed_patient(
        record_id,
        prepared,
        tuple(EXPECTED_CUTOFFS),
    )

    for position, (checkpoint, cutoff_minutes) in enumerate(
        EXPECTED_CUTOFFS.items()
    ):
        assert (prepared["Time_minutes"] > cutoff_minutes).any()
        truncated = observations_up_to(prepared, cutoff_minutes)
        truncated_trajectory = service.score_preprocessed_patient(
            record_id,
            truncated,
            tuple(EXPECTED_CUTOFFS)[: position + 1],
        )
        assert full_trajectory[position].risk_probability == pytest.approx(
            truncated_trajectory[-1].risk_probability,
            rel=0,
            abs=1e-15,
        )


def test_12h_summary_alert_uses_only_6h_and_12h_history(
    summaries,
    detail,
    service,
    monkeypatch,
) -> None:
    probabilities_through_12h = [
        point["risk_probability"] for point in detail["risk_trajectory"][:2]
    ]
    expected = probabilities_to_alert_timeline(
        probabilities_through_12h,
        service.medium_threshold,
        service.high_threshold,
    )[-1]["alert_state"]
    matching_summary = next(
        patient
        for patient in summaries
        if patient["patient_id"] == detail["patient_id"]
    )
    assert matching_summary["alert_state"] == expected

    def fail_if_24h_is_scored(_matrix):
        raise AssertionError("12h summary must not call the 24h model")

    uncached_service = PatientInferenceService()
    monkeypatch.setattr(
        uncached_service.models["24h"],
        "predict_proba",
        fail_if_24h_is_scored,
    )
    id_mapping, _ = build_patient_id_mapping()
    second_opaque = list(id_mapping)[1]
    summary = uncached_service.get_patient_summary(second_opaque)
    assert summary.checkpoint == "12h"


# ── Service behavior tests ───────────────────────────────────────────────


def test_models_are_loaded_once_per_process() -> None:
    first = get_patient_inference_service()
    second = get_patient_inference_service()

    assert first is second
    assert first.models is second.models


def test_missing_manifest_raises_clear_configuration_error(tmp_path) -> None:
    with pytest.raises(InferenceConfigurationError, match="manifest not found"):
        PatientInferenceService(tmp_path)


def test_manifest_schema_mismatch_raises_clear_configuration_error(
    tmp_path,
) -> None:
    manifest_path = tmp_path / "rf_v2_manifest.json"
    manifest_path.write_text(
        json.dumps({"feature_version": "V1"}),
        encoding="utf-8",
    )

    with pytest.raises(
        InferenceConfigurationError,
        match="feature_version must be V2",
    ):
        PatientInferenceService(tmp_path)


def test_malformed_patient_data_returns_controlled_500(monkeypatch) -> None:
    def malformed_patient(_record_id: int) -> pd.DataFrame:
        raise OSError(r"B:\private\patient-file.txt could not be read")

    fresh_service = PatientInferenceService()
    monkeypatch.setattr(patient_service_module, "load_patient", malformed_patient)
    monkeypatch.setattr(
        patient_routes_module,
        "get_patient_inference_service",
        lambda: fresh_service,
    )
    test_id = next(iter(build_patient_id_mapping()[0]))
    response = client.get(f"/api/patients/{test_id}")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to process patient data"
    }
    assert "private" not in response.text.lower()
    assert test_id not in fresh_service._detail_cache


def test_detail_model_failure_returns_safe_500_without_cache(
    monkeypatch,
) -> None:
    fresh_service = PatientInferenceService()
    test_id = next(iter(build_patient_id_mapping()[0]))

    def failed_prediction(_matrix):
        raise RuntimeError(r"model failed at B:\private\artifact.joblib")

    monkeypatch.setattr(
        fresh_service.models["6h"], "predict_proba", failed_prediction,
    )
    monkeypatch.setattr(
        patient_routes_module,
        "get_patient_inference_service",
        lambda: fresh_service,
    )

    response = client.get(f"/api/patients/{test_id}")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to process patient data"
    }
    assert "private" not in response.text.lower()
    assert "risk_probability" not in response.text
    assert "risk_level" not in response.text
    assert "alert_state" not in response.text
    assert test_id not in fresh_service._detail_cache


def test_page_model_failure_returns_safe_500_without_cache(
    monkeypatch,
) -> None:
    fresh_service = PatientInferenceService()

    def failed_prediction(_matrix):
        raise RuntimeError("synthetic model failure")

    monkeypatch.setattr(
        fresh_service.models["6h"], "predict_proba", failed_prediction,
    )
    monkeypatch.setattr(
        patient_routes_module,
        "get_patient_inference_service",
        lambda: fresh_service,
    )

    response = client.get("/api/patients?page=1&page_size=2")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to process patient data"
    }
    assert fresh_service._summary_cache == {}


# ── Caching tests ────────────────────────────────────────────────────────


def test_caching_does_not_alter_summary_predictions(service) -> None:
    """Batched and repeated public summaries preserve inference results."""
    patient_id = list(build_patient_id_mapping()[0])[100]
    cached = service.get_patient_summary(patient_id)
    uncached_service = PatientInferenceService()
    fresh = uncached_service.get_patient_summary(patient_id)
    repeated = service.get_patient_summary(patient_id)

    assert repeated is cached
    assert cached.risk_probability == pytest.approx(
        fresh.risk_probability, abs=1e-15
    )
    assert cached.risk_level == fresh.risk_level
    assert cached.alert_state == fresh.alert_state
    assert cached.risk_trend == fresh.risk_trend


def test_caching_does_not_alter_detail_predictions(service) -> None:
    """Repeated public detail calls return the identical cached result."""
    patient_id = next(iter(build_patient_id_mapping()[0]))
    first = service.get_patient_detail(patient_id)
    second = service.get_patient_detail(patient_id)

    assert second is first


def test_repeated_page_request_reuses_summary_inference(monkeypatch) -> None:
    fresh_service = PatientInferenceService()
    calls = {"6h": 0, "12h": 0}

    for checkpoint in calls:
        original_predict = fresh_service.models[checkpoint].predict_proba

        def counting_predict(matrix, *, label=checkpoint, predict=original_predict):
            calls[label] += 1
            return predict(matrix)

        monkeypatch.setattr(
            fresh_service.models[checkpoint],
            "predict_proba",
            counting_predict,
        )

    first = fresh_service.get_patient_page(page=1, page_size=5)
    second = fresh_service.get_patient_page(page=1, page_size=5)

    assert calls == {"6h": 1, "12h": 1}
    assert first.items == second.items


def test_failed_page_inference_never_caches_partial_results(monkeypatch) -> None:
    fresh_service = PatientInferenceService()
    original_load_patient = patient_service_module.load_patient
    page_record_ids = list(build_patient_id_mapping()[0].values())[:2]
    first_loads = 0
    failures = 0

    def fail_after_one_patient(record_id: int) -> pd.DataFrame:
        nonlocal failures, first_loads
        if record_id == page_record_ids[0]:
            first_loads += 1
        if record_id == page_record_ids[1]:
            failures += 1
            raise ValueError("synthetic page load failure")
        return original_load_patient(record_id)

    monkeypatch.setattr(
        patient_service_module,
        "load_patient",
        fail_after_one_patient,
    )

    for _ in range(2):
        with pytest.raises(PatientInferenceError):
            fresh_service.get_patient_page(page=1, page_size=2)
    assert first_loads == 2
    assert failures == 2


def test_patient_count_matches_dataset(service) -> None:
    assert service.patient_count == len(discover_patient_ids())
