"""Assigned work, availability and handover views; no model inputs are modified."""
import json
from backend.permissions import UNIT_ROLES


def availability(db, user_id):
    row = db.execute("SELECT id,status,note,created_at FROM availability_events WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    return dict(row) if row else {"id": 0, "status": "not_set", "note": "", "created_at": None}


def scope(principal, alias="e"):
    if principal.user["role"] in UNIT_ROLES:
        return "", ()
    return f" AND EXISTS(SELECT 1 FROM assignments a WHERE a.patient_id={alias}.patient_id AND a.user_id=?)", (principal.user["id"],)


def tasks(db, principal, minute, limit=100):
    restricted, values = scope(principal)
    source = """FROM clinical_entries e JOIN users u ON u.id=e.actor_id
      LEFT JOIN follow_up_events f ON f.id=(SELECT MAX(f2.id) FROM follow_up_events f2 WHERE f2.entry_id=e.id AND f2.minute<=?)
      WHERE e.minute<=? AND (e.follow_up<>'' OR e.review_minute IS NOT NULL OR e.kind='follow_up')""" + restricted
    values = (minute, minute, *values)
    counts = {"pending": 0, "completed": 0, "due": 0, "overdue": 0}
    for row in db.execute("SELECT COALESCE(f.status,'pending') AS status,COUNT(*) AS total " + source + " GROUP BY COALESCE(f.status,'pending')", values):
        counts[row["status"]] = row["total"]
    for name, operator in (("due", "<="), ("overdue", "<")):
        counts[name] = db.execute("SELECT COUNT(*) AS total " + source + " AND COALESCE(f.status,'pending')='pending' AND e.review_minute" + operator + "?", (*values, minute)).fetchone()["total"]
    items = [dict(row) for row in db.execute("""SELECT e.id,e.patient_id,e.minute,e.assessment,e.follow_up,e.review_minute,u.display_name AS author,
      COALESCE(f.id,0) AS event_id """ + source + " AND COALESCE(f.status,'pending')='pending' ORDER BY CASE WHEN e.review_minute IS NULL THEN 1 ELSE 0 END,e.review_minute,e.id LIMIT ?", (*values, limit))]
    return {"items": items, "counts": counts, "truncated": counts["pending"] > len(items)}


HANDOVER_SOURCE = """FROM handovers h JOIN users sender ON sender.id=h.from_id JOIN users recipient ON recipient.id=h.to_id
 LEFT JOIN handover_events s ON s.id=(SELECT MAX(s2.id) FROM handover_events s2 WHERE s2.handover_id=h.id AND s2.minute<=?)
 LEFT JOIN users actor ON actor.id=s.actor_id WHERE h.minute<=?"""
HANDOVER_FIELDS = """h.*,sender.display_name AS sender,recipient.display_name AS recipient,
 COALESCE(s.status,'pending') AS status,COALESCE(s.id,0) AS event_id,s.minute AS status_minute,
 s.content AS status_note,s.created_at AS status_saved_at,actor.display_name AS status_author """


def handover_page(db, principal, minute, status="pending", offset=0, limit=25, patient_id=None):
    source, values = HANDOVER_SOURCE, (minute, minute)
    if principal.user["role"] not in UNIT_ROLES:
        source += " AND (h.from_id=? OR h.to_id=?)"; values += (principal.user["id"], principal.user["id"])
    if patient_id is not None:
        source += " AND h.patient_id=?"; values += (patient_id,)
    if status != "all":
        source += " AND COALESCE(s.status,'pending')=?"; values += (status,)
    total = db.execute("SELECT COUNT(*) AS total " + source, values).fetchone()["total"]
    rows = [dict(row) for row in db.execute("SELECT " + HANDOVER_FIELDS + source + " ORDER BY h.id DESC LIMIT ? OFFSET ?", (*values, limit, offset))]
    for row in rows:
        row["tasks"] = json.loads(row.pop("tasks_json"))
    return {"items": rows, "total": total, "offset": offset, "limit": limit}
