"""Recorded observations and append-only staff-entered demonstration context."""
import json
import math
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, model_validator
from backend.auth import patient_access, require_patients, require_write
from backend.routes.accounts import StrictBody
from backend.routes.workflow import known_patient, recheck_actor, assigned_team
from backend.routes.patients import ModelProfile, selected_service
from backend.services.auth_service import get_auth_store
from backend.services.patient_service import PatientInferenceError
from ml.preprocessing import observations_up_to
from backend.services.follow_ups import follow_up_snapshot
from backend.services.doctor_reviews import patient_reviews, inbox, notification_summary

router = APIRouter(tags=["clinical demonstration"])
PARAMETERS = ("SysABP", "DiasABP", "MAP", "NISysABP", "NIDiasABP", "NIMAP", "HR", "RespRate", "SaO2", "Temp", "GCS", "Creatinine")
CONTEXT_ROLES = {"doctor", "coordinator", "admin"}
ENTRY_ROLES = {"visit": {"doctor"}, "assessment": {"doctor"}, "recommendation": {"doctor"},
               "follow_up": {"doctor", "nurse", "coordinator"}, "handover": {"doctor", "nurse", "coordinator"},
               "escalation": {"doctor", "nurse", "coordinator"}}


class TimedBody(StrictBody):
    minute: int = Field(ge=0, le=1440, strict=True)
    as_of_minutes: int = Field(ge=0, le=1440, strict=True)

    @model_validator(mode="after")
    def visible_time(self):
        if self.minute > self.as_of_minutes:
            raise ValueError("Entry time cannot be after the selected recorded view")
        return self


class ContextBody(TimedBody):
    diagnosis: str = Field(default="", max_length=300)
    admission_reason: str = Field(default="", max_length=2000)
    condition_summary: str = Field(default="", max_length=2000)
    admission_severity: str = Field(default="", max_length=100)
    specialty: str = Field(default="", max_length=100)
    physician_id: int | None = Field(default=None, gt=0, strict=True)


class ClinicalEntry(TimedBody):
    kind: Literal["visit", "assessment", "recommendation", "follow_up", "handover", "escalation"]
    assessment: str = Field(min_length=2, max_length=2000)
    plan: str = Field(default="", max_length=2000)
    follow_up: str = Field(default="", max_length=2000)
    escalation: str = Field(default="", max_length=2000)
    review_minute: int | None = Field(default=None, ge=0, le=1440, strict=True)

    @model_validator(mode="after")
    def review_time(self):
        if len(self.assessment.strip()) < 2:
            raise ValueError("Enter an assessment with at least two characters")
        if self.review_minute is not None and self.review_minute < self.minute:
            raise ValueError("Next review cannot be before the entry")
        return self


class VitalRule(StrictBody):
    parameter: Literal["SysABP", "DiasABP", "MAP", "NISysABP", "NIDiasABP", "NIMAP", "HR", "RespRate", "SaO2", "Temp", "GCS", "Creatinine"]
    lower: float | None = Field(default=None, ge=0, allow_inf_nan=False, strict=True)
    upper: float | None = Field(default=None, ge=0, allow_inf_nan=False, strict=True)

    @model_validator(mode="after")
    def bounds(self):
        if self.lower is None and self.upper is None:
            raise ValueError("Enter at least one limit")
        if self.lower is not None and self.upper is not None and self.lower >= self.upper:
            raise ValueError("Lower limit must be below upper limit")
        return self


class RulesBody(TimedBody):
    rules: list[VitalRule] = Field(max_length=12)

    @model_validator(mode="after")
    def unique_rules(self):
        if len({rule.parameter for rule in self.rules}) != len(self.rules):
            raise ValueError("Only one rule per measurement is allowed")
        return self


class FollowUpBody(TimedBody):
    status: Literal["pending", "completed"]
    expected_event_id: int = Field(ge=0, strict=True)
    content: str = Field(min_length=2, max_length=2000)

    @model_validator(mode="after")
    def meaningful_note(self):
        if len(self.content.strip()) < 2:
            raise ValueError("Explain the completion or reopening in at least two characters")
        return self


def authorize(db, principal, patient_id, roles):
    unit = recheck_actor(db, principal, roles)
    if not unit and not db.execute("SELECT 1 FROM assignments WHERE patient_id=? AND user_id=?", (patient_id, principal.user["id"])).fetchone():
        raise HTTPException(403, "This patient is no longer assigned to you.")


