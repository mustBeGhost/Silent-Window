"""Password lifecycle checks run against both isolated SQLite and MySQL stores."""
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.services.auth_service import AuthError, RESET_TTL, digest
from tests.test_auth import store, signed, PASSWORD, ORIGIN

pytestmark = pytest.mark.real_auth
NEW_PASSWORD = 'a-new-private-passphrase-2026'


def target_id(owner, role='doctor'):
    return next(item['id'] for item in owner.get('/api/accounts').json() if item['role'] == role)


def issue(owner, user_id):
    response = owner.post(f'/api/accounts/{user_id}/password-recovery', json={'current_password': PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()['recovery_code']


def reset(client, code, username='doctor', password=NEW_PASSWORD):
    return client.post('/api/auth/reset-password', json={'username': username, 'recovery_code': code, 'password': password}, headers={'Origin': ORIGIN})


@pytest.mark.parametrize('role', ['admin', 'doctor', 'nurse', 'coordinator', 'researcher'])
def test_password_change_requires_current_password_and_revokes_all_sessions(store, role):
    first, other = signed(role), signed(role)
    owner = signed()
    if role != 'admin':
        code = issue(owner, target_id(owner, role))
    else:
        code = store.issue_operator_recovery('owner')['recovery_code']
    response = first.post('/api/account/password', json={'current_password': PASSWORD, 'new_password': NEW_PASSWORD})
    assert response.status_code == 200 and 'Sign in again' in response.json()['message']
    assert first.get('/api/auth/me').status_code == other.get('/api/auth/me').status_code == 401
    username = 'owner' if role == 'admin' else role
    anonymous = TestClient(app)
    assert anonymous.post('/api/auth/login', json={'username': username, 'password': PASSWORD}).status_code == 401
    assert anonymous.post('/api/auth/login', json={'username': username, 'password': NEW_PASSWORD}).status_code == 200
    assert reset(anonymous, code, username).status_code == 400


def test_invalid_password_change_and_csrf_do_not_change_password_or_end_session(store):
    client = signed('doctor')
    body = {'current_password': 'incorrect', 'new_password': NEW_PASSWORD}
    assert client.post('/api/account/password', json=body).status_code == 400
    assert client.get('/api/auth/me').status_code == 200
    assert client.post('/api/account/password', json={**body, 'current_password': PASSWORD, 'new_password': PASSWORD}).status_code == 422
    assert client.post('/api/account/password', json={**body, 'new_password': 'short'}).status_code == 422
    assert client.post('/api/account/password', json=body, headers={'X-CSRF-Token': ''}).status_code == 403
    assert client.post('/api/account/password', json=body, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert signed('doctor').get('/api/auth/me').status_code == 200


def test_recovery_is_admin_only_requires_reauthentication_and_does_not_change_access(store):
    owner, doctor = signed(), signed('doctor')
    user_id = target_id(owner)
    path = f'/api/accounts/{user_id}/password-recovery'
    body = {'current_password': PASSWORD}
    assert TestClient(app).post(path, json=body).status_code == 401
    for role in ('doctor', 'nurse', 'coordinator', 'researcher'):
        assert signed(role).post(path, json=body).status_code == 403
    assert owner.post(path, json={'current_password': 'incorrect'}).status_code == 400
    assert owner.post(path, json=body, headers={'X-CSRF-Token': ''}).status_code == 403
    assert owner.post(f'/api/accounts/{store.owner_id}/password-recovery', json=body).status_code == 422
    code = issue(owner, user_id)
    assert doctor.get('/api/auth/me').status_code == 200  # issuance alone does not lock out workers
    with store.db() as db:
        row = db.execute('SELECT * FROM password_resets WHERE user_id=?', (user_id,)).fetchone()
        assert row['token_hash'] == digest(code) and code not in json.dumps(row)
    assert code not in owner.get('/api/accounts').text
    assert reset(TestClient(app), code).status_code == 200
    assert doctor.get('/api/auth/me').status_code == 401
    assert reset(TestClient(app), code).status_code == 400
    with store.db() as db:
        assert db.execute('SELECT COUNT(*) FROM password_resets WHERE user_id=?', (user_id,)).fetchone()[0] == 0


def test_wrong_expired_replaced_and_disabled_codes_never_reset_password(store):
    owner = signed()
    user_id = target_id(owner)
    first, second = issue(owner, user_id), issue(owner, user_id)
    anonymous = TestClient(app)
    assert reset(anonymous, first).status_code == 400
    assert reset(anonymous, second, username='missinguser').status_code == 400
    assert reset(anonymous, 'a' * 43).status_code == 400
    assert reset(anonymous, second, password=PASSWORD).status_code == 422
    assert reset(anonymous, second, password='short').status_code == 422
    assert reset(anonymous, second).status_code == 200
    third = issue(owner, user_id)
    store.test_clock[0] += RESET_TTL
    assert reset(anonymous, third).status_code == 400
    fourth = issue(owner, user_id)
    assert owner.patch(f'/api/accounts/{user_id}', json={'role': 'doctor', 'active': False}).status_code == 200
    assert reset(anonymous, fourth).status_code == 400
    assert owner.post(f'/api/accounts/{user_id}/password-recovery', json={'current_password': PASSWORD}).status_code == 422
    assert owner.patch(f'/api/accounts/{user_id}', json={'role': 'doctor', 'active': True}).status_code == 200
    assert reset(anonymous, fourth).status_code == 400
    assert anonymous.post('/api/auth/login', json={'username': 'doctor', 'password': NEW_PASSWORD}).status_code == 200
    with store.db() as db:
        assert db.execute('SELECT role,active FROM users WHERE id=?', (user_id,)).fetchone() == {'role': 'doctor', 'active': 1}


def test_recovery_codes_are_one_use_under_concurrent_resets(store):
    owner = signed()
    code = issue(owner, target_id(owner))
    def attempt(client):
        try:
            store.reset_password('doctor', code, NEW_PASSWORD + str(client), f'concurrent-{client}')
            return 200
        except AuthError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, (1, 2))) == [200, 400]


def test_reset_is_rate_limited_and_rejects_untrusted_origin(store):
    client = TestClient(app)
    body = {'username': 'doctor', 'recovery_code': 'a' * 43, 'password': NEW_PASSWORD}
    assert client.post('/api/auth/reset-password', json=body, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    for _ in range(10):
        assert reset(client, 'a' * 43).status_code == 400
    assert reset(client, 'a' * 43).status_code == 429
