"""Real authentication and role tests; no dependency bypass is used here."""
import json
import os
import pytest
from fastapi.testclient import TestClient
import backend.services.auth_service as auth_module
from backend.services.auth_service import AuthStore, AuthError, COOKIE_NAME, ABSOLUTE_TTL, IDLE_TTL
from backend.main import app
from backend.permissions import ROLE_LABELS
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.real_auth
PASSWORD = "temporary-test-passphrase-2026"
ORIGIN = "http://127.0.0.1:5173"


@pytest.fixture(params=["sqlite", "mysql"])
def store(tmp_path, monkeypatch, request):
    clock = [1800000000.0]
    location = tmp_path / "accounts.sqlite3"
    if request.param == "mysql":
        location = os.environ.get("SILENT_WINDOW_TEST_DATABASE_URL")
        if not location:
            pytest.skip("Set an isolated MySQL test database URL to run MySQL integration checks")
        assert make_url(location).database.endswith("_auth_test"), "Refuse to clear a non-test database"
    database = AuthStore(location, clock=lambda: clock[0])
    if request.param == "mysql":
        with database.db() as db:
            db.execute("BEGIN IMMEDIATE")
            for name in ("password_resets", "permission", "patient_events", "assignments", "account_events", "sessions", "attempts", "users"):
                db.execute(f"DELETE FROM {name}")
    _, principal = database.setup("owner", "Test Owner", PASSWORD)
    database.owner_id = principal.user["id"]
    for role in ("doctor", "nurse", "coordinator", "researcher"):
        database.create_user(database.owner_id, role, ROLE_LABELS[role], PASSWORD, role)
    monkeypatch.setattr(auth_module, "_STORE", database)
    database.test_clock = clock
    yield database
    database.database.close()


