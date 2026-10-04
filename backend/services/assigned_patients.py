"""Filter to assigned records before scoring, filtering and pagination."""
import math
from backend.schemas.patient import AssessmentCounts, PatientPage
from backend.services.auth_service import get_auth_store


def assigned_ids(user_id):
    with get_auth_store().db() as db:
        return [row[0] for row in db.execute("SELECT patient_id FROM assignments WHERE user_id=?", (user_id,))]


def assigned_page(service, user_id, *, page, page_size, search, risk, alert, scope, sort_order):
    ids = sorted(assigned_ids(user_id), key=service._public_id_number, reverse=sort_order == "desc")
    matching = [pid for pid in ids if (search or "").strip().upper() in pid]
    counts = None
    if scope == "all":
        summaries = service._get_patient_summaries(ids)
        counts = AssessmentCounts(high_risk=sum(s.risk_level == "HIGH" for s in summaries),
                                  watch=sum(s.alert_state == "WATCH" for s in summaries),
                                  no_alert=sum(s.alert_state == "NO_ALERT" for s in summaries),
                                  not_assessed=sum(s.assessment_status != "READY" for s in summaries))
        summaries = [s for s in summaries if s.patient_id in matching and (not risk or s.risk_level == risk) and (not alert or s.alert_state == alert)]
        total = len(summaries)
        items = summaries[(page - 1) * page_size:page * page_size]
    else:
        # Page-scoped filters are applied in the existing frontend, preserving its semantics.
        total = len(matching)
        items = service._get_patient_summaries(matching[(page - 1) * page_size:page * page_size])
    return PatientPage(items=items, page=page, page_size=page_size, total=total,
                       total_pages=math.ceil(total / page_size), cohort_total=len(ids),
                       cached_assessments=sum(pid in service._summary_cache for pid in ids),
                       result_scope="complete_assessment_index" if scope == "all" else "cohort", assessment_counts=counts)
