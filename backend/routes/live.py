"""Authenticated, scoped invalidation stream. Events contain no patient content."""
import asyncio
import hashlib
import json
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from backend.auth import require_patients, trusted_origin
from backend.services.auth_service import get_auth_store, AuthError, COOKIE_NAME
from backend.permissions import UNIT_ROLES
from backend.services.shift_workflow import scope

router = APIRouter(tags=["live workspace updates"])

def workspace_revision(principal):
    with get_auth_store().db() as db:
        parts = []
        restricted, values = scope(principal)
        for name in ('clinical_entries','patient_contexts','vital_rule_versions','patient_events'):
            parts.append(tuple(db.execute(f"SELECT COUNT(*) AS n,MAX(e.id) AS last_id FROM {name} e WHERE 1=1" + restricted, values).fetchone().values()))
        for name, link in (('follow_up_events','f.entry_id=e.id'),('doctor_review_events','f.request_id IN (SELECT r.id FROM doctor_review_requests r WHERE r.entry_id=e.id)')):
            parts.append(tuple(db.execute(f"SELECT COUNT(*) AS n,MAX(f.id) AS last_id FROM {name} f JOIN clinical_entries e ON {link} WHERE 1=1" + restricted, values).fetchone().values()))
        assignment_scope = '' if principal.user['role'] in UNIT_ROLES else ' WHERE user_id=?'
        parts.append([tuple(row.values()) for row in db.execute('SELECT patient_id,user_id,created_at FROM assignments' + assignment_scope + ' ORDER BY patient_id,user_id', () if not assignment_scope else (principal.user['id'],))])
        for name in ('handovers', 'handover_events'):
            hscope = '' if principal.user['role'] in UNIT_ROLES else ' AND (h.from_id=? OR h.to_id=?)'
            params = () if not hscope else (principal.user['id'], principal.user['id'])
            source = 'handovers h' if name == 'handovers' else 'handover_events x JOIN handovers h ON h.id=x.handover_id'
            alias = 'h' if name == 'handovers' else 'x'
            parts.append(tuple(db.execute(f'SELECT COUNT(*) AS n,MAX({alias}.id) AS last_id FROM ' + source + ' WHERE 1=1' + hscope, params).fetchone().values()))
        parts.append(tuple(db.execute('SELECT COUNT(*) AS n,MAX(id) AS last_id FROM availability_events').fetchone().values()))
        parts.append([tuple(row.values()) for row in db.execute("SELECT id,role,display_name FROM users WHERE active=1 AND role IN ('doctor','nurse','coordinator') ORDER BY id")])
        if principal.user['role'] == 'admin':
            parts.append([tuple(row.values()) for row in db.execute('SELECT id,status,reviewed_at FROM permission ORDER BY id')])
            parts.append([tuple(row.values()) for row in db.execute('SELECT id,role,active,display_name FROM users ORDER BY id')])
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()

@router.get('/workspace/events')
def workspace_events(request: Request, principal=Depends(require_patients)):
    trusted_origin(request)
    cookie = request.cookies.get(COOKIE_NAME)
    async def events():
        previous = None
        while not await request.is_disconnected():
            try:
                current = await run_in_threadpool(get_auth_store().authenticate, cookie)
                if current.user['id'] != principal.user['id'] or current.user['role'] != principal.user['role']:
                    yield 'event: session-ended\ndata: {}\n\n'; return
                revision = await run_in_threadpool(workspace_revision, current)
            except AuthError:
                yield 'event: session-ended\ndata: {}\n\n'; return
            if revision != previous:
                yield 'event: workspace\ndata: ' + json.dumps({'revision': revision}) + '\n\n'
                previous = revision
            else:
                yield ': keepalive\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control':'no-store', 'X-Accel-Buffering':'no'})
