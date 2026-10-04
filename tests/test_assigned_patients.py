"""Assigned queue counts cover the assigned set, independently of search."""
from types import SimpleNamespace
import backend.services.assigned_patients as assigned
from backend.schemas.patient import PatientSummary


def test_search_and_pagination_cannot_change_or_expand_assigned_counts(monkeypatch):
    ids = ["ICU-1001", "ICU-1002"]
    monkeypatch.setattr(assigned, "assigned_ids", lambda user_id: ids)
    summaries = {
        pid: PatientSummary(patient_id=pid, icu_type="MICU", checkpoint="12h",
                            temporal_observation_count=2, risk_probability=score,
                            risk_level=risk, alert_state=alert, risk_trend="Stable")
        for pid, score, risk, alert in [(ids[0], .1, "LOW", "NO_ALERT"),
                                       (ids[1], .5, "HIGH", "WATCH")]
    }
    requested = []

    def load(patient_ids):
        requested.extend(patient_ids)
        return [summaries[pid] for pid in patient_ids]

    service = SimpleNamespace(_public_id_number=lambda pid: int(pid.split("-")[1]),
                              _get_patient_summaries=load, _summary_cache=summaries)
    result = assigned.assigned_page(service, 10, page=1, page_size=1, search="1001",
                                    risk=None, alert=None, scope="all", sort_order="asc")
    assert result.cohort_total == 2 and result.total == 1
    assert [item.patient_id for item in result.items] == ["ICU-1001"]
    assert result.assessment_counts.high_risk == 1
    assert result.assessment_counts.watch == 1
    assert result.assessment_counts.no_alert == 1
    assert set(requested) == set(ids)
