"""Explicit doctor-review requests. Legacy escalation notes are not notifications."""
from backend.permissions import UNIT_ROLES
from backend.services.shift_workflow import availability

DOCTOR_COUNT = """(SELECT COUNT(*) FROM assignments a JOIN users d ON d.id=a.user_id
    WHERE a.patient_id=e.patient_id AND d.role='doctor' AND d.active=1)"""
FIELDS = """r.id AS request_id,e.id AS entry_id,e.patient_id,e.minute,e.assessment AS reason,
    e.escalation AS context,e.created_at,author.display_name AS author,e.actor_role,
    COALESCE(s.status,'pending') AS status,COALESCE(s.id,0) AS event_id,
    s.minute AS status_minute,s.created_at AS status_saved_at,s.content AS status_note,
    actor.display_name AS status_author,s.actor_role AS status_role,""" + DOCTOR_COUNT + " AS assigned_doctor_count "


def source(minute, patient_id=None, principal=None):
    sql = """FROM doctor_review_requests r JOIN clinical_entries e ON e.id=r.entry_id
        JOIN users author ON author.id=e.actor_id
        LEFT JOIN doctor_review_events s ON s.id=(SELECT MAX(s2.id) FROM doctor_review_events s2 WHERE s2.request_id=r.id AND s2.minute<=?)
        LEFT JOIN users actor ON actor.id=s.actor_id WHERE e.minute<=?"""
    values = [minute, minute]
    if patient_id is not None:
        sql += " AND e.patient_id=?"; values.append(patient_id)
    if principal and principal.user["role"] not in UNIT_ROLES:
        sql += " AND EXISTS(SELECT 1 FROM assignments a WHERE a.patient_id=e.patient_id AND a.user_id=?)"
        values.append(principal.user["id"])
    return sql, tuple(values)


def summary(db, sql, values):
    counts = {"pending": 0, "acknowledged": 0, "resolved": 0}
    for row in db.execute("SELECT COALESCE(s.status,'pending') AS status,COUNT(*) AS total " + sql + " GROUP BY COALESCE(s.status,'pending')", values):
        counts[row["status"]] = row["total"]
    counts["unassigned"] = db.execute("SELECT COUNT(*) AS total " + sql + " AND COALESCE(s.status,'pending')<>'resolved' AND " + DOCTOR_COUNT + "=0", values).fetchone()["total"]
    return counts


def patient_reviews(db, patient_id, minute):
    sql, values = source(minute, patient_id=patient_id)
    items = [dict(row) for row in db.execute("SELECT " + FIELDS + sql + " ORDER BY CASE COALESCE(s.status,'pending') WHEN 'pending' THEN 0 WHEN 'acknowledged' THEN 1 ELSE 2 END,r.id DESC LIMIT 201", values)]
    history = [dict(row) for row in db.execute("""SELECT s.*,u.display_name AS author FROM doctor_review_events s
        JOIN doctor_review_requests r ON r.id=s.request_id JOIN clinical_entries e ON e.id=r.entry_id
        JOIN users u ON u.id=s.actor_id WHERE e.patient_id=? AND e.minute<=? AND s.minute<=?
        ORDER BY s.id DESC LIMIT 201""", (patient_id, minute, minute))]
    return {"items": items[:200], "counts": summary(db, sql, values), "history": history[:200], "truncated": len(items) > 200 or len(history) > 200}


def inbox(db, principal, status, offset, limit, minute=1440):
    sql, values = source(minute, principal=principal)
    counts = summary(db, sql, values)
    condition = ""
    if status == "open": condition = " AND COALESCE(s.status,'pending')<>'resolved'"
    elif status != "all":
        condition = " AND COALESCE(s.status,'pending')=?"; values += (status,)
    total = db.execute("SELECT COUNT(*) AS total " + sql + condition, values).fetchone()["total"]
    items = [dict(row) for row in db.execute("SELECT " + FIELDS + sql + condition + " ORDER BY r.id DESC LIMIT ? OFFSET ?", (*values, limit, offset))]
    return {"items": items, "total": total, "offset": offset, "limit": limit, "counts": counts}


def notification_summary(db, principal):
    sql, values = source(1440, principal=principal)
    counts = summary(db, sql, values)
    # Only doctors receive a popup. Unit managers can see unassigned requests in
    # the inbox; assignment changes make pending requests visible to new doctors.
    rows = list(db.execute("SELECT r.id,COALESCE(s.id,0) AS event_id " + sql + " AND COALESCE(s.status,'pending')='pending' ORDER BY r.id DESC LIMIT 100", values)) if principal.user["role"] == "doctor" and availability(db, principal.user["id"])["status"] not in {"off_duty", "unavailable"} else []
    return {"open_count": counts["pending"] + counts["acknowledged"],
            "pending_ids": [row["id"] for row in rows],
            "pending_keys": [f"{row['id']}:{row['event_id']}" for row in rows]}