def signed(role="admin"):
    client = TestClient(app, client=("127.0.0.1", 50000))
    response = client.post("/api/auth/login", json={"username": "owner" if role == "admin" else role, "password": PASSWORD}, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    client.headers.update({"X-CSRF-Token": response.json()["csrf_token"], "Origin": ORIGIN})
    return client


def assign(client, *roles):
    users = client.get("/api/accounts").json()
    ids = [user["id"] for user in users if user["role"] in roles]
    response = client.put("/api/patients/ICU-1001/assignments", json={"user_ids": ids})
    assert response.status_code == 200
    return ids


def test_local_setup_is_single_use_and_never_accepts_a_supplied_role(tmp_path, monkeypatch):
    database = AuthStore(tmp_path / "first.sqlite3")
    monkeypatch.setattr(auth_module, "_STORE", database)
    client = TestClient(app, client=("127.0.0.1", 50000))
    body = {"username": "firstadmin", "display_name": "Owner", "password": PASSWORD}
    assert client.get("/api/auth/status").json() == {"setup_required": True}
    assert client.post("/api/auth/setup", json={**body, "role": "admin"}).status_code == 422
    assert client.post("/api/auth/setup", json=body, headers={"Origin": "https://untrusted.example"}).status_code == 403
    remote = TestClient(app, client=("192.0.2.10", 50000))
    assert remote.post("/api/auth/setup", json=body).status_code == 403
    response = client.post("/api/auth/setup", json=body, headers={"Origin": ORIGIN})
    assert response.status_code == 200 and response.json()["user"]["role"] == "admin"
    assert client.post("/api/auth/setup", json=body).status_code == 409
    assert client.get("/api/auth/status").json() == {"setup_required": False}


def test_anonymous_requests_cannot_read_patients_models_or_accounts(store):
    client = TestClient(app)
    for path in ("/api/patients", "/api/patients/ICU-1001", "/api/models", "/api/accounts", "/api/team/staff", "/api/patients/ICU-1001/workflow"):
        assert client.get(path).status_code == 401, path
    assert client.get("/api/health").status_code == 200


def test_cookie_password_storage_and_logout_are_real_and_revocable(store):
    client = signed()
    cookie = client.cookies.get(COOKIE_NAME)
    response = client.post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
    with store.db() as db:
        password_hash = db.execute("SELECT password_hash FROM users WHERE username='owner'").fetchone()[0]
        session_hashes = [row[0] for row in db.execute("SELECT token_hash FROM sessions")]
    assert password_hash.startswith("$argon2id$") and PASSWORD not in password_hash
    assert cookie not in session_hashes
    assert "password_hash" not in json.dumps(response.json())
    current = client.get("/api/auth/me").json()
    client.headers["X-CSRF-Token"] = current["csrf_token"]
    copied = client.cookies.get(COOKIE_NAME)
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set(COOKIE_NAME, copied, domain="testserver.local", path="/api")
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("role", list(ROLE_LABELS))
def test_all_five_roles_can_sign_in_and_save_only_their_own_preferences(store, role):
    client = signed(role)
    assert client.get("/api/auth/me").json()["user"]["role"] == role
    preferences = {"display_name": "Updated Name", "preferred_model": "expanded", "page_size": 50, "replay_step": 180}
    assert client.patch("/api/account/preferences", json={**preferences, "role": "admin"}).status_code == 422
    saved = client.patch("/api/account/preferences", json=preferences)
    assert saved.status_code == 200 and saved.json()["role"] == role
    restored = AuthStore(store.path).authenticate(client.cookies.get(COOKIE_NAME))
    assert restored.user["preferences"] == {key: preferences[key] for key in ("preferred_model", "page_size", "replay_step")}


def test_write_requests_need_csrf_and_a_trusted_origin(store):
    client = signed()
    body = {"user_ids": []}
    assert client.put("/api/patients/ICU-1001/assignments", json=body, headers={"X-CSRF-Token": ""}).status_code == 403
    assert client.put("/api/patients/ICU-1001/assignments", json=body, headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert client.put("/api/patients/ICU-1001/assignments", json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


@pytest.mark.parametrize("role", ["doctor", "nurse", "coordinator", "researcher"])
def test_non_administrators_cannot_manage_accounts(store, role):
    client = signed(role)
    assert client.get("/api/accounts").status_code == 403
    assert client.post("/api/accounts", json={"username": "extrauser", "display_name": "Extra User", "password": PASSWORD, "role": "admin"}).status_code == 403
    assert client.patch("/api/accounts/1", json={"role": "researcher", "active": False}).status_code == 403


def test_researcher_has_aggregate_results_but_no_patient_access(store):
    client = signed("researcher")
    assert client.get("/api/models").status_code == 200
    for path in ("/api/patients", "/api/patients/ICU-1001", "/api/patients/ICU-1001/workflow", "/api/team/staff"):
        assert client.get(path).status_code == 403


@pytest.mark.parametrize("role", ["doctor", "nurse"])
def test_clinician_queue_and_direct_requests_are_assignment_scoped(store, role):
    owner = signed()
    clinician = signed(role)
    assert clinician.get("/api/patients").json()["items"] == []
    assert clinician.get("/api/patients/ICU-1001").status_code == 403
    assign(owner, role)
    for scope in ("page", "all"):
        result = clinician.get(f"/api/patients?scope={scope}&model_profile=expanded").json()
        assert result["cohort_total"] == result["total"] == 1
        assert [item["patient_id"] for item in result["items"]] == ["ICU-1001"]
    assert clinician.get("/api/patients/ICU-1002").status_code == 403
    assert clinician.get("/api/patients/ICU-1001").status_code == 200
    assert clinician.post("/api/patients/global-index/prepare").status_code == 403
    assign(owner)
    assert clinician.get("/api/patients/ICU-1001").status_code == 403


def test_coordinator_can_assign_but_cannot_create_accounts(store):
    coordinator = signed("coordinator")
    staff = coordinator.get("/api/team/staff").json()
    assert {item["role"] for item in staff} == {"doctor", "nurse"}
    assert coordinator.put("/api/patients/ICU-1001/assignments", json={"user_ids": [staff[0]["id"]]}).status_code == 200
    assert coordinator.put("/api/patients/ICU-1001/assignments", json={"user_ids": [store.owner_id]}).status_code == 422
    assert coordinator.put("/api/patients/ICU-9999/assignments", json={"user_ids": []}).status_code == 404


def test_event_roles_saved_snapshot_and_future_history_filter(store):
    owner = signed()
    assign(owner, "doctor", "nurse")
    body = {"model_profile": "expanded", "checkpoint": "12h", "event_type": "review", "content": "Research review note."}
    doctor, nurse = signed("doctor"), signed("nurse")
    before = doctor.get("/api/patients/ICU-1001?model_profile=expanded").json()
    assert nurse.post("/api/patients/ICU-1001/events", json=body).status_code == 403
    assert doctor.post("/api/patients/ICU-1001/events", json=body).status_code == 201
    assert doctor.post("/api/patients/ICU-1001/events", json={**body, "event_type": "observation"}).status_code == 403
    assert nurse.post("/api/patients/ICU-1001/events", json={**body, "event_type": "observation"}).status_code == 201
    early = doctor.get("/api/patients/ICU-1001/workflow?model_profile=expanded&as_of_minutes=540").json()
    assert early["events"] == []
    full = doctor.get("/api/patients/ICU-1001/workflow?model_profile=expanded").json()
    assert len(full["events"]) == 2
    assert full["events"][0]["risk_score"] == before["risk_probability"]
    after = doctor.get("/api/patients/ICU-1001?model_profile=expanded").json()
    assert before == after
    assert doctor.get("/api/patients/ICU-1001/workflow?model_profile=original").json()["events"] == []


def test_access_changes_revoke_sessions_and_protect_last_administrator(store):
    owner, researcher = signed(), signed("researcher")
    users = owner.get("/api/accounts").json()
    target = next(user for user in users if user["role"] == "researcher")
    assert owner.patch(f"/api/accounts/{target['id']}", json={"role": "doctor", "active": True}).status_code == 200
    assert researcher.get("/api/auth/me").status_code == 401
    assert owner.patch(f"/api/accounts/{store.owner_id}", json={"role": "researcher", "active": False}).status_code == 409
    assert owner.post("/api/auth/register", json={"username": "owner", "display_name": "Duplicate", "password": PASSWORD, "requested_role": "doctor"}).status_code == 409
    assert owner.post("/api/accounts", json={"username": "newperson", "display_name": "New Person", "password": PASSWORD, "role": "viewer"}).status_code == 422


def test_idle_absolute_expiry_and_rate_limit(store):
    token, _ = store.login("owner", PASSWORD, "test-expiry")
    store.test_clock[0] += IDLE_TTL
    with pytest.raises(AuthError) as failure:
        store.authenticate(token)
    assert failure.value.status == 401
    token, _ = store.login("owner", PASSWORD, "test-absolute")
    for _ in range(17):
        store.test_clock[0] += IDLE_TTL - 1
        try:
            store.authenticate(token)
        except AuthError as failure:
            assert failure.status == 401
            break
    else:
        raise AssertionError("Absolute expiry did not end the session")
    for _ in range(10):
        with pytest.raises(AuthError) as failure:
            store.login("missingperson", "wrong", "test-limit")
        assert failure.value.status == 401
    with pytest.raises(AuthError) as failure:
        store.login("missingperson", "wrong", "test-limit")
    assert failure.value.status == 429
    store.test_clock[0] += 601
    with pytest.raises(AuthError) as failure:
        store.login("missingperson", "wrong", "test-limit")
    assert failure.value.status == 401


def test_sixth_session_revokes_the_oldest_but_keeps_the_new_five(store):
    tokens = []
    for _ in range(6):
        store.test_clock[0] += 1
        token, _ = store.login("owner", PASSWORD, "session-cap-test")
        tokens.append(token)
    with pytest.raises(AuthError) as expired:
        store.authenticate(tokens[0])
    assert expired.value.status == 401
    assert all(store.authenticate(token).user["id"] == store.owner_id for token in tokens[1:])


def test_first_setup_race_creates_exactly_one_administrator(store):
    from concurrent.futures import ThreadPoolExecutor
    # Only the already-isolated test store is cleared here.
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        for name in ("permission", "patient_events", "assignments", "account_events", "sessions", "attempts", "users"):
            db.execute(f"DELETE FROM {name}")
    def create(username):
        try:
            store.setup(username, username, PASSWORD)
            return 200
        except AuthError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, ("first-admin", "second-admin")))
    assert sorted(results) == [200, 409]
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] == 1


