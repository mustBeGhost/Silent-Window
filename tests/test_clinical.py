"""Clinical context uses real sessions, assigned access and isolated storage."""
import pytest
from test_auth import store, signed, assign
from backend.main import app
from fastapi.testclient import TestClient

pytestmark = pytest.mark.real_auth
BASE = "/api/patients/ICU-1001/clinical"


def timed(**kwargs):
    return {"minute": 360, "as_of_minutes": 720, **kwargs}


def test_clinical_reads_require_login_and_assigned_patient_access(store):
    assert TestClient(app).get(BASE).status_code == 401
    assert signed("researcher").get(BASE).status_code == 403
    assert signed("doctor").get(BASE).status_code == 403
    admin = signed(); assign(admin, "doctor", "nurse")
    assert signed("doctor").get(BASE).status_code == 200
    assert signed("nurse").get(BASE).status_code == 200
    assert admin.get("/api/patients/ICU-999999/clinical").status_code == 404


def test_recorded_bp_is_separate_and_future_readings_are_hidden(store):
    admin = signed()
    result = admin.get(BASE + "?as_of_minutes=360").json()
    assert result["context"] is None and result["rules"] == []
    assert [v["parameter"] for v in result["vitals"]][:6] == ["SysABP", "DiasABP", "MAP", "NISysABP", "NIDiasABP", "NIMAP"]
    for series in result["vitals"]:
        assert all(0 <= p["time_minutes"] <= 360 and p["value"] >= 0 for p in series["measurements"])
    zero = admin.get(BASE + "?as_of_minutes=0").json()
    assert all(all(p["time_minutes"] == 0 for p in v["measurements"]) for v in zero["vitals"])


def test_context_is_versioned_and_responsible_doctor_must_be_assigned(store):
    admin = signed()
    doctor_id = next(u["id"] for u in admin.get("/api/accounts").json() if u["role"] == "doctor")
    body = timed(diagnosis="Fictional demo diagnosis", physician_id=doctor_id)
    assert admin.post(BASE + "/context", json=body).status_code == 422
    assign(admin, "doctor")
    assert admin.post(BASE + "/context", json=body).status_code == 201
    assert admin.post(BASE + "/context", json=timed(minute=720, diagnosis="Revised demonstration")).status_code == 201
    early = admin.get(BASE + "?as_of_minutes=359").json()
    assert early["context"] is None and early["context_history"] == []
    old = admin.get(BASE + "?as_of_minutes=360").json()
    assert old["context"]["diagnosis"] == body["diagnosis"] and old["context"]["physician_available"]
    now = admin.get(BASE).json()
    assert len(now["context_history"]) == 2 and now["context"]["diagnosis"] == "Revised demonstration"
    assert admin.patch("/api/patients/ICU-1001/assignments/doctor", json={"user_ids": []}).status_code == 200
    assert not admin.get(BASE + "?as_of_minutes=360").json()["context"]["physician_available"]


def test_notes_are_independent_of_model_score_and_checkpoint_availability(store):
    admin = signed(); assign(admin, "doctor", "nurse")
    doctor = signed("doctor")
    before = admin.get("/api/patients/ICU-1001").json()
    payload = timed(minute=90, kind="visit", assessment="Fictional visit assessment", plan="Staff-entered demo plan", follow_up="Check the demo record", review_minute=180)
    assert doctor.post(BASE + "/entries", json=payload).status_code == 201
    assert admin.get(BASE + "?as_of_minutes=89").json()["entries"] == []
    early = admin.get(BASE + "?as_of_minutes=90&model_profile=expanded").json()
    assert early["entries"][0]["plan"] == payload["plan"] and early["entries"][0]["author"]
    assert admin.get("/api/patients/ICU-1001").json() == before
    assert signed("nurse").post(BASE + "/entries", json=payload).status_code == 403
    assert signed("nurse").post(BASE + "/entries", json={**payload, "kind": "escalation"}).status_code == 201