def recent(db, table, patient_id, minute):
    # The table is supplied only by the three application-owned call sites.
    return [dict(row) for row in db.execute(f"SELECT c.*,u.display_name AS author FROM {table} c JOIN users u ON u.id=c.actor_id WHERE c.patient_id=? AND c.minute<=? ORDER BY c.minute DESC,c.id DESC LIMIT 201", (patient_id, minute))]


@router.get("/patients/{patient_id}/clinical")
def clinical(patient_id: str, as_of_minutes: int = Query(1440, ge=0, le=1440),
             model_profile: ModelProfile = "original", principal=Depends(require_patients)):
    patient_access(principal, patient_id)
    known_patient(patient_id)
    service = selected_service(model_profile)
    try:
        patient, _ = service._load_patient_context(service._record_id(patient_id))
        visible = observations_up_to(patient, as_of_minutes)
    except PatientInferenceError:
        raise HTTPException(503, "Recorded observations could not be loaded.") from None
    vitals = []
    for parameter in PARAMETERS:
        rows = visible[(visible.Parameter == parameter) & visible.Value.notna() & (visible.Value >= 0)].sort_values("Time_minutes", kind="stable")
        vitals.append({"parameter": parameter, "measurements": [{"time_minutes": int(row.Time_minutes), "value": float(row.Value)} for row in rows.itertuples() if math.isfinite(row.Value)]})
    store = get_auth_store()
    with store.db() as db:
        # Recheck after data loading, including assignments that may have changed.
        authorize(db, principal, patient_id, {"admin", "coordinator", "doctor", "nurse"})
        contexts = recent(db, "patient_contexts", patient_id, as_of_minutes)
        entries = recent(db, "clinical_entries", patient_id, as_of_minutes)
        rule_versions = recent(db, "vital_rule_versions", patient_id, as_of_minutes)
        follow_ups = follow_up_snapshot(db, patient_id, as_of_minutes)
        review_requests = patient_reviews(db, patient_id, as_of_minutes)
        team = assigned_team(db, patient_id)
        for context in contexts:
            physician = db.execute("SELECT display_name,active,role FROM users WHERE id=?", (context["physician_id"],)).fetchone()
            context["physician_name"] = physician["display_name"] if physician else None
            context["physician_available"] = bool(physician and physician["active"] and physician["role"] == "doctor" and any(p["id"] == context["physician_id"] for p in team))
        checkpoints = [cp for cp, cutoff in service.cutoffs.items() if cutoff <= as_of_minutes]
        marks = ",".join("?" for _ in checkpoints)
        reviews = [dict(row) for row in db.execute(f"SELECT e.*,u.display_name AS author FROM patient_events e JOIN users u ON u.id=e.actor_id WHERE e.patient_id=? AND e.model_profile=? AND e.checkpoint IN ({marks}) ORDER BY e.id DESC LIMIT 201", (patient_id, model_profile, *checkpoints))] if checkpoints else []
        acknowledgements = [dict(row) for row in db.execute(f"SELECT e.*,u.display_name AS author FROM patient_events e JOIN users u ON u.id=e.actor_id WHERE e.id IN (SELECT MAX(id) FROM patient_events WHERE patient_id=? AND model_profile=? AND event_type='acknowledge' GROUP BY checkpoint) AND e.checkpoint IN ({marks})", (patient_id, model_profile, *checkpoints))] if checkpoints else []
    rules = json.loads(rule_versions[0]["rules_json"]) if rule_versions else []
    warnings = []
    for rule in rules:
        series = next(series for series in vitals if series["parameter"] == rule["parameter"])
        latest = series["measurements"][-1] if series["measurements"] else None
        # A rule introduced later cannot retroactively assess an earlier reading.
        state = "NO_READING_AFTER_RULE" if not latest or latest["time_minutes"] < rule_versions[0]["minute"] else (
            "OUTSIDE_ENTERED_LIMITS" if (rule["lower"] is not None and latest["value"] < rule["lower"]) or (rule["upper"] is not None and latest["value"] > rule["upper"]) else "WITHIN_ENTERED_LIMITS")
        warnings.append({**rule, "state": state, "latest": latest})
    return {"patient_id": patient_id, "as_of_minutes": as_of_minutes, "model_profile": model_profile,
            "source": "recorded_observations_and_staff_demo_entries", "vitals": vitals, "assignments": team,
            "context": contexts[0] if contexts else None, "context_history": contexts[:200], "entries": entries[:200],
            "rule_history": rule_versions[:200], "rules": rules, "vital_warnings": warnings,
            "review_events": reviews[:200], "acknowledgements": acknowledgements, "follow_ups": follow_ups, "review_requests": review_requests,
            "history_truncated": any(len(rows) > 200 for rows in (contexts, entries, rule_versions, reviews))}