def test_warning_acknowledgement_cannot_be_saved_for_a_no_alert_assessment(store):
    owner = signed()
    assign(owner, "nurse")
    nurse = signed("nurse")
    assert nurse.post("/api/patients/ICU-1001/events", json={"model_profile": "original",
        "checkpoint": "12h", "event_type": "acknowledge", "content": "I saw this assessment."}).status_code == 409
    assert nurse.get("/api/patients/ICU-1001/workflow").json()["events"] == []


def test_new_account_username_rules_and_duplicate_warning_without_changing_existing_account(store):
    owner = signed()
    before = owner.get("/api/accounts").json()
    body = {"display_name": "New Member", "password": PASSWORD, "requested_role": "nurse"}
    for username in ("1admin", "123", "Admin", "admin_name", "admin.name", "admin-name", "admin name", " admin", "álpha", "ab", "a" * 33):
        response = owner.post("/api/auth/register", json={**body, "username": username})
        assert response.status_code == 422, username
    assert owner.get("/api/accounts").json() == before
    for username in ("newmember", "member12", "a12", "a" * 32):
        response = owner.post("/api/auth/register", json={**body, "username": username})
        assert response.status_code == 202, username
        assert owner.post(f"/api/permissions/{response.json()['id']}/review", json={"decision": "approve", "role": "nurse"}).status_code == 200
    created = owner.get("/api/accounts").json()
    duplicate = owner.post("/api/auth/register", json={**body, "username": "member12", "requested_role": "doctor", "password": "different-test-passphrase"})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "That username is already in use."
    assert owner.get("/api/accounts").json() == created
    member = TestClient(app)
    assert member.post("/api/auth/login", json={"username": "MEMBER12", "password": PASSWORD}).status_code == 200


