"""Follow-ups preserve history, replay chronology and assigned-staff access."""
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from test_auth import store, signed, assign

pytestmark = pytest.mark.real_auth
BASE = '/api/patients/ICU-1001/clinical'


def create_plan(admin):
    assign(admin, 'doctor', 'nurse')
    doctor = signed('doctor')
    response = doctor.post(BASE + '/entries', json={
        'minute': 360, 'as_of_minutes': 1440, 'kind': 'visit',
        'assessment': 'Fictional review', 'follow_up': 'Review the recorded measurements', 'review_minute': 480})
    assert response.status_code == 201
    return response.json()['id']


def change(client, entry_id, status='completed', expected=0, minute=720, **extra):
    return client.post(f'{BASE}/entries/{entry_id}/follow-up', json={
        'minute': minute, 'as_of_minutes': 1440, 'status': status,
        'expected_event_id': expected, 'content': 'Fictional review action completed', **extra})


def test_pending_completion_and_reopening_preserve_recorded_history(store):
    admin = signed(); entry = create_plan(admin)
    assert admin.get(BASE + '?as_of_minutes=359').json()['follow_ups']['counts']['pending'] == 0
    pending = admin.get(BASE + '?as_of_minutes=600').json()['follow_ups']
    assert pending['counts'] == {'pending': 1, 'completed': 0, 'overdue': 1}
    assert pending['items'][0]['event_id'] == 0
    result = change(signed('nurse'), entry)
    assert result.status_code == 201
    completed_id = result.json()['id']
    current = admin.get(BASE + '?as_of_minutes=800').json()['follow_ups']
    assert current['counts'] == {'pending': 0, 'completed': 1, 'overdue': 0}
    assert current['items'][0]['status_author'] == 'Nurse'
    assert current['items'][0]['status_minute'] == 720 and current['items'][0]['status_saved_at'] == store.clock()
    assert admin.get(BASE + '?as_of_minutes=600').json()['follow_ups']['items'][0]['status'] == 'pending'
    assert change(signed('doctor'), entry, 'pending', completed_id, 900, content='Needs another recorded review').status_code == 201
    assert admin.get(BASE + '?as_of_minutes=800').json()['follow_ups']['items'][0]['status'] == 'completed'
    now = admin.get(BASE).json()['follow_ups']
    assert now['items'][0]['status'] == 'pending' and len(now['history']) == 2
    assert now['history'][1]['status'] == 'completed'


def test_stale_duplicate_and_backdated_changes_do_not_overwrite_completion(store):
    admin = signed(); entry = create_plan(admin); doctor = signed('doctor')
    assert change(doctor, entry, minute=300).status_code == 422
    done = change(doctor, entry); assert done.status_code == 201
    assert change(doctor, entry).status_code == 409
    assert change(doctor, entry, expected=done.json()['id']).status_code == 409
    assert change(doctor, entry, 'pending', done.json()['id'], 600).status_code == 422
    # A view before the completion cannot replace a transition it cannot yet see.
    assert change(doctor, entry, 'completed', 0, 600, as_of_minutes=600).status_code == 409
    assert len(admin.get(BASE).json()['follow_ups']['history']) == 1


def test_follow_up_write_permissions_and_patient_scope_are_enforced(store):
    admin = signed(); entry = create_plan(admin)
    assert change(TestClient(app), entry).status_code == 401
    assert change(admin, entry).status_code == 403
    assert change(signed('researcher'), entry).status_code == 403
    doctor = signed('doctor'); doctor.headers.pop('X-CSRF-Token')
    assert change(doctor, entry).status_code == 403
    assert change(signed('doctor'), entry + 999).status_code == 404
    admin.patch('/api/patients/ICU-1001/assignments/doctor', json={'user_ids': []})
    assert change(signed('doctor'), entry).status_code == 403
    assert admin.get(BASE).json()['follow_ups']['counts']['completed'] == 0


def test_plain_notes_are_not_treated_as_actions_and_bad_times_or_blank_notes_fail(store):
    admin = signed(); create_plan(admin); doctor = signed('doctor')
    note = doctor.post(BASE + '/entries', json={'minute': 360, 'as_of_minutes': 1440, 'kind': 'assessment', 'assessment': 'Just a note'}).json()['id']
    assert change(doctor, note).status_code == 422
    for extra in ({'content': '  '}, {'minute': 1441}, {'minute': True}, {'as_of_minutes': 600}, {'expected_event_id': True}):
        assert change(doctor, note, **extra).status_code == 422


def test_follow_ups_stay_shared_across_models_without_changing_model_results(store):
    admin = signed(); entry = create_plan(admin)
    before = admin.get('/api/patients/ICU-1001').json()
    assert change(signed('coordinator'), entry).status_code == 201
    assert admin.get(BASE + '?model_profile=expanded').json()['follow_ups']['counts']['completed'] == 1
    assert admin.get('/api/patients/ICU-1001').json() == before


def test_simultaneous_completion_cannot_create_two_transitions(store):
    from concurrent.futures import ThreadPoolExecutor
    admin = signed(); entry = create_plan(admin)
    clients = [signed('doctor'), signed('nurse')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda client: change(client, entry).status_code, clients))
    assert sorted(codes) == [201, 409]
    assert len(admin.get(BASE).json()['follow_ups']['history']) == 1
