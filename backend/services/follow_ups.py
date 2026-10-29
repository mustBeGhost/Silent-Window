"""Follow-up state at a recorded cutoff, independent of model alert state."""

def follow_up_snapshot(db, patient_id, minute):
    # Pick the latest visible transition for each entry. Future completions never
    # hide a pending action during an earlier recorded view.
    source = """FROM clinical_entries e JOIN users author ON author.id=e.actor_id
        LEFT JOIN follow_up_events f ON f.id=(SELECT MAX(f2.id) FROM follow_up_events f2
            WHERE f2.entry_id=e.id AND f2.minute<=?)
        LEFT JOIN users actor ON actor.id=f.actor_id
        WHERE e.patient_id=? AND e.minute<=?
        AND (e.follow_up<>'' OR e.review_minute IS NOT NULL OR e.kind='follow_up')"""
    values = (minute, patient_id, minute)
    counts = {"pending": 0, "completed": 0, "overdue": 0}
    for row in db.execute("SELECT COALESCE(f.status,'pending') AS status,COUNT(*) AS total " + source + " GROUP BY COALESCE(f.status,'pending')", values):
        counts[row["status"]] = row["total"]
    counts["overdue"] = db.execute("SELECT COUNT(*) AS total " + source + " AND COALESCE(f.status,'pending')='pending' AND e.review_minute<?", (*values, minute)).fetchone()["total"]
    items = [dict(row) for row in db.execute("""SELECT e.id AS entry_id,e.minute,e.kind,e.assessment,e.follow_up,
        e.review_minute,author.display_name AS author,COALESCE(f.status,'pending') AS status,
        COALESCE(f.id,0) AS event_id,f.minute AS status_minute,f.created_at AS status_saved_at,
        actor.display_name AS status_author,f.actor_role AS status_role,f.content AS status_note """ + source + """
        ORDER BY CASE WHEN COALESCE(f.status,'pending')='pending' THEN 0 ELSE 1 END,
        CASE WHEN e.review_minute IS NULL THEN 1 ELSE 0 END,e.review_minute,e.id DESC LIMIT 201""", values)]
    history = [dict(row) for row in db.execute("""SELECT f.*,u.display_name AS author FROM follow_up_events f
        JOIN clinical_entries e ON e.id=f.entry_id JOIN users u ON u.id=f.actor_id
        WHERE e.patient_id=? AND e.minute<=? AND f.minute<=? ORDER BY f.id DESC LIMIT 201""", (patient_id, minute, minute))]
    return {"items": items[:200], "counts": counts, "history": history[:200], "truncated": len(items) > 200 or len(history) > 200}