def test_setup_enforces_the_same_username_rules_and_keeps_legacy_sign_in(tmp_path, monkeypatch):
    database = AuthStore(tmp_path / "username-setup.sqlite3")
    monkeypatch.setattr(auth_module, "_STORE", database)
    client = TestClient(app, client=("127.0.0.1", 50000))
    body = {"display_name": "Owner", "password": PASSWORD}
    for username in ("1owner", "Owner", "owner_name", "123", "ow"):
        assert client.post("/api/auth/setup", json={**body, "username": username}).status_code == 422
        assert database.setup_required()
    assert client.post("/api/auth/setup", json={**body, "username": "owner12"}).status_code == 200
    # Legacy accounts are not renamed or locked out by the new creation rule.
    database.create_user(database.list_users(1)[0]["id"], "legacy-user", "Legacy User", PASSWORD, "nurse")
    assert client.post("/api/auth/login", json={"username": "LEGACY-USER", "password": PASSWORD}).status_code == 200
    database.database.close()


def submit_worker(username='newworker', requested_role='nurse'):
    client = TestClient(app, client=('127.0.0.1', 50200))
    response = client.post('/api/auth/register', json={'username': username, 'display_name': 'New Worker',
        'password': PASSWORD, 'requested_role': requested_role, 'request_note': 'Department: ICU'}, headers={'Origin': ORIGIN})
    assert response.status_code == 202, response.text
    assert 'password' not in response.text and response.json()['status'] == 'pending'
    assert COOKIE_NAME not in response.cookies
    return client, response.json()['id']


def test_pending_request_is_only_in_permission_and_cannot_sign_in_or_read_data(store):
    worker, request_id = submit_worker()
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE username='newworker'").fetchone()[0] == 0
        row = db.execute('SELECT * FROM permission WHERE id=?', (request_id,)).fetchone()
        assert row['status'] == 'pending' and row['password_hash'].startswith('$argon2id$')
        assert PASSWORD not in row['password_hash']
    assert worker.post('/api/auth/login', json={'username': 'newworker', 'password': PASSWORD}).status_code == 401
    for path in ('/api/patients', '/api/permissions', '/api/accounts'):
        assert worker.get(path).status_code == 401
    body = {'username': 'newworker', 'display_name': 'Other Worker', 'password': 'other-test-passphrase', 'requested_role': 'doctor'}
    duplicate = worker.post('/api/auth/register', json=body)
    assert duplicate.status_code == 409 and 'waiting for approval' in duplicate.json()['detail']
    listing = signed().get('/api/permissions').json()
    assert listing['total'] == 1 and listing['items'][0]['id'] == request_id
    assert 'password_hash' not in json.dumps(listing)


