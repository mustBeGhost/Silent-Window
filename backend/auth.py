"""Cookie authentication, CSRF checks and shared authorization dependencies."""
import hmac
import re
from fastapi import Depends, HTTPException, Request
from backend.permissions import PATIENT_ROLES, UNIT_ROLES
from backend.services.auth_service import COOKIE_NAME, AuthError, get_auth_store

TRUSTED_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


def trusted_origin(request: Request):
    origin = request.headers.get("origin")
    if origin is not None and origin not in TRUSTED_ORIGINS:
        raise HTTPException(403, "This request came from an untrusted site.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site account requests are blocked.")


def current_user(request: Request):
    try:
        return get_auth_store().authenticate(request.cookies.get(COOKIE_NAME))
    except AuthError as error:
        raise HTTPException(error.status, str(error)) from None


def require_write(request: Request, principal=Depends(current_user)):
    trusted_origin(request)
    supplied = request.headers.get("X-CSRF-Token", "")
    if not re.fullmatch(r"[a-f0-9]{64}", supplied) or not hmac.compare_digest(supplied, principal.csrf_token):
        raise HTTPException(403, "The security token is missing or expired. Reload and try again.")
    return principal


def require_admin(principal=Depends(require_write)):
    if principal.user["role"] != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return principal


def require_patients(principal=Depends(current_user)):
    if principal.user["role"] not in PATIENT_ROLES:
        raise HTTPException(403, "This role can view research results, not individual patients.")
    return principal


def require_unit_write(principal=Depends(require_write)):
    if principal.user["role"] not in UNIT_ROLES:
        raise HTTPException(403, "Administrator or ICU coordinator access is required.")
    return principal


def patient_access(principal, patient_id):
    if principal.user["role"] in UNIT_ROLES:
        return
    if principal.user["role"] not in PATIENT_ROLES:
        raise HTTPException(403, "Patient access is not allowed for this role.")
    with get_auth_store().db() as db:
        assigned = db.execute("SELECT 1 FROM assignments WHERE patient_id=? AND user_id=?", (patient_id, principal.user["id"])).fetchone()
    if not assigned:
        raise HTTPException(403, "This patient is not assigned to you.")
