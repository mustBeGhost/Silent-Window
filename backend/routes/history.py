"""Paginated staff history search at the selected recorded cutoff."""
from typing import Literal
from fastapi import APIRouter, Depends, Query, HTTPException
from backend.auth import require_patients, patient_access
from backend.routes.clinical import authorize
from backend.routes.workflow import known_patient
from backend.services.auth_service import get_auth_store
router = APIRouter(tags=['patient history'])
KINDS = Literal['all','visit','assessment','recommendation','follow_up','handover','escalation','context','follow_up_status','doctor_review_status','model_review','vital_limits','shift_handover','doctor_review_request']

@router.get('/patients/{patient_id}/history')
def history(patient_id: str, as_of_minutes: int=Query(1440,ge=0,le=1440), search: str=Query('',max_length=100),
            kind: KINDS='all', author_id: int|None=Query(None,gt=0), minute_from: int=Query(0,ge=0,le=1440),
            saved_after: float|None=Query(None,ge=0,allow_inf_nan=False), saved_before: float|None=Query(None,ge=0,allow_inf_nan=False),
            offset: int=Query(0,ge=0), limit: int=Query(25,ge=1,le=100), principal=Depends(require_patients)):
    patient_access(principal,patient_id); known_patient(patient_id)
    if minute_from > as_of_minutes:
        raise HTTPException(422,'The first recorded minute must not be after the selected view.')
    if saved_after is not None and saved_before is not None and saved_after > saved_before:
        raise HTTPException(422,'Saved after must not be later than Saved before.')
    queries = [
      "SELECT 'entry' AS source,id,patient_id,minute,CASE WHEN EXISTS(SELECT 1 FROM doctor_review_requests r WHERE r.entry_id=clinical_entries.id) THEN 'doctor_review_request' ELSE kind END AS kind,assessment AS content,plan,follow_up,escalation,actor_id,created_at FROM clinical_entries",
      "SELECT 'context',id,patient_id,minute,'context',condition_summary,admission_reason,diagnosis,specialty,actor_id,created_at FROM patient_contexts",
      "SELECT 'limits',id,patient_id,minute,'vital_limits',rules_json,'','','',actor_id,created_at FROM vital_rule_versions",
      "SELECT 'model',id,patient_id,CAST(REPLACE(checkpoint,'h','') AS INTEGER)*60,'model_review',content,model_profile,checkpoint,event_type,actor_id,created_at FROM patient_events",
      "SELECT 'follow',f.id,e.patient_id,f.minute,'follow_up_status',f.content,f.status,'','',f.actor_id,f.created_at FROM follow_up_events f JOIN clinical_entries e ON e.id=f.entry_id WHERE e.minute<=?",
      "SELECT 'review',f.id,e.patient_id,f.minute,'doctor_review_status',f.content,f.status,'','',f.actor_id,f.created_at FROM doctor_review_events f JOIN doctor_review_requests r ON r.id=f.request_id JOIN clinical_entries e ON e.id=r.entry_id WHERE e.minute<=?",
      "SELECT 'offer',id,patient_id,minute,'shift_handover',summary,staff_role,'','',actor_id,created_at FROM handovers",
      "SELECT 'handover',s.id,h.patient_id,s.minute,'shift_handover',s.content,s.status,'','',s.actor_id,s.created_at FROM handover_events s JOIN handovers h ON h.id=s.handover_id WHERE h.minute<=?"
    ]
    # MySQL spells the integer conversion SIGNED; SQL text remains application-owned.
    with get_auth_store().db() as db:
        authorize(db,principal,patient_id,{'admin','coordinator','doctor','nurse'})
        if db.connection.dialect.name == 'mysql':
            queries[3] = queries[3].replace('AS INTEGER','AS SIGNED')
        sql=' FROM ('+' UNION ALL '.join(queries)+') h JOIN users u ON u.id=h.actor_id WHERE h.patient_id=? AND h.minute>=? AND h.minute<=?'
        values=(as_of_minutes,as_of_minutes,as_of_minutes,patient_id,minute_from,as_of_minutes)
        authors=[dict(row) for row in db.execute('SELECT DISTINCT u.id,u.display_name'+sql+' ORDER BY u.display_name,u.id', values)]
        if kind!='all': sql+=' AND h.kind=?';values+=(kind,)
        if author_id is not None: sql+=' AND h.actor_id=?';values+=(author_id,)
        if saved_after is not None: sql+=' AND h.created_at>=?';values+=(saved_after,)
        if saved_before is not None: sql+=' AND h.created_at<=?';values+=(saved_before,)
        if search.strip():
            pattern='%'+search.strip().lower().replace('!','!!').replace('%','!%').replace('_','!_')+'%'
            sql+=" AND (LOWER(h.content) LIKE ? ESCAPE '!' OR LOWER(h.plan) LIKE ? ESCAPE '!' OR LOWER(h.follow_up) LIKE ? ESCAPE '!' OR LOWER(h.escalation) LIKE ? ESCAPE '!' OR LOWER(u.display_name) LIKE ? ESCAPE '!')";values+=(pattern,)*5
        total=db.execute('SELECT COUNT(*) AS total'+sql,values).fetchone()['total']
        items=[dict(r) for r in db.execute('SELECT h.*,u.display_name AS author'+sql+' ORDER BY h.minute DESC,h.created_at DESC,h.source,h.id DESC LIMIT ? OFFSET ?',(*values,limit,offset))]
    return {'items':items,'total':total,'offset':offset,'limit':limit,'as_of_minutes':as_of_minutes,'authors':authors}
