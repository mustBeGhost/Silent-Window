"""Patient summary and detail API schemas."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


Checkpoint = Literal["6h", "9h", "12h", "18h", "24h"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]
AlertState = Literal["NO_ALERT", "WATCH", "HIGH_ALERT"]
VitalName = Literal["HR", "MAP", "GCS", "Creatinine"]
GlobalIndexState = Literal["not_started", "building", "ready", "failed"]
AssessmentStatus = Literal["READY", "INSUFFICIENT_DATA", "NOT_YET_AVAILABLE"]


class AssessmentResult(BaseModel):
    """A missing assessment is never represented by a zero or LOW score."""

    assessment_status: AssessmentStatus = "READY"
    assessment_reason: str | None = None
    temporal_observation_count: int = Field(ge=0)
    risk_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_level: RiskLevel | None = None
    alert_state: AlertState | None = None

    @model_validator(mode="after")
    def validate_assessment(self):
        results = (self.risk_probability, self.risk_level, self.alert_state)
        if self.assessment_status == "READY":
            if any(value is None for value in results):
                raise ValueError("A ready assessment must contain a score and alert")
            if self.temporal_observation_count == 0 or self.assessment_reason is not None:
                raise ValueError("A ready assessment needs observations and no unavailable reason")
        elif any(value is not None for value in results):
            raise ValueError("An unavailable assessment cannot contain a score or alert")
        elif not self.assessment_reason:
            raise ValueError("An unavailable assessment must explain why")
        elif self.temporal_observation_count != 0:
            raise ValueError("An unavailable assessment must have zero usable observations")
        return self


class PatientSummary(AssessmentResult):
    """Primary 12-hour model summary for one cohort patient."""

    patient_id: str
    icu_type: str
    checkpoint: Literal["12h"]
    risk_trend: Literal["Rising", "Stable", "Falling"] | None


class AssessmentCounts(BaseModel):
    """Complete-cohort counts used by the All Patients summary cards."""

    high_risk: int = Field(ge=0)
    watch: int = Field(ge=0)
    no_alert: int = Field(ge=0)
    not_assessed: int = Field(default=0, ge=0)


class PatientPage(BaseModel):
    """Paginated patient summaries with explicit result-scope metadata."""

    items: list[PatientSummary]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    cohort_total: int = Field(ge=0)
    cached_assessments: int = Field(ge=0)
    result_scope: Literal[
        "cohort",
        "cached_assessments",
        "complete_assessment_index",
    ]
    assessment_counts: AssessmentCounts | None = None


class GlobalIndexStatus(BaseModel):
    """Safe progress state for explicit complete-cohort preparation."""

    state: GlobalIndexState
    total_patients: int = Field(ge=0)
    completed_patients: int = Field(ge=0)
    message: str


class RiskTrajectoryPoint(AssessmentResult):
    """Risk and prefix-only alert state at one supported checkpoint."""

    checkpoint: Checkpoint


class VitalMeasurement(BaseModel):
    """One observed, non-interpolated measurement."""

    time_minutes: int = Field(ge=0, le=1440)
    value: float


class VitalSeries(BaseModel):
    """Chronological observations for one supported vital."""

    parameter: VitalName
    measurements: list[VitalMeasurement]


class PatientDetail(AssessmentResult):
    """Chronology-safe model trajectory and selected observation history."""

    patient_id: str
    icu_type: str
    primary_checkpoint: Literal["12h"]
    available_through_minutes: int = Field(default=1440, ge=0, le=1440)
    risk_trend: Literal["Rising", "Stable", "Falling"] | None
    risk_trajectory: list[RiskTrajectoryPoint]
    vital_histories: list[VitalSeries]
