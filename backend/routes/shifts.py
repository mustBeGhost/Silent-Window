"""Staff shift workflow with explicit receiving-person confirmation."""
import json
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, model_validator
from backend.auth import require_patients, require_write, patient_access
from backend.routes.accounts import StrictBody
from backend.routes.clinical import TimedBody, authorize, clinical
from backend.routes.workflow import known_patient, recheck_actor
from backend.routes.patients import ModelProfile, selected_service
from backend.services.auth_service import get_auth_store
from backend.services.shift_workflow import availability, tasks, handover_page
from backend.services.follow_ups import follow_up_snapshot
from backend.permissions import UNIT_ROLES
from backend.services.patient_service import PatientInferenceError

router = APIRouter(tags=["shift workflow"])
STAFF = {"doctor", "nurse", "coordinator"}

class AvailabilityBody(StrictBody):
    status: Literal["on_duty", "off_duty", "unavailable"]
    expected_event_id: int = Field(ge=0, strict=True)
    note: str = Field(default="", max_length=300)

class HandoverBody(TimedBody):
    from_id: int = Field(gt=0, strict=True)
    to_id: int = Field(gt=0, strict=True)
    summary: str = Field(min_length=2, max_length=2000)

    @model_validator(mode="after")
    def summary_text(self):
        if len(self.summary.strip()) < 2 or self.from_id == self.to_id:
            raise ValueError("Choose a different receiving staff member and explain the handover")
        return self

class HandoverAction(TimedBody):
    status: Literal["accepted", "declined", "cancelled"]
    expected_event_id: int = Field(ge=0, strict=True)
    content: str = Field(min_length=2, max_length=2000)

    @model_validator(mode="after")
    def note_text(self):
        if len(self.content.strip()) < 2:
            raise ValueError("Explain this handover action")
        return self

@router.get("/staff/availability")
def staff_availability(principal=Depends(require_patients)):
    with get_auth_store().db() as db:
        recheck_actor(db, principal, {*STAFF, "admin"})
        people = [dict(row) for row in db.execute("SELECT id,display_name,username,role FROM users WHERE active=1 AND role IN ('doctor','nurse','coordinator') ORDER BY display_name,id")]
        for person in people:
            person["availability"] = availability(db, person["id"])
    return people

@router.post("/staff/availability", status_code=201)
def set_availability(body: AvailabilityBody, principal=Depends(require_write)):
    store = get_auth_store()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE"); recheck_actor(db, principal, STAFF)
        old = availability(db, principal.user["id"])
        if old["id"] != body.expected_event_id:
            raise HTTPException(409, "Your availability changed. Refresh before saving.")
        cursor = db.execute("INSERT INTO availability_events(user_id,status,note,actor_id,created_at) VALUES(?,?,?,?,?)", (principal.user["id"], body.status, body.note.strip(), principal.user["id"], store.clock()))
    return {"id": cursor.lastrowid}

@router.get("/shift")
def my_shift(as_of_minutes: int = Query(1440, ge=0, le=1440), page: int = Query(1, ge=1), principal=Depends(require_patients)):
    store = get_auth_store()
    with store.db() as db:
        recheck_actor(db, principal, {*STAFF, "admin"})
        if principal.user["role"] in UNIT_ROLES:
            ids = sorted(selected_service("original")._opaque_to_record, key=lambda value: int(value.split('-')[1]))
        else:
            ids = [r["patient_id"] for r in db.execute("SELECT patient_id FROM assignments WHERE user_id=? ORDER BY patient_id", (principal.user["id"],))]
        coverage=[]
        for patient_id in ids[(page-1)*25:page*25]:
            members=[dict(row) for row in db.execute("SELECT u.id,u.display_name,u.role FROM assignments a JOIN users u ON u.id=a.user_id WHERE a.patient_id=? AND u.active=1 AND u.role IN ('doctor','nurse')",(patient_id,))]
            for member in members:member['availability']=availability(db,member['id'])['status']
            coverage.append({'patient_id':patient_id,'members':members})
        return {"as_of_minutes": as_of_minutes, "coverage":coverage, "availability": availability(db, principal.user["id"]),
            "patient_ids": ids[(page-1)*25:page*25], "patient_total": len(ids), "page": page,
            "tasks": tasks(db, principal, as_of_minutes), "handovers": handover_page(db, principal, as_of_minutes),
            "scope": "unit" if principal.user["role"] in UNIT_ROLES else "assigned"}