def test_writes_enforce_role_csrf_and_current_assignment(store):
    admin = signed(); assign(admin, "doctor", "nurse")
    nurse = signed("nurse"); doctor = signed("doctor")
    assert nurse.post(BASE + "/context", json=timed()).status_code == 403
    assert admin.post(BASE + "/rules", json=timed(rules=[])).status_code == 403
    assert nurse.post(BASE + "/rules", json=timed(rules=[])).status_code == 403
    doctor.headers.pop("X-CSRF-Token")
    assert doctor.post(BASE + "/context", json=timed()).status_code == 403
    doctor = signed("doctor")
    admin.patch("/api/patients/ICU-1001/assignments/doctor", json={"user_ids": []})
    assert doctor.post(BASE + "/entries", json=timed(kind="visit", assessment="Not allowed")).status_code == 403


@pytest.mark.parametrize("path,body", [
    ("context", timed(minute=721)), ("context", timed(minute=-1)),
    ("entries", timed(kind="visit", assessment="  ")),
    ("entries", timed(kind="visit", assessment="Demo", review_minute=10)),
    ("rules", timed(rules=[{"parameter": "MAP", "lower": 100, "upper": 50}])),
    ("rules", timed(rules=[{"parameter": "HR", "upper": "nan"}])),
    ("rules", timed(rules=[{"parameter": "HR", "upper": 100}, {"parameter": "HR", "upper": 200}])),
])
def test_invalid_or_future_entries_are_rejected(store, path, body):
    admin = signed(); assign(admin, "doctor")
    assert signed("doctor").post(BASE + "/" + path, json=body).status_code == 422


def test_doctor_rules_are_versioned_do_not_use_future_values_or_clear_model_alerts(store):
    admin = signed(); assign(admin, "doctor")
    doctor = signed("doctor")
    # Deliberately fictional engineering limits, not clinical recommendations.
    assert doctor.post(BASE + "/rules", json=timed(minute=0, rules=[{"parameter": "HR", "upper": 0}])).status_code == 201
    data = admin.get(BASE + "?as_of_minutes=720").json()
    warning = data["vital_warnings"][0]
    if warning["latest"]:
        assert warning["state"] == "OUTSIDE_ENTERED_LIMITS"
        assert warning["latest"]["time_minutes"] <= 720
    assert doctor.post(BASE + "/rules", json=timed(minute=721, as_of_minutes=1440, rules=[])).status_code == 201
    assert admin.get(BASE + "?as_of_minutes=720").json()["rules"]
    assert admin.get(BASE + "?as_of_minutes=721").json()["rules"] == []


def test_new_rules_do_not_retroactively_warn_on_an_older_reading(store):
    admin = signed(); assign(admin, "doctor")
    snapshot = admin.get(BASE).json()
    candidate = next((v for v in snapshot["vitals"] if v["measurements"] and v["measurements"][-1]["time_minutes"] < 1440), None)
    assert candidate is not None
    last = candidate["measurements"][-1]["time_minutes"]
    assert signed("doctor").post(BASE + "/rules", json=timed(minute=last + 1, as_of_minutes=1440, rules=[{"parameter": candidate["parameter"], "upper": 0}])).status_code == 201
    assert admin.get(BASE).json()["vital_warnings"][0]["state"] == "NO_READING_AFTER_RULE"


def test_acknowledgement_status_survives_history_limit_and_is_model_scoped(store):
    admin = signed()
    with store.db() as db:
        for i in range(202):
            db.execute("INSERT INTO patient_events(patient_id,model_profile,checkpoint,event_type,content,actor_id,actor_role,risk_score,alert_state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", ("ICU-1001", "original", "6h", "acknowledge" if i == 0 else "review", "Fictional test record", store.owner_id, "doctor", .5, "WATCH", store.clock()))
    data = admin.get(BASE + "?as_of_minutes=360").json()
    assert data["history_truncated"] and len(data["review_events"]) == 200
    assert len(data["acknowledgements"]) == 1
    assert not admin.get(BASE + "?as_of_minutes=359").json()["acknowledgements"]
    assert not admin.get(BASE + "?model_profile=calibrated").json()["acknowledgements"]