def test_approval_creates_account_with_original_password_and_admin_chosen_role_once(store):
    worker, request_id = submit_worker(requested_role='nurse')
    owner = signed()
    assert owner.post(f'/api/permissions/{request_id}/review', json={'decision': 'approve'}).status_code == 422
    approved = owner.post(f'/api/permissions/{request_id}/review', json={'decision': 'approve', 'role': 'doctor', 'note': 'Staff identity verified.'})
    assert approved.status_code == 200
    assert approved.json()['requested_role'] == 'nurse' and approved.json()['granted_role'] == 'doctor'
    assert 'password_hash' not in approved.text
    assert owner.post(f'/api/permissions/{request_id}/review', json={'decision': 'reject'}).status_code == 409
    session = worker.post('/api/auth/login', json={'username': 'newworker', 'password': PASSWORD})
    assert session.status_code == 200 and session.json()['user']['role'] == 'doctor'
    assert worker.get('/api/patients').json()['items'] == []
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE username='newworker'").fetchone()[0] == 1
        row = db.execute('SELECT * FROM permission WHERE id=?', (request_id,)).fetchone()
        assert row['password_hash'] is None and row['reviewed_by'] == store.owner_id
        assert row['approved_user_id'] == session.json()['user']['id']


def test_rejection_never_creates_user_and_resubmission_keeps_decision_history(store):
    worker, request_id = submit_worker()
    owner = signed()
    rejected = owner.post(f'/api/permissions/{request_id}/review', json={'decision': 'reject', 'note': 'Unable to verify staff details.'})
    assert rejected.status_code == 200 and rejected.json()['status'] == 'rejected'
    assert rejected.json()['approved_user_id'] is None
    assert worker.post('/api/auth/login', json={'username': 'newworker', 'password': PASSWORD}).status_code == 401
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE username='newworker'").fetchone()[0] == 0
        assert db.execute('SELECT password_hash FROM permission WHERE id=?', (request_id,)).fetchone()[0] is None
        event = db.execute("SELECT actor_id,target_id FROM account_events WHERE action='reject_account'").fetchone()
        assert event['actor_id'] == store.owner_id and event['target_id'] is None
    _, next_id = submit_worker()
    assert next_id != request_id
    assert owner.get('/api/permissions?status=rejected').json()['total'] == 1
    assert owner.get('/api/permissions?status=pending').json()['total'] == 1


@pytest.mark.parametrize('role', ['doctor', 'nurse', 'coordinator', 'researcher'])
def test_only_admin_can_read_or_decide_requests_and_direct_creation_is_closed(store, role):
    _, request_id = submit_worker()
    client = signed(role)
    assert client.get('/api/permissions').status_code == 403
    assert client.post(f'/api/permissions/{request_id}/review', json={'decision': 'approve', 'role': 'admin'}).status_code == 403
    owner = signed()
    assert owner.post(f'/api/permissions/{request_id}/review', json={'decision': 'reject'}, headers={'X-CSRF-Token': ''}).status_code == 403
    assert owner.post('/api/accounts', json={'username': 'bypass', 'display_name': 'Bypass User', 'password': PASSWORD, 'role': 'doctor'}).status_code == 410
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE username IN ('bypass','newworker')").fetchone()[0] == 0