@router.get("/handovers")
def list_handovers(as_of_minutes: int = Query(1440, ge=0, le=1440), status: Literal["pending", "accepted", "declined", "cancelled", "all"] = "pending", offset: int = Query(0, ge=0), patient_id: str|None=Query(None,max_length=32), principal=Depends(require_patients)):
    with get_auth_store().db() as db:
        recheck_actor(db, principal, {*STAFF, "admin"})
        return handover_page(db, principal, as_of_minutes, status, offset, patient_id=patient_id)

@router.post("/patients/{patient_id}/handovers", status_code=201)
def offer_handover(patient_id: str, body: HandoverBody, principal=Depends(require_write)):
    patient_access(principal, patient_id); known_patient(patient_id)
    store = get_auth_store()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE"); authorize(db, principal, patient_id, STAFF)
        sender = db.execute("SELECT role,active FROM users WHERE id=?", (body.from_id,)).fetchone()
        recipient = db.execute("SELECT role,active FROM users WHERE id=?", (body.to_id,)).fetchone()
        if not sender or not recipient or not sender["active"] or not recipient["active"] or sender["role"] not in {"doctor", "nurse"} or sender["role"] != recipient["role"]:
            raise HTTPException(422, "Choose active staff in the same doctor or nurse role.")
        if principal.user["role"] != "coordinator" and principal.user["id"] != body.from_id:
            raise HTTPException(403, "You can hand over only your own assignment.")
        if not db.execute("SELECT 1 FROM assignments WHERE patient_id=? AND user_id=?", (patient_id, body.from_id)).fetchone():
            raise HTTPException(409, "The sending staff member is no longer assigned.")
        if db.execute("SELECT 1 FROM assignments WHERE patient_id=? AND user_id=?", (patient_id, body.to_id)).fetchone():
            raise HTTPException(409, "The receiving staff member is already assigned.")
        if db.execute("SELECT 1 FROM handovers h WHERE h.patient_id=? AND h.from_id=? AND NOT EXISTS(SELECT 1 FROM handover_events s WHERE s.handover_id=h.id)", (patient_id, body.from_id)).fetchone():
            raise HTTPException(409, "A handover is already pending for this assignment.")
        pending = follow_up_snapshot(db, patient_id, body.minute)
        snapshot = {"items": [{"entry_id": t["entry_id"], "action": t["follow_up"] or t["assessment"], "review_minute": t["review_minute"]} for t in pending["items"] if t["status"] == "pending"], "count": pending["counts"]["pending"], "truncated": pending["truncated"]}
        cursor = db.execute("INSERT INTO handovers(patient_id,minute,from_id,to_id,actor_id,staff_role,summary,tasks_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (patient_id, body.minute, body.from_id, body.to_id, principal.user["id"], sender["role"], body.summary.strip(), json.dumps(snapshot), store.clock()))
    return {"id": cursor.lastrowid}

@router.post("/handovers/{handover_id}/status", status_code=201)
def act_handover(handover_id: int, body: HandoverAction, principal=Depends(require_write)):
    store = get_auth_store()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE"); recheck_actor(db, principal, STAFF)
        h = db.execute("SELECT * FROM handovers WHERE id=?", (handover_id,)).fetchone()
        if not h or h["minute"] > body.as_of_minutes or (principal.user["id"] not in {h["from_id"], h["to_id"]} and principal.user["role"] != "coordinator"):
            raise HTTPException(404, "Handover not found in this recorded view.")
        latest = db.execute("SELECT id FROM handover_events WHERE handover_id=? ORDER BY id DESC LIMIT 1", (handover_id,)).fetchone()
        if body.expected_event_id != (latest["id"] if latest else 0) or latest:
            raise HTTPException(409, "This handover already changed. Refresh the page.")
        if body.minute < h["minute"]:
            raise HTTPException(422, "Action time cannot precede the handover.")
        if body.status == "cancelled":
            if principal.user["id"] != h["from_id"] and principal.user["role"] != "coordinator":
                raise HTTPException(403, "Only the sender or a coordinator can cancel this handover.")
        elif principal.user["id"] != h["to_id"]:
            raise HTTPException(403, "Only the receiving staff member can accept or decline.")
        if body.status == "accepted":
            sender = db.execute("SELECT role,active FROM users WHERE id=?", (h["from_id"],)).fetchone()
            if not sender or not sender["active"] or sender["role"] != h["staff_role"] or principal.user["role"] != h["staff_role"]:
                raise HTTPException(409, "A staff role or account changed. Ask the coordinator to reassign.")
            if availability(db, h["to_id"])["status"] != "on_duty":
                raise HTTPException(409, "Set your availability to On duty before accepting.")
            if not db.execute("SELECT 1 FROM assignments WHERE patient_id=? AND user_id=?", (h["patient_id"], h["from_id"])).fetchone():
                raise HTTPException(409, "The sending assignment changed. Ask the coordinator to review it.")
            if db.execute("SELECT 1 FROM assignments WHERE patient_id=? AND user_id=?", (h["patient_id"], h["to_id"])).fetchone():
                raise HTTPException(409, "You are already assigned. Cancel this handover instead.")
            db.execute("DELETE FROM assignments WHERE patient_id=? AND user_id=?", (h["patient_id"], h["from_id"]))
            db.execute("INSERT INTO assignments VALUES(?,?,?,?)", (h["patient_id"], h["to_id"], principal.user["id"], store.clock()))
            store._event(db, principal.user["id"], h["from_id"], "accept_handover")
        cursor = db.execute("INSERT INTO handover_events(handover_id,status,minute,content,actor_id,created_at) VALUES(?,?,?,?,?,?)", (handover_id, body.status, body.minute, body.content.strip(), principal.user["id"], store.clock()))
    return {"id": cursor.lastrowid}


@router.get('/shift/warnings')
def shift_warnings(as_of_minutes: int=Query(1440,ge=0,le=1440), page:int=Query(1,ge=1), model_profile:ModelProfile='original', principal=Depends(require_patients)):
    ids=my_shift(as_of_minutes,page,principal)['patient_ids']
    items=[]
    for patient_id in ids:
        try:
            data=clinical(patient_id,as_of_minutes,model_profile,principal)
            detail=selected_service(model_profile).get_patient_detail(patient_id,as_of_minutes=as_of_minutes)
            ack={a['checkpoint'] for a in data['acknowledgements']}
            alerts=[{'checkpoint':p.checkpoint,'state':p.alert_state} for p in detail.risk_trajectory if p.assessment_status=='READY' and p.alert_state!='NO_ALERT' and p.checkpoint not in ack]
            vitals=[v['parameter'] for v in data['vital_warnings'] if v['state']=='OUTSIDE_ENTERED_LIMITS']
            items.append({'patient_id':patient_id,'model_alerts':alerts,'vital_warnings':vitals,'assessed':any(p.assessment_status=='READY' for p in detail.risk_trajectory)})
        except PatientInferenceError:
            items.append({'patient_id':patient_id,'unavailable':True})
    return {'items':items,'scope':'loaded_page','as_of_minutes':as_of_minutes,'model_profile':model_profile}