@router.post("/patients/{patient_id}/clinical/context", status_code=201)
def save_context(patient_id: str, body: ContextBody, principal=Depends(require_write)):
    patient_access(principal, patient_id); known_patient(patient_id)
    store = get_auth_store()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE"); authorize(db, principal, patient_id, CONTEXT_ROLES)
        if body.physician_id is not None:
            doctor = db.execute("SELECT u.id FROM assignments a JOIN users u ON a.user_id=u.id WHERE a.patient_id=? AND u.id=? AND u.role='doctor' AND u.active=1", (patient_id, body.physician_id)).fetchone()
            if not doctor:
                raise HTTPException(422, "Choose an active doctor already assigned to this patient.")
        cursor = db.execute("INSERT INTO patient_contexts(patient_id,minute,diagnosis,admission_reason,condition_summary,admission_severity,specialty,physician_id,actor_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (patient_id, body.minute, body.diagnosis.strip(), body.admission_reason.strip(), body.condition_summary.strip(), body.admission_severity.strip(), body.specialty.strip(), body.physician_id, principal.user["id"], store.clock()))
    return {"id": cursor.lastrowid, "patient_id": patient_id}


@router.post("/patients/{patient_id}/clinical/entries/{entry_id}/follow-up", status_code=201)
def update_follow_up(patient_id: str, entry_id: int, body: FollowUpBody, principal=Depends(require_write)):
    patient_access(principal, patient_id); known_patient(patient_id)
    store = get_auth_store()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        authorize(db, principal, patient_id, {"doctor", "nurse", "coordinator"})
        entry = db.execute("SELECT * FROM clinical_entries WHERE id=? AND patient_id=?", (entry_id, patient_id)).fetchone()
        if not entry or entry["minute"] > body.as_of_minutes:
            raise HTTPException(404, "Follow-up not found in this recorded view.")
        if not (entry["follow_up"] or entry["review_minute"] is not None or entry["kind"] == "follow_up"):
            raise HTTPException(422, "This entry has no planned follow-up.")
        latest = db.execute("SELECT * FROM follow_up_events WHERE entry_id=? ORDER BY id DESC LIMIT 1", (entry_id,)).fetchone()
        if body.expected_event_id != (latest["id"] if latest else 0):
            raise HTTPException(409, "This follow-up changed. Refresh the latest recorded view before updating it.")
        if body.minute < max(entry["minute"], latest["minute"] if latest else 0):
            raise HTTPException(422, "Status time cannot precede the entry or its latest status change.")
        if body.status == (latest["status"] if latest else "pending"):
            raise HTTPException(409, "This follow-up already has that status.")
        cursor = db.execute("INSERT INTO follow_up_events(entry_id,minute,status,content,actor_id,actor_role,created_at) VALUES(?,?,?,?,?,?,?)", (entry_id, body.minute, body.status, body.content.strip(), principal.user["id"], principal.user["role"], store.clock()))
    return {"id": cursor.lastrowid, "patient_id": patient_id}


@router.post("/patients/{patient_id}/clinical/entries", status_code=201)
def add_entry(patient_id: str, body: ClinicalEntry, principal=Depends(require_write)):
    patient_access(principal, patient_id); known_patient(patient_id)
    store = get_auth_store()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE"); authorize(db, principal, patient_id, ENTRY_ROLES[body.kind])
        cursor = db.execute("INSERT INTO clinical_entries(patient_id,minute,kind,assessment,plan,follow_up,escalation,review_minute,actor_id,actor_role,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (patient_id, body.minute, body.kind, body.assessment.strip(), body.plan.strip(), body.follow_up.strip(), body.escalation.strip(), body.review_minute, principal.user["id"], principal.user["role"], store.clock()))
    return {"id": cursor.lastrowid, "patient_id": patient_id}


@router.post("/patients/{patient_id}/clinical/rules", status_code=201)
def save_rules(patient_id: str, body: RulesBody, principal=Depends(require_write)):
    patient_access(principal, patient_id); known_patient(patient_id)
    store = get_auth_store()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE"); authorize(db, principal, patient_id, {"doctor"})
        cursor = db.execute("INSERT INTO vital_rule_versions(patient_id,minute,rules_json,actor_id,created_at) VALUES(?,?,?,?,?)", (patient_id, body.minute, json.dumps([rule.model_dump() for rule in body.rules]), principal.user["id"], store.clock()))
    return {"id": cursor.lastrowid, "patient_id": patient_id}


class DoctorReviewBody(TimedBody):
    reason: str = Field(min_length=2, max_length=2000)
    context: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def meaningful_reason(self):
        if len(self.reason.strip()) < 2:
            raise ValueError("Explain why a doctor review is requested")
        return self


class DoctorReviewStatus(FollowUpBody):
    status: Literal["pending", "acknowledged", "resolved"]


@router.get("/review-requests/summary")
def review_summary(principal=Depends(require_patients)):
    with get_auth_store().db() as db:
        recheck_actor(db, principal, {"admin", "coordinator", "doctor", "nurse"})
        return notification_summary(db, principal)


@router.get("/review-requests")
def review_inbox(status: Literal["open", "pending", "acknowledged", "resolved", "all"] = "open",
                 offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100), as_of_minutes: int = Query(1440,ge=0,le=1440), principal=Depends(require_patients)):
    with get_auth_store().db() as db:
        recheck_actor(db, principal, {"admin", "coordinator", "doctor", "nurse"})
        return inbox(db, principal, status, offset, limit, as_of_minutes)


@router.post("/patients/{patient_id}/clinical/review-requests", status_code=201)
def request_doctor_review(patient_id: str, body: DoctorReviewBody, principal=Depends(require_write)):
    patient_access(principal, patient_id); known_patient(patient_id)
    store = get_auth_store()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        authorize(db, principal, patient_id, {"doctor", "nurse", "coordinator"})
        entry = db.execute("INSERT INTO clinical_entries(patient_id,minute,kind,assessment,plan,follow_up,escalation,review_minute,actor_id,actor_role,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (patient_id, body.minute, "escalation", body.reason.strip(), "", "", body.context.strip(), None, principal.user["id"], principal.user["role"], store.clock()))
        request = db.execute("INSERT INTO doctor_review_requests(entry_id) VALUES(?)", (entry.lastrowid,))
    return {"id": request.lastrowid, "patient_id": patient_id}


@router.post("/patients/{patient_id}/clinical/review-requests/{request_id}/status", status_code=201)
def update_doctor_review(patient_id: str, request_id: int, body: DoctorReviewStatus, principal=Depends(require_write)):
    patient_access(principal, patient_id); known_patient(patient_id)
    store = get_auth_store()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        authorize(db, principal, patient_id, {"doctor", "nurse", "coordinator"})
        entry = db.execute("SELECT e.* FROM doctor_review_requests r JOIN clinical_entries e ON e.id=r.entry_id WHERE r.id=? AND e.patient_id=?", (request_id, patient_id)).fetchone()
        if not entry or entry["minute"] > body.as_of_minutes:
            raise HTTPException(404, "Doctor review request not found in this recorded view.")
        latest = db.execute("SELECT * FROM doctor_review_events WHERE request_id=? ORDER BY id DESC LIMIT 1", (request_id,)).fetchone()
        if body.expected_event_id != (latest["id"] if latest else 0):
            raise HTTPException(409, "This request changed. Refresh before updating it.")
        if body.minute < max(entry["minute"], latest["minute"] if latest else 0):
            raise HTTPException(422, "Status time cannot precede the request or its latest change.")
        previous = latest["status"] if latest else "pending"
        if body.status == previous:
            raise HTTPException(409, "This request already has that status.")
        if body.status == "pending":
            if previous != "resolved":
                raise HTTPException(422, "Only resolved requests can be reopened.")
        else:
            if principal.user["role"] != "doctor" or not db.execute("SELECT 1 FROM assignments WHERE patient_id=? AND user_id=?", (patient_id, principal.user["id"])).fetchone():
                raise HTTPException(403, "Only an assigned doctor can acknowledge or resolve this request.")
            if (previous, body.status) not in {("pending", "acknowledged"), ("acknowledged", "resolved")}:
                raise HTTPException(422, "Acknowledge a pending request before resolving it.")
        cursor = db.execute("INSERT INTO doctor_review_events(request_id,minute,status,content,actor_id,actor_role,created_at) VALUES(?,?,?,?,?,?,?)",
            (request_id, body.minute, body.status, body.content.strip(), principal.user["id"], principal.user["role"], store.clock()))
    return {"id": cursor.lastrowid, "patient_id": patient_id}
