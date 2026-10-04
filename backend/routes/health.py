"""Safe application and inference readiness endpoint."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from ml.checkpoint_profiles import MODEL_PROFILES, profile_cutoffs

from backend.services.patient_service import (
    EXPECTED_CUTOFFS,
    MODEL_FAMILY,
    PRIMARY_CHECKPOINT,
    get_patient_inference_service,
)


router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    """Public readiness metadata with no paths or patient information."""

    status: Literal["ok", "degraded"]
    api: Literal["online"]
    models: Literal["ready", "unavailable"]
    patient_data: Literal["available", "unavailable"]
    model_family: Literal["Random Forest V2", "Calibrated Random Forest V3", "Calibrated Random Forest V4"]
    primary_checkpoint: Literal["12h"]
    supported_checkpoints: list[Literal["6h", "9h", "12h", "18h", "24h"]]


@router.get("/health", response_model=HealthStatus)
def get_health(model_profile: Literal["original", "calibrated", "expanded"] = "original") -> HealthStatus:
    """Report readiness without predictions or patient-data loading."""
    try:
        service = get_patient_inference_service() if model_profile == "original" else get_patient_inference_service(model_profile)
        models_ready = service.models_ready
        patient_data_available = service.patient_data_available
    except Exception:
        models_ready = False
        patient_data_available = False

    return HealthStatus(
        status=(
            "ok" if models_ready and patient_data_available else "degraded"
        ),
        api="online",
        models="ready" if models_ready else "unavailable",
        patient_data=(
            "available" if patient_data_available else "unavailable"
        ),
        model_family=MODEL_PROFILES[model_profile]["model_family"],
        primary_checkpoint=PRIMARY_CHECKPOINT,
        supported_checkpoints=list(profile_cutoffs(model_profile)),
    )
