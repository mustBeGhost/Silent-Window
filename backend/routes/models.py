"""Public research model descriptions, without paths or patient predictions."""

from typing import Literal

from fastapi import APIRouter, Depends
from backend.auth import current_user
from pydantic import BaseModel

from backend.services.patient_service import InferenceConfigurationError, get_patient_inference_service
from ml.checkpoint_profiles import MODEL_PROFILES, profile_cutoffs


router = APIRouter(tags=["models"], dependencies=[Depends(current_user)])


class ModelOption(BaseModel):
    id: Literal["original", "calibrated", "expanded"]
    label: str
    model_family: str
    description: str
    available: bool
    medium_threshold: float | None
    high_threshold: float | None


@router.get("/models", response_model=list[ModelOption])
def list_models():
    options = []
    for profile_id, profile in MODEL_PROFILES.items():
        available, medium, high = False, None, None
        try:
            service = get_patient_inference_service(profile_id)
            available = service.models_ready
            if available:
                medium, high = service.medium_threshold, service.high_threshold
        except InferenceConfigurationError:
            pass
        options.append(ModelOption(
            id=profile_id, label=profile["label"], model_family=profile["model_family"],
            description=profile["description"], available=available,
            medium_threshold=medium, high_threshold=high,
        ))
    return options