def test_signup_cannot_self_assign_admin_or_extra_access_and_blocks_untrusted_origins(store):
    client = TestClient(app)
    body = {'username': 'newworker', 'display_name': 'Worker', 'password': PASSWORD, 'requested_role': 'nurse'}
    for extra in ({'requested_role': 'admin'}, {'role': 'admin'}, {'active': True}):
        assert client.post('/api/auth/register', json={**body, **extra}).status_code == 422
    assert client.post('/api/auth/register', json=body, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert signed().get('/api/permissions').json()['total'] == 0


def test_parallel_signup_and_approval_rejection_races_have_one_winner(store):
    from concurrent.futures import ThreadPoolExecutor
    def register(_):
        try:
            return store.request_account('raceworker', 'Worker', PASSWORD, 'nurse', '', 'race-signup')['id']
        except AuthError as error:
            assert error.status == 409
            return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register, range(2)))
    request_id = next(result for result in results if result is not None)
    assert sum(result is not None for result in results) == 1
    def review(decision):
        try:
            return store.review_request(store.owner_id, request_id, decision, 'nurse', '')['status']
        except AuthError as error:
            assert error.status == 409
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(review, ('approve', 'reject')))
    assert results.count('conflict') == 1
    with store.db() as db:
        row = db.execute('SELECT status,password_hash FROM permission WHERE id=?', (request_id,)).fetchone()
        count = db.execute("SELECT COUNT(*) FROM users WHERE username='raceworker'").fetchone()[0]
    assert count == (1 if row['status'] == 'approved' else 0) and row['password_hash'] is None


def test_request_pagination_and_rate_limit(store):
    for index in range(3):
        store.request_account(f'worker{index}', 'Worker', PASSWORD, 'nurse', '', 'pagination')
    owner = signed()
    page = owner.get('/api/permissions?limit=2&offset=2').json()
    assert page['total'] == 3 and len(page['items']) == 1
    assert owner.get('/api/permissions?limit=101').status_code == 422
    assert owner.get('/api/permissions?offset=-1').status_code == 422
    assert owner.post('/api/permissions/999999/review', json={'decision': 'reject'}).status_code == 404
    with store.db() as db:
        db.execute('INSERT INTO attempts VALUES(?,?,?)', (auth_module.digest('client:signup:limited'), store.clock(), 60))
    with pytest.raises(AuthError) as failure:
        store.request_account('limitedworker', 'Worker', PASSWORD, 'nurse', '', 'limited')
    assert failure.value.status == 429


def test_request_summary_is_admin_only_and_tracks_new_ids_even_when_count_is_unchanged(store):
    assert TestClient(app).get('/api/permissions/summary').status_code == 401
    owner = signed()
    assert owner.get('/api/permissions/summary').json() == {'pending_count': 0, 'latest_pending_id': 0}
    for role in ('doctor', 'nurse', 'coordinator', 'researcher'):
        assert signed(role).get('/api/permissions/summary').status_code == 403
    _, first = submit_worker('firstworker')
    assert owner.get('/api/permissions/summary').json() == {'pending_count': 1, 'latest_pending_id': first}
    assert owner.post(f'/api/permissions/{first}/review', json={'decision': 'reject'}).status_code == 200
    _, second = submit_worker('secondworker')
    assert second > first
    summary = owner.get('/api/permissions/summary')
    assert summary.json() == {'pending_count': 1, 'latest_pending_id': second}
    assert 'username' not in summary.text and 'password' not in summary.text


def test_separate_group_edits_save_multiple_staff_keep_other_role_and_allow_removal(store):
    owner = signed()
    users = owner.get('/api/accounts').json()
    doctor = next(item['id'] for item in users if item['role'] == 'doctor')
    nurse = next(item['id'] for item in users if item['role'] == 'nurse')
    extra_doctor = store.create_user(store.owner_id, 'doctor2', 'Doctor Two', PASSWORD, 'doctor')['id']
    extra_nurse = store.create_user(store.owner_id, 'nurse2', 'Nurse Two', PASSWORD, 'nurse')['id']
    assert owner.patch('/api/patients/ICU-1001/assignments/nurse', json={'user_ids': [nurse, extra_nurse]}).status_code == 200
    saved = owner.patch('/api/patients/ICU-1001/assignments/doctor', json={'user_ids': [doctor, extra_doctor, doctor]})
    assert saved.status_code == 200
    assert {item['id'] for item in saved.json()['assignments']} == {doctor, extra_doctor, nurse, extra_nurse}
    assert all(item['username'] for item in saved.json()['assignments'])
    doctor_client = signed('doctor')
    assert doctor_client.get('/api/patients/ICU-1001').status_code == 200
    assert signed('nurse').get('/api/patients/ICU-1001').status_code == 200
    removed = owner.patch('/api/patients/ICU-1001/assignments/doctor', json={'user_ids': []})
    assert removed.status_code == 200
    assert {item['id'] for item in removed.json()['assignments']} == {nurse, extra_nurse}
    assert doctor_client.get('/api/patients/ICU-1001').status_code == 403
    assert signed('nurse').get('/api/patients/ICU-1001').status_code == 200
    assert owner.get('/api/patients/ICU-1002/workflow').json()['assignments'] == []


