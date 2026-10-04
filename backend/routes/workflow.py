"""Scoped assignments and append-only review notes; model inputs are untouched."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from backend.auth import current_user, patient_access, require_patients, require_unit_write, require_write
from backend.permissions import EVENT_ROLES, UNIT_ROLES
from backend.routes.accounts import StrictBody
from backend.routes.patients import selected_service, ModelProfile
from backend.services.auth_service import get_auth_store
from backend.services.patient_service import PatientNotFoundError, PatientInferenceError

router = APIRouter(tags=["patient workflow"])


class AssignmentBody(StrictBody):
    user_ids: list[int] = Field(max_length=20)


class EventBody(StrictBody):
    model_profile: ModelProfile
    checkpoint: Literal["6h", "9h", "12h", "18h", "24h"]
    event_type: Literal["acknowledge", "review", "observation", "handover"]
    content: str = Field(min_length=2, max_length=2000)


def known_patient(patient_id):
    try:
        selected_service("original")._record_id(patient_id)
    except PatientNotFoundError:
        raise HTTPException(404, "Patient not found.") from None


def recheck_actor(db, principal, roles):
    row = db.execute("SELECT role,active FROM users WHERE id=?", (principal.user["id"],)).fetchone()
    if not row or not row["active"] or row["role"] not in roles or row["role"] != principal.user["role"]:
        raise HTTPException(403, "Your access changed. Sign in again.")
    if row["role"] not in UNIT_ROLES:
        return False
    return True


@router.get("/team/staff")
def staff(principal=Depends(current_user)):
    if principal.user["role"] not in UNIT_ROLES:
        raise HTTPException(403, "Unit management access is required.")
    with get_auth_store().db() as db:
        return [dict(row) for row in db.execute("SELECT id,username,display_name,role FROM users WHERE active=1 AND role IN ('doctor','nurse') ORDER BY display_name,username")]


@router.get("/patients/{patient_id}/workflow")
def workflow(patient_id: str, model_profile: ModelProfile = "original",
             as_of_minutes: int = Query(1440, ge=0, le=1440), principal=Depends(require_patients)):
    patient_access(principal, patient_id)
    known_patient(patient_id)
    service = selected_service(model_profile)
    visible = [cp for cp, cutoff in service.cutoffs.items() if cutoff <= as_of_minutes]
    with get_auth_store().db() as db:
        assigned = assigned_team(db, patient_id)
        placeholders = ",".join("?" for _ in visible)
        events = [dict(row) for row in db.execute(f"SELECT e.id,e.model_profile,e.checkpoint,e.event_type,e.content,e.actor_role,e.risk_score,e.alert_state,e.created_at,u.display_name AS author FROM patient_events e JOIN users u ON u.id=e.actor_id WHERE e.patient_id=? AND e.model_profile=? AND e.checkpoint IN ({placeholders}) ORDER BY e.id DESC LIMIT 200", (patient_id, model_profile, *visible))] if visible else []
    return {"patient_id": patient_id, "assignments": assigned, "events": events}


def assigned_team(db, patient_id):
    return [dict(row) for row in db.execute("SELECT u.id,u.username,u.display_name,u.role,u.active FROM assignments a JOIN users u ON u.id=a.user_id WHERE a.patient_id=? AND u.role IN ('doctor','nurse') ORDER BY u.display_name,u.username", (patient_id,))]


@router.patch('/patients/{patient_id}/assignments/{role}')
def assign_role(patient_id: str, role: Literal['doctor', 'nurse'], body: AssignmentBody, principal=Depends(require_unit_write)):
    known_patient(patient_id)
    ids = sorted(set(body.user_ids))
    store = get_auth_store()
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        recheck_actor(db, principal, UNIT_ROLES)
        for user_id in ids:
            row = db.execute('SELECT role,active FROM users WHERE id=?', (user_id,)).fetchone()
            if not row or not row['active'] or row['role'] != role:
                raise HTTPException(422, f'Choose only active {role} accounts. Refresh the team if an account changed.')
        # Replace this role only, under the same transaction used for validation.
        db.execute('DELETE FROM assignments WHERE patient_id=? AND user_id IN (SELECT id FROM users WHERE role=?)', (patient_id, role))
        for user_id in ids:
            db.execute('INSERT INTO assignments VALUES(?,?,?,?)', (patient_id, user_id, principal.user['id'], store.clock()))
        store._event(db, principal.user['id'], None, 'assign_' + role)
        team = assigned_team(db, patient_id)
    return {'patient_id': patient_id, 'assignments': team}


@router.put("/patients/{patient_id}/assignments")
def assign(patient_id: str, body: AssignmentBody, principal=Depends(require_unit_write)):
    known_patient(patient_id)
    ids = sorted(set(body.user_ids))
    store = get_auth_store()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        recheck_actor(db, principal, UNIT_ROLES)
        for user_id in ids:
            row = db.execute("SELECT role,active FROM users WHERE id=?", (user_id,)).fetchone()
            if not row or not row["active"] or row["role"] not in {"doctor", "nurse"}:
                raise HTTPException(422, "Assign only active doctor or nurse accounts.")
        db.execute("DELETE FROM assignments WHERE patient_id=?", (patient_id,))
        for user_id in ids:
            db.execute("INSERT INTO assignments VALUES(?,?,?,?)", (patient_id, user_id, principal.user["id"], store.clock()))
        store._event(db, principal.user["id"], None, "assign_patient")
    return {"patient_id": patient_id, "user_ids": ids}


@router.post("/patients/{patient_id}/events", status_code=201)
def event(patient_id: str, body: EventBody, principal=Depends(require_write)):
    allowed_roles = EVENT_ROLES[body.event_type]
    if principal.user["role"] not in allowed_roles:
        raise HTTPException(403, "This action is not allowed for your role.")
    patient_access(principal, patient_id)
    content = body.content.strip()
    if len(content) < 2:
        raise HTTPException(422, "Enter a note with at least two characters.")
    service = selected_service(body.model_profile)
    if body.checkpoint not in service.cutoffs:
        raise HTTPException(422, "This checkpoint is not supported by the selected model.")
    try:
        detail = service.get_patient_detail(patient_id, as_of_minutes=service.cutoffs[body.checkpoint])
    except PatientNotFoundError:
        raise HTTPException(404, "Patient not found.") from None
    except PatientInferenceError:
        raise HTTPException(503, "Assessment could not be loaded.") from None
    point = next(point for point in detail.risk_trajectory if point.checkpoint == body.checkpoint)
    if point.assessment_status != "READY":
        raise HTTPException(409, "There is no available assessment at this checkpoint.")
    if body.event_type == "acknowledge" and point.alert_state == "NO_ALERT":
        raise HTTPException(409, "There is no warning to acknowledge at this checkpoint.")
    store = get_auth_store()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        is_unit = recheck_actor(db, principal, allowed_roles)
        if not is_unit and not db.execute("SELECT 1 FROM assignments WHERE patient_id=? AND user_id=?", (patient_id, principal.user["id"])).fetchone():
            raise HTTPException(403, "This patient is no longer assigned to you.")
        cursor = db.execute("INSERT INTO patient_events(patient_id,model_profile,checkpoint,event_type,content,actor_id,actor_role,risk_score,alert_state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (patient_id, body.model_profile, body.checkpoint, body.event_type, content, principal.user["id"], principal.user["role"], point.risk_probability, point.alert_state, store.clock()))
    return {"id": cursor.lastrowid, "patient_id": patient_id}
