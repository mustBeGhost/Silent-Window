"""Routed requests preserve assignment permissions and recorded chronology."""
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from test_auth import store, signed, assign
pytestmark = pytest.mark.real_auth
BASE = '/api/patients/ICU-1001/clinical'

def create(client, minute=360):
    return client.post(BASE + '/review-requests', json={'minute': minute, 'as_of_minutes': 1440, 'reason': 'Fictional doctor review needed'})

def change(client, request, status, expected=0, minute=720):
    return client.post(f'{BASE}/review-requests/{request}/status', json={'minute': minute, 'as_of_minutes': 1440, 'status': status, 'expected_event_id': expected, 'content': 'Fictional review action'})

def test_status_flow_replay_and_stale_updates(store):
    admin = signed(); assign(admin, 'doctor', 'nurse')
    doctor, nurse = signed('doctor'), signed('nurse')
    request = create(nurse).json()['id']
    assert admin.get(BASE + '?as_of_minutes=300').json()['review_requests']['items'] == []
    assert change(doctor, request, 'resolved').status_code == 422
    ack = change(doctor, request, 'acknowledged'); assert ack.status_code == 201
    assert change(doctor, request, 'acknowledged').status_code == 409
    assert change(doctor, request, 'resolved', ack.json()['id'], 600).status_code == 422
    done = change(doctor, request, 'resolved', ack.json()['id'], 900); assert done.status_code == 201
    assert admin.get(BASE + '?as_of_minutes=600').json()['review_requests']['items'][0]['status'] == 'pending'
    assert admin.get(BASE + '?as_of_minutes=800').json()['review_requests']['items'][0]['status'] == 'acknowledged'
    assert change(nurse, request, 'pending', done.json()['id'], 1000).status_code == 201
    data = admin.get(BASE).json()['review_requests']
    assert data['counts']['pending'] == 1 and len(data['history']) == 3
    assert data['history'][0]['author'] == 'Nurse'
    assert doctor.get('/api/review-requests/summary').json()['pending_keys'] == [f"{request}:{data['history'][0]['id']}"]

def test_unassigned_requests_reach_newly_assigned_doctors_and_old_notes_do_not(store):
    admin = signed(); coordinator = signed('coordinator'); doctor = signed('doctor')
    coordinator.post(BASE + '/entries', json={'minute': 300, 'as_of_minutes': 1440, 'kind': 'escalation', 'assessment': 'Old plain note'})
    request = create(coordinator).json()['id']
    assert admin.get('/api/review-requests').json()['counts']['unassigned'] == 1
    assert doctor.get('/api/review-requests/summary').json() == {'open_count': 0, 'pending_ids': [], 'pending_keys': []}
    assign(admin, 'doctor')
    assert doctor.get('/api/review-requests/summary').json() == {'open_count': 1, 'pending_ids': [request], 'pending_keys': [f'{request}:0']}
    assert len(doctor.get('/api/review-requests').json()['items']) == 1
    admin.patch('/api/patients/ICU-1001/assignments/doctor', json={'user_ids': []})
    assert change(doctor, request, 'acknowledged').status_code == 403
    assert doctor.get('/api/review-requests').json()['total'] == 0

def test_permissions_csrf_patient_scope_and_validation(store):
    admin = signed(); assign(admin, 'doctor', 'nurse')
    nurse, coordinator = signed('nurse'), signed('coordinator')
    request = create(nurse).json()['id']
    for client in (nurse, coordinator, admin, signed('researcher')):
        assert change(client, request, 'acknowledged').status_code == 403
    assert create(admin).status_code == 403
    assert create(signed('researcher')).status_code == 403
    assert TestClient(app).get('/api/review-requests').status_code == 401
    assert signed('researcher').get('/api/review-requests/summary').status_code == 403
    doctor = signed('doctor'); doctor.headers.pop('X-CSRF-Token')
    assert change(doctor, request, 'acknowledged').status_code == 403
    assert change(signed('doctor'), request + 999, 'acknowledged').status_code == 404
    for reason in (' ', ''):
        assert nurse.post(BASE + '/review-requests', json={'minute': 360, 'as_of_minutes': 1440, 'reason': reason}).status_code == 422
    assert change(signed('doctor'), request, 'acknowledged', minute=300).status_code == 422

def test_inbox_filters_and_model_independence(store):
    admin = signed(); assign(admin, 'doctor', 'nurse'); nurse = signed('nurse'); doctor = signed('doctor')
    before = admin.get('/api/patients/ICU-1001').json()
    first = create(nurse).json()['id']; create(nurse)
    ack = change(doctor, first, 'acknowledged').json()['id']
    change(doctor, first, 'resolved', ack, 900)
    assert admin.get('/api/review-requests?status=resolved').json()['total'] == 1
    assert admin.get('/api/review-requests?status=open').json()['total'] == 1
    assert len(admin.get('/api/review-requests?status=all&limit=1&offset=1').json()['items']) == 1
    assert admin.get(BASE + '?model_profile=expanded').json()['review_requests']['counts']['resolved'] == 1
    assert admin.get('/api/patients/ICU-1001').json() == before