def test_group_edits_reject_wrong_role_inactive_staff_and_invalid_requests_without_changing_team(store):
    owner = signed()
    ids = assign(owner, 'doctor', 'nurse')
    before = owner.get('/api/patients/ICU-1001/workflow').json()['assignments']
    nurse = next(person['id'] for person in before if person['role'] == 'nurse')
    for invalid in ([nurse], [store.owner_id], [999999]):
        assert owner.patch('/api/patients/ICU-1001/assignments/doctor', json={'user_ids': invalid}).status_code == 422
        assert owner.get('/api/patients/ICU-1001/workflow').json()['assignments'] == before
    assert owner.patch('/api/patients/ICU-1001/assignments/doctor', json={'user_ids': ids * 11}).status_code == 422
    assert owner.patch('/api/patients/ICU-9999/assignments/doctor', json={'user_ids': []}).status_code == 404
    assert owner.patch('/api/patients/ICU-1001/assignments/researcher', json={'user_ids': []}).status_code == 422
    assert owner.patch('/api/patients/ICU-1001/assignments/doctor', json={'user_ids': []}, headers={'X-CSRF-Token': ''}).status_code == 403
    assert owner.patch('/api/patients/ICU-1001/assignments/doctor', json={'user_ids': []}, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    doctor = next(person['id'] for person in before if person['role'] == 'doctor')
    assert owner.patch(f'/api/accounts/{doctor}', json={'role': 'doctor', 'active': False}).status_code == 200
    assert owner.patch('/api/patients/ICU-1001/assignments/doctor', json={'user_ids': [doctor]}).status_code == 422
    assert owner.patch('/api/patients/ICU-1001/assignments/nurse', json={'user_ids': [nurse]}).status_code == 200
    # Editing nurses does not discard an inactive doctor assignment.
    assert {person['id'] for person in owner.get('/api/patients/ICU-1001/workflow').json()['assignments']} == set(ids)


def test_group_edits_are_limited_to_admin_and_coordinator(store):
    owner = signed()
    assign(owner, 'doctor', 'nurse')
    for role in ('doctor', 'nurse', 'researcher'):
        assert signed(role).patch('/api/patients/ICU-1001/assignments/doctor', json={'user_ids': []}).status_code == 403
    coordinator = signed('coordinator')
    assert coordinator.patch('/api/patients/ICU-1001/assignments/nurse', json={'user_ids': []}).status_code == 200
    assert TestClient(app).patch('/api/patients/ICU-1001/assignments/nurse', json={'user_ids': []}).status_code == 401


def test_concurrent_doctor_and_nurse_edits_cannot_overwrite_each_other(store):
    from concurrent.futures import ThreadPoolExecutor
    owner, coordinator = signed(), signed('coordinator')
    users = owner.get('/api/accounts').json()
    ids = {item['role']: item['id'] for item in users}
    def change(role):
        client = owner if role == 'doctor' else coordinator
        return client.patch(f'/api/patients/ICU-1001/assignments/{role}', json={'user_ids': [ids[role]]}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(change, ('doctor', 'nurse'))) == [200, 200]
    final = owner.get('/api/patients/ICU-1001/workflow').json()['assignments']
    assert {item['id'] for item in final} == {ids['doctor'], ids['nurse']}
