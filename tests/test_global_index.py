"""Safety and persistence tests for the complete patient assessment index."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.routes.patients as patient_routes_module
import backend.services.patient_service as patient_service_module
from backend.main import app
from backend.schemas.patient import PatientSummary
from backend.services.patient_service import (
    PatientInferenceError,
    PatientInferenceService,
)


client = TestClient(app)
PATIENT_FIELDS = {
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
FORBIDDEN_TEXT = {
    "recordid",
    "record_id",
    "in-hospital_death",
    "in_hospital_death",
    "survival",
    "length_of_stay",
}


def _service(index_path: Path) -> PatientInferenceService:
    return PatientInferenceService(global_index_path=index_path)


def _summary(patient_id: str) -> PatientSummary:
    return PatientSummary(
        temporal_observation_count=1,
        patient_id=patient_id,
        icu_type="MICU",
        checkpoint="12h",
        risk_probability=0.1,
        risk_level="LOW",
        alert_state="NO_ALERT",
        risk_trend="Stable",
    )


def _varied_complete_index(
    service: PatientInferenceService,
) -> dict[str, PatientSummary]:
    variants = [
        (0.1, "LOW", "NO_ALERT"),
        (0.3, "MEDIUM", "WATCH"),
        (0.4, "MEDIUM", "HIGH_ALERT"),
        (0.7, "HIGH", "WATCH"),
        (0.8, "HIGH", "HIGH_ALERT"),
    ]
    index = {}
    for position, patient_id in enumerate(service._opaque_to_record):
        probability, risk, alert = variants[position % len(variants)]
        index[patient_id] = PatientSummary(
            temporal_observation_count=1,
            patient_id=patient_id,
            icu_type="MICU",
            checkpoint="12h",
            risk_probability=probability,
            risk_level=risk,
            alert_state=alert,
            risk_trend="Stable",
        )
    return index


def _publish_ready_index(
    service: PatientInferenceService,
    index: dict[str, PatientSummary],
) -> None:
    service._validate_complete_global_index(index)
    service._global_index = dict(index)
    service._global_index_state = "ready"
    service._global_index_completed = service.patient_count
    service._global_index_message = (
        "Complete patient assessment index is ready."
    )


@pytest.fixture(scope="module")
def ready_global_service(tmp_path_factory) -> PatientInferenceService:
    service = _service(tmp_path_factory.mktemp("global-query") / "index.json")
    _publish_ready_index(service, _varied_complete_index(service))
    return service


def _complete_synthetic_index(
    service: PatientInferenceService,
) -> dict[str, PatientSummary]:
    return {
        patient_id: _summary(patient_id)
        for patient_id in service._opaque_to_record
    }


def _use_small_real_cohort(
    service: PatientInferenceService,
    count: int = 3,
) -> list[str]:
    subset = dict(list(service._opaque_to_record.items())[:count])
    service._opaque_to_record = subset
    service._record_to_opaque = {
        record_id: patient_id
        for patient_id, record_id in subset.items()
    }
    service._summary_cache.clear()
    return list(subset)


def _set_building(service: PatientInferenceService) -> None:
    service._global_index_state = "building"
    service._global_index_completed = 0
    service._global_index_message = (
        "Preparing complete patient assessment index."
    )


def test_status_and_normal_page_do_not_start_global_build(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path / "index.json")
    monkeypatch.setattr(
        patient_routes_module,
        "get_patient_inference_service",
        lambda: service,
    )

    status_response = client.get("/api/patients/global-index/status")
    page_response = client.get("/api/patients?page=1&page_size=2")

    assert status_response.status_code == 200
    assert status_response.json()["state"] == "not_started"
    assert page_response.status_code == 200
    assert len(page_response.json()["items"]) == 2
    assert service.get_global_index_status().state == "not_started"
    assert not service.global_index_path.exists()


def test_prepare_is_background_and_duplicate_calls_start_one_worker(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path / "index.json")
    workers = []

    class DeferredThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            workers.append(self)

    monkeypatch.setattr(patient_service_module, "Thread", DeferredThread)
    monkeypatch.setattr(
        patient_routes_module,
        "get_patient_inference_service",
        lambda: service,
    )

    first = client.post("/api/patients/global-index/prepare")
    second = client.post("/api/patients/global-index/prepare")

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["state"] == "building"
    assert second.json()["state"] == "building"
    assert len(workers) == 1


def test_successful_build_reuses_exact_summary_inference(
    tmp_path,
) -> None:
    service = _service(tmp_path / "index.json")
    patient_ids = _use_small_real_cohort(service)
    _set_building(service)

    service._run_global_index_build()

    status = service.get_global_index_status()
    assert status.state == "ready"
    assert status.completed_patients == len(patient_ids)
    stored = {
        item.patient_id: item
        for item in service.get_global_index_summaries()
    }
    assert set(stored) == set(patient_ids)

    representative = patient_ids[0]
    service._summary_cache.clear()
    normal_summary = service.get_patient_summary(representative)
    assert stored[representative].model_dump() == normal_summary.model_dump()


def test_ready_requires_exactly_3200_unique_public_ids(tmp_path) -> None:
    service = _service(tmp_path / "index.json")
    complete = _complete_synthetic_index(service)

    assert len(complete) == 3200
    service._validate_complete_global_index(complete)

    incomplete = dict(complete)
    incomplete.pop(next(iter(incomplete)))
    with pytest.raises(ValueError, match="does not cover"):
        service._validate_complete_global_index(incomplete)


def test_failed_build_never_publishes_partial_or_leaks_details(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path / "index.json")
    _use_small_real_cohort(service)
    _set_building(service)

    def fail_with_private_detail(_patient_ids):
        raise PatientInferenceError(
            r"failed at B:\private\patient-2917.txt"
        )

    monkeypatch.setattr(service, "_compute_summaries", fail_with_private_detail)
    service._run_global_index_build()

    status = service.get_global_index_status()
    assert status.state == "failed"
    assert status.completed_patients == 0
    assert "private" not in status.message.lower()
    assert "2917" not in status.message
    assert service._global_index is None
    assert service._summary_cache == {}
    assert not service.global_index_path.exists()


def test_ready_index_is_reused_without_starting_rebuild(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path / "index.json")
    _use_small_real_cohort(service)
    complete = _complete_synthetic_index(service)
    service._persist_global_index(complete)
    service._global_index = dict(complete)
    service._global_index_state = "ready"
    service._global_index_completed = service.patient_count
    service._global_index_message = (
        "Complete patient assessment index is ready."
    )

    class UnexpectedThread:
        def __init__(self, **_kwargs):
            raise AssertionError("READY index must not start another build")

    monkeypatch.setattr(patient_service_module, "Thread", UnexpectedThread)

    assert service.prepare_global_index().state == "ready"
    assert len(service.get_global_index_summaries()) == service.patient_count


def test_persistence_uses_atomic_replace_and_cleans_temporary_file(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "index.json"
    service = _service(path)
    _use_small_real_cohort(service)
    complete = _complete_synthetic_index(service)
    real_replace = patient_service_module.os.replace
    replacements = []

    def recording_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(patient_service_module.os, "replace", recording_replace)
    service._persist_global_index(complete)

    assert path.is_file()
    assert len(replacements) == 1
    source, destination = replacements[0]
    assert source != destination == path
    assert not source.exists()


def test_atomic_write_failure_leaves_no_published_or_temporary_file(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "index.json"
    service = _service(path)
    _use_small_real_cohort(service)
    complete = _complete_synthetic_index(service)

    def failed_replace(_source, _destination):
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(patient_service_module.os, "replace", failed_replace)
    with pytest.raises(OSError, match="replace failure"):
        service._persist_global_index(complete)

    assert not path.exists()
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_valid_persisted_index_loads_without_inference(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "index.json"
    first = _service(path)
    complete = _complete_synthetic_index(first)
    first._persist_global_index(complete)

    def inference_must_not_run(*_args, **_kwargs):
        raise AssertionError("persisted-index load must not run inference")

    monkeypatch.setattr(
        PatientInferenceService,
        "_compute_summaries",
        inference_must_not_run,
    )
    restarted = _service(path)

    assert restarted.get_global_index_status().state == "ready"
    assert len(restarted.get_global_index_summaries()) == 3200
    assert restarted._summary_cache == {}


@pytest.mark.parametrize(
    "contents",
    [
        "{not-json",
        json.dumps({"metadata": {"index_schema_version": -1}, "patients": []}),
    ],
)
def test_corrupt_or_stale_persisted_index_is_rejected_safely(
    tmp_path,
    contents,
) -> None:
    path = tmp_path / "index.json"
    path.write_text(contents, encoding="utf-8")

    service = _service(path)

    status = service.get_global_index_status()
    assert status.state == "not_started"
    assert status.completed_patients == 0
    assert service._global_index is None


def test_duplicate_or_partial_persisted_cohort_is_rejected(
    tmp_path,
) -> None:
    path = tmp_path / "index.json"
    writer = _service(path)
    complete = _complete_synthetic_index(writer)
    writer._persist_global_index(complete)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["patients"][-1] = dict(payload["patients"][0])
    path.write_text(json.dumps(payload), encoding="utf-8")

    restarted = _service(path)

    assert restarted.get_global_index_status().state == "not_started"
    assert restarted._global_index is None


def test_persisted_index_contains_only_safe_public_summary_fields(
    tmp_path,
) -> None:
    path = tmp_path / "index.json"
    service = _service(path)
    complete = _complete_synthetic_index(service)
    service._persist_global_index(complete)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert len(payload["patients"]) == 3200
    assert all(set(item) == PATIENT_FIELDS for item in payload["patients"])
    serialized = json.dumps(payload).lower()
    assert all(forbidden not in serialized for forbidden in FORBIDDEN_TEXT)
    raw_record_ids = {str(value) for value in service._opaque_to_record.values()}
    persisted_numbers = set(re.findall(r"\d{5,}", serialized))
    assert raw_record_ids.isdisjoint(persisted_numbers)
    assert "\\private\\" not in serialized


def test_existing_page_and_detail_apis_remain_compatible(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path / "index.json")
    monkeypatch.setattr(
        patient_routes_module,
        "get_patient_inference_service",
        lambda: service,
    )
    first_patient_id = next(iter(service._opaque_to_record))

    page = client.get("/api/patients?page=1&page_size=2")
    detail = client.get(f"/api/patients/{first_patient_id}")

    assert page.status_code == 200
    assert page.json()["result_scope"] == "cohort"
    assert len(page.json()["items"]) == 2
    assert detail.status_code == 200
    assert detail.json()["patient_id"] == first_patient_id
    assert service.get_global_index_status().state == "not_started"


# -- complete-index query behavior ------------------------------------------


def test_all_scope_requires_ready_and_never_uses_summary_cache(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path / "index.json")
    patient_id = next(iter(service._opaque_to_record))
    service._summary_cache[patient_id] = _summary(patient_id)
    monkeypatch.setattr(
        patient_routes_module,
        "get_patient_inference_service",
        lambda: service,
    )

    response = client.get("/api/patients?scope=all")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Complete patient assessments are not ready"
    }


@pytest.mark.parametrize(
    ("risk", "expected_total"),
    [("LOW", 640), ("MEDIUM", 1280), ("HIGH", 1280)],
)
def test_all_scope_risk_filters_are_complete(
    ready_global_service,
    risk,
    expected_total,
) -> None:
    result = ready_global_service.get_patient_page(
        page=1,
        page_size=25,
        risk=risk,
        scope="all",
    )

    assert result.total == expected_total
    assert all(item.risk_level == risk for item in result.items)


@pytest.mark.parametrize(
    ("alert", "expected_total"),
    [("NO_ALERT", 640), ("WATCH", 1280), ("HIGH_ALERT", 1280)],
)
def test_all_scope_alert_filters_are_complete(
    ready_global_service,
    alert,
    expected_total,
) -> None:
    result = ready_global_service.get_patient_page(
        page=1,
        page_size=25,
        alert=alert,
        scope="all",
    )

    assert result.total == expected_total
    assert all(item.alert_state == alert for item in result.items)


def test_all_scope_combines_risk_and_alert_with_and(
    ready_global_service,
) -> None:
    result = ready_global_service.get_patient_page(
        page=1,
        page_size=25,
        risk="HIGH",
        alert="WATCH",
        scope="all",
    )

    assert result.total == 640
    assert all(
        item.risk_level == "HIGH" and item.alert_state == "WATCH"
        for item in result.items
    )


def test_all_scope_searches_before_pagination(ready_global_service) -> None:
    result = ready_global_service.get_patient_page(
        page=2,
        page_size=25,
        search="ICU-1",
        scope="all",
    )

    assert result.total == 999
    assert result.total_pages == 40
    assert result.items[0].patient_id == "ICU-1026"
    assert all("ICU-1" in item.patient_id for item in result.items)


def test_all_scope_sorts_before_pagination(ready_global_service) -> None:
    result = ready_global_service.get_patient_page(
        page=2,
        page_size=2,
        scope="all",
        sort_order="desc",
    )

    assert [item.patient_id for item in result.items] == [
        "ICU-4198",
        "ICU-4197",
    ]


def test_all_scope_filters_before_pagination(ready_global_service) -> None:
    complete = ready_global_service.get_global_index_summaries()
    expected = [item for item in complete if item.risk_level == "HIGH"]

    result = ready_global_service.get_patient_page(
        page=2,
        page_size=3,
        risk="HIGH",
        scope="all",
    )

    assert result.total == len(expected) == 1280
    assert result.total_pages == 427
    assert result.items == expected[3:6]


def test_all_scope_metadata_and_counts_cover_complete_cohort(
    ready_global_service,
) -> None:
    result = ready_global_service.get_patient_page(
        page=1,
        page_size=25,
        risk="HIGH",
        scope="all",
    )

    assert result.result_scope == "complete_assessment_index"
    assert result.cohort_total == 3200
    assert result.total == 1280
    assert result.total_pages == 52
    assert result.assessment_counts is not None
    assert result.assessment_counts.model_dump() == {
        "not_assessed": 0,
        "high_risk": 1280,
        "watch": 1280,
        "no_alert": 640,
    }


def test_all_scope_zero_match_is_valid(ready_global_service) -> None:
    result = ready_global_service.get_patient_page(
        page=1,
        page_size=25,
        risk="LOW",
        alert="WATCH",
        scope="all",
    )

    assert result.items == []
    assert result.total == 0
    assert result.total_pages == 0
    assert result.result_scope == "complete_assessment_index"


def test_ready_all_scope_does_not_run_inference(
    ready_global_service,
    monkeypatch,
) -> None:
    def inference_must_not_run(*_args, **_kwargs):
        raise AssertionError("READY global filtering must not run inference")

    monkeypatch.setattr(
        ready_global_service,
        "_compute_summaries",
        inference_must_not_run,
    )
    for model in ready_global_service.models.values():
        monkeypatch.setattr(model, "predict_proba", inference_must_not_run)

    result = ready_global_service.get_patient_page(
        page=3,
        page_size=25,
        risk="MEDIUM",
        alert="WATCH",
        scope="all",
    )

    assert len(result.items) == 25
    assert result.total == 640


def test_all_scope_route_returns_complete_result_contract(
    ready_global_service,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        patient_routes_module,
        "get_patient_inference_service",
        lambda: ready_global_service,
    )

    response = client.get(
        "/api/patients",
        params={
            "scope": "all",
            "risk": "MEDIUM",
            "alert": "HIGH_ALERT",
            "page": 2,
            "page_size": 10,
            "sort_order": "desc",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result_scope"] == "complete_assessment_index"
    assert payload["total"] == 640
    assert payload["total_pages"] == 64
    assert len(payload["items"]) == 10
    assert payload["assessment_counts"] == {
        "not_assessed": 0,
        "high_risk": 1280,
        "watch": 1280,
        "no_alert": 640,
    }
