"""Patient inference endpoints for the full cohort."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from backend.auth import patient_access, require_patients, require_unit_write
from backend.permissions import UNIT_ROLES
from backend.services.assigned_patients import assigned_ids, assigned_page

from backend.schemas.patient import (
    AlertState,
    GlobalIndexStatus,
    PatientDetail,
    PatientPage,
    RiskLevel,
)
from backend.services.patient_service import (
    GlobalIndexNotReadyError,
    InferenceConfigurationError,
    PatientNotFoundError,
    PatientInferenceError,
    get_patient_inference_service,
)


router = APIRouter(tags=["patients"], dependencies=[Depends(require_patients)])
ModelProfile = Literal["original", "calibrated", "expanded"]


def selected_service(model_profile: ModelProfile):
    try:
        return get_patient_inference_service() if model_profile == "original" else get_patient_inference_service(model_profile)
    except InferenceConfigurationError as exc:
        raise HTTPException(status_code=503, detail="Selected research model is unavailable") from exc


@router.get("/patients", response_model=PatientPage)
def list_patients(
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    search: Annotated[str | None, Query(max_length=32)] = None,
    risk: RiskLevel | None = None,
    alert: AlertState | None = None,
    scope: Literal["page", "all"] = "page",
    sort_by: Literal["patient_id"] = "patient_id",
    sort_order: Literal["asc", "desc"] = "asc",
    model_profile: ModelProfile = "original",
    principal=Depends(require_patients),
) -> PatientPage:
    """Return a responsive page of real RF V2 patient summaries."""
    try:
        service = selected_service(model_profile)
        response.headers["X-Silent-Window-Model"] = service.model_profile
        if principal.user["role"] not in UNIT_ROLES:
            return assigned_page(service, principal.user["id"], page=page, page_size=page_size,
                                 search=search, risk=risk, alert=alert, scope=scope, sort_order=sort_order)
        return service.get_patient_page(
            page=page,
            page_size=page_size,
            search=search,
            risk=risk,
            alert=alert,
            scope=scope,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except GlobalIndexNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail="Complete patient assessments are not ready",
        ) from exc
    except PatientInferenceError as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to process patient data",
        ) from exc


@router.get(
    "/patients/global-index/status",
    response_model=GlobalIndexStatus,
)
def get_global_index_status(response: Response, model_profile: ModelProfile = "original", principal=Depends(require_patients)) -> GlobalIndexStatus:
    """Return global-index state without starting complete-cohort work."""
    service = selected_service(model_profile)
    response.headers["X-Silent-Window-Model"] = service.model_profile
    if principal.user["role"] not in UNIT_ROLES:
        total = len(assigned_ids(principal.user["id"]))
        return GlobalIndexStatus(state="ready", total_patients=total, completed_patients=total,
                                 message="Assigned patient assessments are available on demand.")
    return service.get_global_index_status()


@router.post(
    "/patients/global-index/prepare",
    response_model=GlobalIndexStatus,
    status_code=202,
)
def prepare_global_index(response: Response, model_profile: ModelProfile = "original", principal=Depends(require_unit_write)) -> GlobalIndexStatus:
    """Explicitly start one background complete-cohort preparation."""
    service = selected_service(model_profile)
    response.headers["X-Silent-Window-Model"] = service.model_profile
    return service.prepare_global_index()


@router.get("/patients/{patient_id}", response_model=PatientDetail)
def get_patient(
    patient_id: str,
    response: Response,
    as_of_minutes: Annotated[int, Query(ge=0, le=1440)] = 1440,
    model_profile: ModelProfile = "original",
    principal=Depends(require_patients),
) -> PatientDetail:
    """Return one patient's chronology-safe model detail."""
    try:
        patient_access(principal, patient_id)
        service = selected_service(model_profile)
        response.headers["X-Silent-Window-Model"] = service.model_profile
        return service.get_patient_detail(
            patient_id, as_of_minutes=as_of_minutes,
        )
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc
    except PatientInferenceError as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to process patient data",
        ) from exc
