"""Shift ownership, reminders, history, PDF and scoped live updates."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.services.auth_service import COOKIE_NAME
from backend.routes.live import workspace_revision,workspace_events
from test_auth import store,signed,assign,PASSWORD
pytestmark=pytest.mark.real_auth
BASE='/api/patients/ICU-1001'

def extra_staff(store,role='doctor'):
    return store.create_user(store.owner_id,'second'+role,'Second '+role.title(),PASSWORD,role)

def login(name):
    client=TestClient(app,client=('127.0.0.1',50000))
    r=client.post('/api/auth/login',json={'username':name,'password':PASSWORD},headers={'Origin':'http://127.0.0.1:5173'})
    assert r.status_code==200
    client.headers.update({'Origin':'http://127.0.0.1:5173','X-CSRF-Token':r.json()['csrf_token']})
    return client

def ids(admin):return {u['username']:u['id'] for u in admin.get('/api/accounts').json()}
def availability(client,status='on_duty',expected=0):return client.post('/api/staff/availability',json={'status':status,'expected_event_id':expected,'note':'Fictional availability'})
def offer(client,people):return client.post(BASE+'/handovers',json={'minute':360,'as_of_minutes':1440,'from_id':people['doctor'],'to_id':people['seconddoctor'],'summary':'Fictional shift handover'})
def act(client,hid,status='accepted',minute=600):return client.post(f'/api/handovers/{hid}/status',json={'minute':minute,'as_of_minutes':1440,'status':status,'expected_event_id':0,'content':'Fictional receiving staff confirmation'})
def note(client,minute=300,review=600,assessment='Fictional follow-up'):
    return client.post(BASE+'/clinical/entries',json={'minute':minute,'as_of_minutes':1440,'kind':'follow_up','assessment':assessment,'follow_up':'Review observations','review_minute':review})

def test_availability_is_self_only_and_pauses_doctor_popups_without_hiding_requests(store):
    admin=signed();assign(admin,'doctor','nurse');doctor=signed('doctor');nurse=signed('nurse')
    nurse.post(BASE+'/clinical/review-requests',json={'minute':300,'as_of_minutes':1440,'reason':'Demo review'})
    assert doctor.get('/api/review-requests/summary').json()['pending_ids']
    first=availability(doctor,'off_duty');assert first.status_code==201
    assert availability(doctor).status_code==409
    assert doctor.get('/api/review-requests/summary').json()['open_count']==1
    assert doctor.get('/api/review-requests/summary').json()['pending_ids']==[]
    assert availability(doctor,'on_duty',first.json()['id']).status_code==201
    assert doctor.get('/api/review-requests/summary').json()['pending_ids']
    assert availability(admin).status_code==403
    assert availability(signed('researcher')).status_code==403
    assert doctor.post('/api/staff/availability',json={'status':'on_duty','expected_event_id':0,'user_id':store.owner_id}).status_code==422

def test_shift_reminders_follow_recorded_time_and_assignment_scope(store):
    admin=signed();assign(admin,'doctor','nurse');doctor=signed('doctor')
    entry=note(doctor).json()['id'];note(doctor,1200,1300,'Later review')
    early=doctor.get('/api/shift?as_of_minutes=599').json()
    assert early['tasks']['counts']['due']==0 and len(early['tasks']['items'])==1
    assert early['coverage'][0]['patient_id']=='ICU-1001'
    assert {m['availability'] for m in early['coverage'][0]['members']}=={'not_set'}
    exact=doctor.get('/api/shift?as_of_minutes=600').json()
    assert exact['tasks']['counts']['due']==1 and exact['tasks']['counts']['overdue']==0
    doctor.post(BASE+f'/clinical/entries/{entry}/follow-up',json={'minute':700,'as_of_minutes':1440,'status':'completed','expected_event_id':0,'content':'Demo completed'})
    assert doctor.get('/api/shift?as_of_minutes=600').json()['tasks']['counts']['pending']==1
    assert doctor.get('/api/shift?as_of_minutes=800').json()['tasks']['counts']['pending']==0
    assert doctor.get('/api/shift?as_of_minutes=800').json()['patient_ids']==['ICU-1001']
    assert signed('researcher').get('/api/shift').status_code==403
    assert signed('researcher').get('/api/shift/warnings').status_code==403

def test_handover_acceptance_changes_only_that_assignment_and_grants_access_after_consent(store):
    admin=signed();assign(admin,'doctor','nurse');extra_staff(store);people=ids(admin)
    doctor=signed('doctor');receiver=login('seconddoctor')
    note(doctor)
    response=offer(doctor,people);assert response.status_code==201;hid=response.json()['id']
    assert offer(doctor,people).status_code==409
    assert receiver.get(BASE+'/clinical').status_code==403
    incoming=receiver.get('/api/handovers').json()['items'][0]
    assert incoming['tasks']['count']==1 and incoming['tasks']['items'][0]['action']=='Review observations'
    assert act(doctor,hid).status_code==403
    assert act(receiver,hid).status_code==409
    assert availability(receiver).status_code==201
    assert act(receiver,hid).status_code==201
    assert act(receiver,hid).status_code==409
    assert doctor.get(BASE+'/clinical').status_code==403
    assert receiver.get(BASE+'/clinical').status_code==200
    with store.db() as db:
        assigned={r['user_id'] for r in db.execute("SELECT user_id FROM assignments WHERE patient_id='ICU-1001'")}
    assert assigned=={people['seconddoctor'],people['nurse']}
    assert receiver.get('/api/handovers?as_of_minutes=500').json()['items'][0]['status']=='pending'
    assert receiver.get('/api/handovers?status=accepted').json()['total']==1

def test_handover_decline_cancel_and_changed_assignment_do_not_silently_transfer(store):
    admin=signed();assign(admin,'doctor','nurse');extra_staff(store);people=ids(admin)
    doctor=signed('doctor');receiver=login('seconddoctor');availability(receiver)
    hid=offer(doctor,people).json()['id']
    assert act(receiver,hid,'declined').status_code==201
    assert doctor.get(BASE+'/clinical').status_code==200
    hid=offer(doctor,people).json()['id']
    assert act(receiver,hid,'cancelled').status_code==403
    assert act(doctor,hid,'cancelled').status_code==201
    hid=offer(doctor,people).json()['id']
    admin.patch(BASE+'/assignments/doctor',json={'user_ids':[]})
    assert act(receiver,hid).status_code==409
    assert receiver.get(BASE+'/clinical').status_code==403

def test_simultaneous_handover_confirmation_is_applied_once(store):
    admin=signed();assign(admin,'doctor');extra_staff(store);people=ids(admin)
    hid=offer(signed('doctor'),people).json()['id'];receiver=login('seconddoctor');availability(receiver)
    clients=[login('seconddoctor'),login('seconddoctor')]
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses=sorted(executor.map(lambda c:act(c,hid).status_code,clients))
    assert statuses==[201,409]
    with store.db() as db:assert db.execute('SELECT COUNT(*) FROM handover_events WHERE handover_id=?',(hid,)).fetchone()[0]==1

def test_history_search_loads_old_records_and_escapes_wildcards(store):
    admin=signed();assign(admin,'doctor');doctor=signed('doctor');actor=ids(admin)['doctor']
    with store.db() as db:
        for n in range(230):
            db.execute('INSERT INTO clinical_entries(patient_id,minute,kind,assessment,plan,follow_up,escalation,review_minute,actor_id,actor_role,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',('ICU-1001',300,'assessment','Unique older 100%_note' if n==0 else f'Demo record {n}','','','',None,actor,'doctor',store.clock()))
    result=doctor.get(BASE+'/history?search=100%25_note').json()
    assert result['total']==1 and result['items'][0]['content']=='Unique older 100%_note'
    assert doctor.get(BASE+'/history?limit=25&offset=200').json()['total']==230
    assert len(doctor.get(BASE+'/history?limit=25&offset=200').json()['items'])==25
    assert doctor.get(BASE+'/history?as_of_minutes=299').json()['total']==0
    assert doctor.get(BASE+'/history?kind=recommendation').json()['total']==0
    assert doctor.get(BASE+f'/history?author_id={actor}&saved_after={store.clock()+1}').json()['total']==0
    assert signed('nurse').get(BASE+'/history').status_code==403
    assert signed('researcher').get(BASE+'/history').status_code==403
    assert doctor.get(BASE+'/history?saved_after=100&saved_before=50').status_code==422
    assert doctor.get(BASE+'/history?as_of_minutes=300&minute_from=400').status_code==422

def test_history_hides_future_statuses_and_supports_handover_events(store):
    admin=signed();assign(admin,'doctor');extra_staff(store);people=ids(admin);doctor=signed('doctor');receiver=login('seconddoctor');availability(receiver)
    hid=offer(doctor,people).json()['id'];act(receiver,hid)
    rows=receiver.get(BASE+'/history?kind=shift_handover&as_of_minutes=500').json()['items']
    assert len(rows)==1 and rows[0]['source']=='offer'
    assert receiver.get(BASE+'/history?kind=shift_handover&as_of_minutes=600').json()['total']==2

def test_pdf_permission_headers_and_cutoff_snapshot(store,monkeypatch):
    admin=signed();assign(admin,'doctor');doctor=signed('doctor');note(doctor,300);note(doctor,1200,1300,'Future-only note')
    response=doctor.get(BASE+'/summary.pdf?as_of_minutes=600')
    assert response.status_code==200 and response.content.startswith(b'%PDF-')
    assert response.headers['cache-control']=='no-store' and 'attachment;' in response.headers['content-disposition']
    assert signed('researcher').get(BASE+'/summary.pdf').status_code==403
    assert signed('nurse').get(BASE+'/summary.pdf').status_code==403
    import backend.routes.reports as reports
    captured={}
    def capture(detail,clinical,generated):captured.update(clinical);return b'%PDF-demo'
    monkeypatch.setattr(reports,'make_patient_pdf',capture)
    assert doctor.get(BASE+'/summary.pdf?as_of_minutes=600').status_code==200
    assert all(e['minute']<=600 for e in captured['entries'])
    assert all(e['assessment']!='Future-only note' for e in captured['entries'])

def test_live_revisions_are_scoped_and_stream_does_not_expose_patient_content(store):
    admin=signed();assign(admin,'doctor');doctor=signed('doctor')
    principal=store.authenticate(doctor.cookies.get(COOKIE_NAME));before=workspace_revision(principal)
    signed('coordinator').post('/api/patients/ICU-1002/clinical/entries',json={'minute':300,'as_of_minutes':1440,'kind':'follow_up','assessment':'Other patient private note'})
    assert workspace_revision(principal)==before
    note(doctor)
    assert workspace_revision(principal)!=before
    calls=[False,True]
    async def disconnected():return calls.pop(0)
    request=SimpleNamespace(cookies={COOKIE_NAME:doctor.cookies.get(COOKIE_NAME)},headers={'origin':'http://127.0.0.1:5173'},is_disconnected=disconnected)
    response=workspace_events(request,principal)
    async def collect():return [item async for item in response.body_iterator]
    frames=asyncio.run(collect())
    assert len(frames)==1 and 'event: workspace' in frames[0]
    assert 'ICU-' not in frames[0] and 'Fictional' not in frames[0]
    assert signed('researcher').get('/api/workspace/events').status_code==403
    doctor.headers['Origin']='https://untrusted.example'
    assert doctor.get('/api/workspace/events').status_code==403
