"""MySQL accounts, Argon2id passwords and revocable cookie sessions."""
from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import time
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from backend.permissions import capabilities
from backend.services.account_database import AccountDatabase
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)
COOKIE_NAME = "silent_window_session"
ABSOLUTE_TTL = 8 * 60 * 60
IDLE_TTL = 30 * 60
RESET_TTL = 15 * 60
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)


class AuthError(Exception):
    def __init__(self, message, status=400):
        self.status = status
        super().__init__(message)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_for(token):
    return hmac.new(token.encode(), b"silent-window-csrf-v1", hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Principal:
    user: dict
    csrf_token: str


class AuthStore:
    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock
        self.database = AccountDatabase(path)
        self.dummy_hash = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))
    def db(self):
        return self.database.db()

    @staticmethod
    def public_user(row):
        return {"id": row["id"], "username": row["username"], "display_name": row["display_name"],
                "role": row["role"], "active": bool(row["active"]),
                "capabilities": capabilities(row["role"]),
                "preferences": {"preferred_model": row["preferred_model"], "page_size": row["page_size"], "replay_step": row["replay_step"]}}

    def setup_required(self):
        with self.db() as db:
            return db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0

    def _event(self, db, actor_id, target_id, action):
        db.execute("INSERT INTO account_events(actor_id,target_id,action,created_at) VALUES(?,?,?,?)",
                   (actor_id, target_id, action, self.clock()))

    def setup(self, username, display_name, password):
        password_hash = PASSWORD_HASHER.hash(password)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                raise AuthError("Setup is already complete. Sign in instead.", 409)
            cursor = db.execute("INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,'admin',?)",
                                (username, display_name, password_hash, self.clock()))
            self._event(db, cursor.lastrowid, cursor.lastrowid, "setup_admin")
        return self.login(username, password, "setup")

    def _limit(self, username, client):
        now = self.clock()
        limited = False
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM attempts WHERE started_at <= ?", (now - 600,))
            for key, maximum in (("user:" + username, 10), ("client:" + client, 60)):
                bucket = digest(key)
                row = db.execute("SELECT count FROM attempts WHERE bucket=?", (bucket,)).fetchone()
                count = row["count"] if row else 0
                if count >= maximum:
                    limited = True
                elif row:
                    db.execute("UPDATE attempts SET count=count+1 WHERE bucket=?", (bucket,))
                else:
                    db.execute("INSERT INTO attempts VALUES(?,?,1)", (bucket, now))
        if limited:
            raise AuthError("Too many sign-in attempts. Try again in ten minutes.", 429)

    def login(self, username, password, client):
        self._limit(username, client)
        with self.db() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        try:
            PASSWORD_HASHER.verify(row["password_hash"] if row else self.dummy_hash, password)
        except (VerificationError, InvalidHashError):
            raise AuthError("Username or password is incorrect.", 401) from None
        if not row or not row["active"]:
            raise AuthError("Username or password is incorrect.", 401)
        token, now = secrets.token_urlsafe(32), self.clock()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            # Recheck inside the transaction: an administrator may have revoked access during hashing.
            current = db.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
            if not current["active"] or current["password_hash"] != row["password_hash"] or current["role"] != row["role"]:
                raise AuthError("Username or password is incorrect.", 401)
            db.execute("DELETE FROM sessions WHERE expires_at<=? OR last_seen<=?", (now, now - IDLE_TTL))
            old_tokens = [item[0] for item in db.execute("SELECT token_hash FROM sessions WHERE user_id=? ORDER BY created_at DESC", (row["id"],))][4:]
            for old_token in old_tokens:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (old_token,))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (digest(token), row["id"], now, now, now + ABSOLUTE_TTL))
            db.execute("DELETE FROM attempts WHERE bucket=?", (digest("user:" + username),))
        return token, Principal(self.public_user(current), csrf_for(token))

    def authenticate(self, token):
        if not isinstance(token, str) or len(token) != 43:
            raise AuthError("Sign in to continue.", 401)
        now = self.clock()
        with self.db() as db:
            row = db.execute("SELECT u.*, s.created_at AS session_created, s.last_seen, s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?", (digest(token),)).fetchone()
            if not row or not row["active"] or row["expires_at"] <= now or row["last_seen"] <= now - IDLE_TTL:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (digest(token),))
                invalid = True
            else:
                db.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (now, digest(token)))
                invalid = False
        if invalid:
            raise AuthError("Your session ended. Please sign in again.", 401)
        return Principal(self.public_user(row), csrf_for(token))

    def logout(self, token):
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (digest(token),))

    @staticmethod
    def _verify_password(row, password):
        try:
            PASSWORD_HASHER.verify(row['password_hash'], password)
        except (VerificationError, InvalidHashError):
            raise AuthError('Your current password is incorrect.', 400) from None

    def _confirmed_user(self, user_id, password, purpose):
        # Use a separate rate bucket so changing a password cannot reset login limits.
        self._limit(f'{purpose}:{user_id}', f'{purpose}:{user_id}')
        with self.db() as db:
            row = db.execute('SELECT * FROM users WHERE id=? AND active=1', (user_id,)).fetchone()
        if not row:
            raise AuthError('Your account is unavailable.', 401)
        self._verify_password(row, password)
        return row

    def change_password(self, user_id, current_password, new_password):
        row = self._confirmed_user(user_id, current_password, 'change-password')
        if current_password == new_password:
            raise AuthError('Choose a different new password.', 422)
        hashed = PASSWORD_HASHER.hash(new_password)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM users WHERE id=? AND active=1', (user_id,)).fetchone()
            if not current or current['password_hash'] != row['password_hash']:
                raise AuthError('Your account changed. Sign in again before continuing.', 409)
            self._replace_password(db, user_id, hashed)
            self._event(db, user_id, user_id, 'change_password')
        return {'message': 'Your password was changed. Sign in again with your new password.'}

    @staticmethod
    def _replace_password(db, user_id, hashed):
        db.execute('UPDATE users SET password_hash=? WHERE id=?', (hashed, user_id))
        db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
        db.execute('DELETE FROM password_resets WHERE user_id=?', (user_id,))

    def _issue_recovery(self, db, target, actor):
        token, now = secrets.token_urlsafe(32), self.clock()
        db.execute('DELETE FROM password_resets WHERE expires_at<=? OR user_id=?', (now, target))
        db.execute('INSERT INTO password_resets(user_id,token_hash,created_at,expires_at,issued_by) VALUES(?,?,?,?,?)',
            (target, digest(token), now, now + RESET_TTL, actor))
        self._event(db, actor, target, 'issue_password_recovery')
        return {'recovery_code': token, 'expires_at': now + RESET_TTL}

    def issue_recovery(self, actor, target, current_password):
        confirmed = self._confirmed_user(actor, current_password, 'issue-recovery')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._check_admin(db, actor)
            current = db.execute('SELECT password_hash FROM users WHERE id=?', (actor,)).fetchone()
            if current['password_hash'] != confirmed['password_hash']:
                raise AuthError('Your account changed. Sign in again before continuing.', 409)
            if actor == target:
                raise AuthError('Use My Account to change your own password.', 422)
            if not db.execute('SELECT id FROM users WHERE id=? AND active=1', (target,)).fetchone():
                raise AuthError('Choose an active approved account.', 422)
            return self._issue_recovery(db, target, actor)

    def issue_operator_recovery(self, username):
        # Only the local recovery CLI calls this after connecting with database
        # administrator credentials. There is deliberately no HTTP endpoint.
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id FROM users WHERE username=? AND active=1', (username,)).fetchone()
            if not row:
                raise AuthError('Choose an active approved account.', 422)
            return self._issue_recovery(db, row['id'], None)

    def reset_password(self, username, code, new_password, client):
        self._limit('reset:' + username, 'reset:' + client)
        hashed = PASSWORD_HASHER.hash(new_password)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT u.id,u.active,u.password_hash,r.token_hash,r.expires_at,r.issued_by FROM users u '
                'JOIN password_resets r ON r.user_id=u.id WHERE u.username=?', (username,)).fetchone()
            if not row or not row['active'] or row['expires_at'] <= self.clock() or not hmac.compare_digest(row['token_hash'], digest(code)):
                raise AuthError('The recovery code is invalid or expired. Ask for a new code.', 400)
            try:
                PASSWORD_HASHER.verify(row['password_hash'], new_password)
            except (VerificationError, InvalidHashError):
                pass
            else:
                raise AuthError('Choose a different new password.', 422)
            self._replace_password(db, row['id'], hashed)
            db.execute('DELETE FROM attempts WHERE bucket=?', (digest('user:' + username),))
            self._event(db, row['issued_by'], row['id'], 'reset_password')
        return {'message': 'Your password was reset. Sign in with your new password.'}

    def create_user(self, actor, username, display_name, password, role):
        hashed = PASSWORD_HASHER.hash(password)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_admin(db, actor)
            if db.execute("SELECT id FROM permission WHERE username=? AND status='pending'", (username,)).fetchone():
                raise AuthError("Review the pending account request for this username first.", 409)
            try:
                cursor = db.execute("INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)", (username, display_name, hashed, role, self.clock()))
            except IntegrityError:
                raise AuthError("That username is already in use.", 409) from None
            self._event(db, actor, cursor.lastrowid, "create_user")
            return self.public_user(db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())

    def request_account(self, username, display_name, password, requested_role, request_note, client):
        try:
            self._limit('signup:' + username, 'signup:' + client)
        except AuthError as error:
            if error.status == 429:
                raise AuthError('Too many account requests. Try again in ten minutes.', 429) from None
            raise
        hashed = PASSWORD_HASHER.hash(password)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
                raise AuthError('An administrator must set up the workspace first.', 409)
            if db.execute('SELECT id FROM users WHERE LOWER(username)=?', (username,)).fetchone():
                raise AuthError('That username is already in use.', 409)
            if db.execute("SELECT id FROM permission WHERE username=? AND status='pending'", (username,)).fetchone():
                raise AuthError('A request for that username is already waiting for approval.', 409)
            cursor = db.execute('INSERT INTO permission(username,display_name,password_hash,requested_role,request_note,created_at) VALUES(?,?,?,?,?,?)',
                (username, display_name, hashed, requested_role, request_note, self.clock()))
            return {'id': cursor.lastrowid, 'status': 'pending', 'message': 'Your request was submitted. You can sign in only after an administrator approves it.'}

    @staticmethod
    def public_request(row):
        return {key: row[key] for key in ('id', 'username', 'display_name', 'requested_role', 'request_note',
            'status', 'created_at', 'reviewed_at', 'reviewed_by', 'approved_user_id', 'granted_role', 'review_note')}

    def list_requests(self, actor, status, offset, limit):
        with self.db() as db:
            self._check_admin(db, actor)
            total = db.execute('SELECT COUNT(*) FROM permission WHERE status=?', (status,)).fetchone()[0]
            items = [self.public_request(row) for row in db.execute('SELECT * FROM permission WHERE status=? ORDER BY created_at,id LIMIT ? OFFSET ?', (status, limit, offset))]
            return {'items': items, 'total': total, 'offset': offset, 'limit': limit}

    def request_summary(self, actor):
        with self.db() as db:
            self._check_admin(db, actor)
            row = db.execute("SELECT COUNT(*) AS pending_count, MAX(id) AS latest_pending_id FROM permission WHERE status='pending'").fetchone()
            return {'pending_count': row['pending_count'], 'latest_pending_id': row['latest_pending_id'] or 0}

    def review_request(self, actor, request_id, decision, role, note):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._check_admin(db, actor)
            row = db.execute('SELECT * FROM permission WHERE id=?', (request_id,)).fetchone()
            if not row:
                raise AuthError('Account request not found.', 404)
            if row['status'] != 'pending':
                raise AuthError('This request has already been reviewed. Refresh the list.', 409)
            user_id = None
            if decision == 'approve':
                if not role:
                    raise AuthError('Choose the role to grant before approving.', 422)
                if db.execute('SELECT id FROM users WHERE LOWER(username)=?', (row['username'],)).fetchone():
                    raise AuthError('That username is already in use. Reject this request or resolve the existing account.', 409)
                cursor = db.execute('INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                    (row['username'], row['display_name'], row['password_hash'], role, self.clock()))
                user_id = cursor.lastrowid
                self._event(db, actor, user_id, 'approve_account')
            else:
                self._event(db, actor, None, 'reject_account')
            db.execute('UPDATE permission SET status=?,password_hash=NULL,reviewed_at=?,reviewed_by=?,approved_user_id=?,granted_role=?,review_note=? WHERE id=?',
                ('approved' if decision == 'approve' else 'rejected', self.clock(), actor, user_id, role if user_id else None, note, request_id))
            return self.public_request(db.execute('SELECT * FROM permission WHERE id=?', (request_id,)).fetchone())

    @staticmethod
    def _check_admin(db, actor):
        row = db.execute("SELECT role,active FROM users WHERE id=?", (actor,)).fetchone()
        if not row or not row["active"] or row["role"] != "admin":
            raise AuthError("Administrator access is required.", 403)

    def list_users(self, actor):
        with self.db() as db:
            self._check_admin(db, actor)
            return [self.public_user(row) for row in db.execute("SELECT * FROM users ORDER BY username")]

    def update_access(self, actor, user_id, role, active):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_admin(db, actor)
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise AuthError("Account not found.", 404)
            if row["role"] == "admin" and row["active"] and (role != "admin" or not active):
                count = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
                if count <= 1:
                    raise AuthError("Keep at least one active administrator.", 409)
            if actor == user_id and (role != "admin" or not active):
                raise AuthError("Use another administrator account to change your own access.", 409)
            if role != row["role"] or bool(row["active"]) != active:
                db.execute("UPDATE users SET role=?,active=? WHERE id=?", (role, int(active), user_id))
                db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
                db.execute("DELETE FROM password_resets WHERE user_id=?", (user_id,))
                self._event(db, actor, user_id, "change_access")
            return self.public_user(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def save_preferences(self, user_id, display_name, preferred_model, page_size, replay_step):
        with self.db() as db:
            db.execute("UPDATE users SET display_name=?,preferred_model=?,page_size=?,replay_step=? WHERE id=? AND active=1",
                       (display_name, preferred_model, page_size, replay_step, user_id))
            row = db.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
            if not row:
                raise AuthError("Your account is unavailable.", 401)
            return self.public_user(row)


_STORE = None
_STORE_LOCK = Lock()


def get_auth_store():
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            location = os.environ.get("SILENT_WINDOW_DATABASE_URL")
            if not location:
                raise RuntimeError("MySQL is not configured. Run the Silent Window database setup.")
            if not location.startswith('mysql+pymysql://'):
                raise RuntimeError('The website requires MySQL. SQLite is reserved for isolated tests.')
            _STORE = AuthStore(location)
    return _STORE
