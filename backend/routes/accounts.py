"""First local setup, sign-in/out, account management and saved preferences."""
import os
import re
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.auth import current_user, require_admin, require_write, trusted_origin
from backend.permissions import Role
from backend.services.auth_service import ABSOLUTE_TTL, COOKIE_NAME, AuthError, get_auth_store

router = APIRouter(tags=["accounts"])


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginBody(StrictBody):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize(cls, value):
        return value.lower()


class SetupBody(LoginBody):
    display_name: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=15, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def new_username(cls, value):
        # New accounts follow the rule; existing usernames remain valid at sign-in.
        if isinstance(value, str) and not re.fullmatch(r"[a-z][a-z0-9]{2,31}", value):
            raise ValueError("Use 3–32 characters, starting with a lowercase letter, with lowercase letters and optional numbers only.")
        return value

    @field_validator("display_name")
    @classmethod
    def display(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Enter a name with at least two characters")
        return value


class CreateBody(SetupBody):
    role: Role = "researcher"


class SignupBody(SetupBody):
    requested_role: Literal['doctor', 'nurse', 'coordinator', 'researcher']
    request_note: str = Field(default='', max_length=500)


class ReviewBody(StrictBody):
    decision: Literal['approve', 'reject']
    role: Role | None = None
    note: str = Field(default='', max_length=500)


class AccessBody(StrictBody):
    role: Role
    active: bool


class PreferencesBody(StrictBody):
    display_name: str = Field(min_length=2, max_length=60)
    preferred_model: Literal["original", "calibrated", "expanded"]
    page_size: Literal[25, 50, 100]
    replay_step: Literal[15, 60, 180]

    @field_validator("display_name")
    @classmethod
    def display(cls, value):
        return SetupBody.display(value)


class ChangePasswordBody(StrictBody):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=15, max_length=128)


class RecoveryBody(StrictBody):
    current_password: str = Field(min_length=1, max_length=128)


class ResetPasswordBody(LoginBody):
    password: str = Field(min_length=15, max_length=128)
    recovery_code: str = Field(min_length=43, max_length=43, pattern=r'^[A-Za-z0-9_-]+$')


def auth_call(function, *args):
    try:
        return function(*args)
    except AuthError as error:
        raise HTTPException(error.status, str(error)) from None


def session_response(response, token, principal):
    response.set_cookie(COOKIE_NAME, token, max_age=ABSOLUTE_TTL, httponly=True,
                        secure=os.environ.get("SILENT_WINDOW_SECURE_COOKIES") == "1", samesite="strict", path="/api")
    response.headers["Cache-Control"] = "no-store"
    return {"user": principal.user, "csrf_token": principal.csrf_token}


@router.get("/auth/status")
def status(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"setup_required": get_auth_store().setup_required()}


@router.post("/auth/setup")
def setup(body: SetupBody, request: Request, response: Response):
    trusted_origin(request)
    if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "First setup must be completed on this laptop.")
    store = get_auth_store()
    if not store.setup_required():
        raise HTTPException(409, "Setup is already complete. Sign in instead.")
    auth_call(store._limit, "bootstrap", request.client.host)
    token, principal = auth_call(store.setup, body.username, body.display_name, body.password)
    return session_response(response, token, principal)


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response):
    trusted_origin(request)
    token, principal = auth_call(get_auth_store().login, body.username, body.password, request.client.host if request.client else "unknown")
    return session_response(response, token, principal)


@router.get("/auth/me")
def me(response: Response, principal=Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    return {"user": principal.user, "csrf_token": principal.csrf_token}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, principal=Depends(require_write)):
    get_auth_store().logout(request.cookies[COOKIE_NAME])
    response.delete_cookie(COOKIE_NAME, path="/api", httponly=True, samesite="strict")


@router.patch("/account/preferences")
def preferences(body: PreferencesBody, principal=Depends(require_write)):
    return auth_call(get_auth_store().save_preferences, principal.user["id"], body.display_name,
                     body.preferred_model, body.page_size, body.replay_step)


@router.post('/account/password')
def change_password(body: ChangePasswordBody, response: Response, principal=Depends(require_write)):
    result = auth_call(get_auth_store().change_password, principal.user['id'], body.current_password, body.new_password)
    response.delete_cookie(COOKIE_NAME, path='/api', httponly=True, samesite='strict')
    return result


@router.post('/accounts/{user_id}/password-recovery')
def issue_recovery(user_id: int, body: RecoveryBody, principal=Depends(require_admin)):
    return auth_call(get_auth_store().issue_recovery, principal.user['id'], user_id, body.current_password)


@router.post('/auth/reset-password')
def reset_password(body: ResetPasswordBody, request: Request):
    trusted_origin(request)
    return auth_call(get_auth_store().reset_password, body.username, body.recovery_code, body.password,
        request.client.host if request.client else 'unknown')


@router.get("/accounts")
def users(principal=Depends(current_user)):
    if principal.user["role"] != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return auth_call(get_auth_store().list_users, principal.user["id"])


@router.post("/accounts", status_code=201)
def create(body: CreateBody, principal=Depends(require_admin)):
    raise HTTPException(410, 'Direct account creation has been replaced by administrator approval of worker requests.')


@router.post('/auth/register', status_code=202)
def register(body: SignupBody, request: Request):
    trusted_origin(request)
    return auth_call(get_auth_store().request_account, body.username, body.display_name, body.password,
        body.requested_role, body.request_note.strip(), request.client.host if request.client else 'unknown')


@router.get('/permissions')
def permission_requests(status: Literal['pending', 'approved', 'rejected'] = 'pending',
    offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100), principal=Depends(current_user)):
    return auth_call(get_auth_store().list_requests, principal.user['id'], status, offset, limit)


@router.get('/permissions/summary')
def permission_summary(principal=Depends(current_user)):
    return auth_call(get_auth_store().request_summary, principal.user['id'])


@router.post('/permissions/{request_id}/review')
def review(request_id: int, body: ReviewBody, principal=Depends(require_admin)):
    return auth_call(get_auth_store().review_request, principal.user['id'], request_id, body.decision, body.role, body.note.strip())


@router.patch("/accounts/{user_id}")
def access(user_id: int, body: AccessBody, principal=Depends(require_admin)):
    return auth_call(get_auth_store().update_access, principal.user["id"], user_id, body.role, body.active)
