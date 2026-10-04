"""Chronology-safe RF V2 inference for all dataset patients."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV
import sklearn

from backend.schemas.patient import (
    AssessmentCounts,
    GlobalIndexStatus,
    PatientDetail,
    PatientPage,
    PatientSummary,
    RiskTrajectoryPoint,
    VitalMeasurement,
    VitalSeries,
)
from ml.alert_policy import probabilities_to_alert_timeline
from ml.coverage import COVERAGE_POLICY, usable_temporal_counts
from ml.checkpoint_profiles import MODEL_PROFILES, profile_cutoffs
from ml.data_loader import discover_patient_ids, get_patient_dir, load_patient
from ml.features import build_feature_matrix, get_feature_columns_v2
from ml.preprocessing import observations_up_to, preprocess_patient


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / "ml" / "artifacts"
DEFAULT_GLOBAL_INDEX_PATH = (
    PROJECT_ROOT / "data" / "processed" / "runtime"
    / "patient_assessment_index.json"
)
MANIFEST_FILENAME = "rf_v2_manifest.json"
GLOBAL_INDEX_SCHEMA_VERSION = 2
GLOBAL_INDEX_BATCH_SIZE = 100

EXPECTED_ARTIFACT_FILENAMES = {
    "6h": "rf_v2_6h.joblib",
    "12h": "rf_v2_12h.joblib",
    "24h": "rf_v2_24h.joblib",
}
EXPECTED_CUTOFFS = {"6h": 360, "12h": 720, "24h": 1440}
PRIMARY_CHECKPOINT = "12h"
MODEL_FAMILY = "Random Forest V2"
EXPECTED_FEATURE_COUNT = 132

# Preserve the public identities already used by the original demo while
# assigning every other dataset patient a deterministic ID below.
PRESERVED_PUBLIC_ID_RECORDS: dict[str, int] = {
    "ICU-1001": 132539,
    "ICU-1002": 135083,
    "ICU-1003": 137583,
    "ICU-1004": 140009,
    "ICU-1005": 142673,
}

ICU_TYPE_LABELS = {
    1: "CCU",
    2: "CSRU",
    3: "MICU",
    4: "SICU",
}

VITAL_PARAMETERS = ("HR", "MAP", "GCS", "Creatinine")

# Presentation-only rule: changes within two percentage points are displayed
# as stable. This is deterministic and is not a clinically validated rule.
TREND_STABLE_DELTA = 0.02


def build_patient_id_mapping() -> tuple[dict[str, int], dict[int, str]]:
    """Build a deterministic, label-independent opaque-ID mapping.

    Keeps the five existing public IDs stable, then assigns ``ICU-{n}``
    identifiers from 1006 onward to remaining files in ascending numeric
    RecordID order. Selection does not depend on target labels.
    """
    sorted_record_ids = sorted(discover_patient_ids())
    record_id_set = set(sorted_record_ids)
    preserved_record_ids = set(PRESERVED_PUBLIC_ID_RECORDS.values())
    if not preserved_record_ids <= record_id_set:
        raise InferenceConfigurationError(
            "Dataset is missing a preserved public patient mapping"
        )

    opaque_to_record = dict(PRESERVED_PUBLIC_ID_RECORDS)
    remaining_record_ids = [
        record_id
        for record_id in sorted_record_ids
        if record_id not in preserved_record_ids
    ]
    for public_number, record_id in zip(
        range(1006, 1001 + len(sorted_record_ids)),
        remaining_record_ids,
        strict=True,
    ):
        opaque_id = f"ICU-{public_number}"
        opaque_to_record[opaque_id] = record_id
    record_to_opaque = {
        record_id: opaque_id
        for opaque_id, record_id in opaque_to_record.items()
    }
    return opaque_to_record, record_to_opaque


class InferenceConfigurationError(RuntimeError):
    """Raised when deployment artifacts cannot be safely initialized."""


class PatientNotFoundError(LookupError):
    """Raised when an opaque ID is not in the patient cohort."""


class PatientInferenceError(RuntimeError):
    """Raised when source data cannot be safely processed."""


class GlobalIndexNotReadyError(PatientInferenceError):
    """Raised when a complete-cohort query is requested before READY."""


class PatientInferenceService:
    """Load RF V2 models once and serve historical inference for all patients."""

    def __init__(
        self,
        artifact_dir: Path | None = None,
        global_index_path: Path | None = None,
        *, model_profile: str = "original",
    ) -> None:
        if model_profile not in MODEL_PROFILES:
            raise InferenceConfigurationError("Unknown model profile")
        self.model_profile = model_profile
        self.cutoffs = profile_cutoffs(model_profile)
        profile = MODEL_PROFILES[model_profile]
        self.model_family = profile["model_family"]
        self.manifest_filename = profile["manifest_filename"]
        self.artifact_filenames = profile["filenames"]
        self.artifact_dir = Path(artifact_dir) if artifact_dir is not None else DEFAULT_ARTIFACT_DIR / profile["directory"]
        default_index = DEFAULT_GLOBAL_INDEX_PATH if model_profile == "original" else DEFAULT_GLOBAL_INDEX_PATH.with_name(f"patient_assessment_index_{model_profile}.json")
        self.global_index_path = Path(global_index_path) if global_index_path is not None else default_index
        self.feature_columns = get_feature_columns_v2()
        self.manifest = self._load_and_validate_manifest()
        self.medium_threshold, self.high_threshold = self._risk_thresholds()
        self.models, self.positive_class_indices = self._load_models()

        # Deterministic opaque-ID mapping for the full cohort.
        self._opaque_to_record, self._record_to_opaque = (
            build_patient_id_mapping()
        )

        # Lazy caches — populated only for requested patients.
        self._summary_cache: dict[str, PatientSummary] = {}
        self._detail_cache: dict[str, PatientDetail] = {}
        self._summary_cache_lock = Lock()
        self._detail_cache_lock = Lock()

        # A complete assessment index is separate from the lazy page cache.
        # It becomes available only after exact-cohort validation succeeds.
        self._global_index: dict[str, PatientSummary] | None = None
        self._global_index_state = "not_started"
        self._global_index_completed = 0
        self._global_index_message = (
            "Complete assessment index has not been prepared."
        )
        self._global_index_lock = Lock()
        self._global_index_thread: Thread | None = None
        self._load_persisted_global_index()

    # -- manifest / model loading --------------------------------------------

    def _load_and_validate_manifest(self) -> dict[str, Any]:
        manifest_path = self.artifact_dir / self.manifest_filename
        if not manifest_path.is_file():
            raise InferenceConfigurationError(
                f"RF V2 manifest not found: {manifest_path}"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InferenceConfigurationError(
                f"Unable to read RF V2 manifest: {manifest_path}"
            ) from exc

        if not isinstance(manifest, dict):
            raise InferenceConfigurationError("Model manifest must be a JSON object")
        if manifest.get("feature_version") != "V2":
            raise InferenceConfigurationError(
                "RF artifact manifest feature_version must be V2"
            )
        if len(self.feature_columns) != EXPECTED_FEATURE_COUNT:
            raise InferenceConfigurationError(
                "Runtime V2 feature generator does not produce 132 features"
            )
        if manifest.get("feature_count") != EXPECTED_FEATURE_COUNT:
            raise InferenceConfigurationError(
                "RF artifact manifest feature_count must be 132"
            )
        if manifest.get("ordered_input_features") != self.feature_columns:
            raise InferenceConfigurationError(
                "RF artifact manifest feature order does not match runtime V2"
            )
        if manifest.get("supported_cutoffs") != self.cutoffs:
            raise InferenceConfigurationError(
                "RF artifact manifest cutoffs do not match the selected profile"
            )
        if manifest.get("primary_cutoff") != PRIMARY_CHECKPOINT:
            raise InferenceConfigurationError(
                "RF artifact manifest primary cutoff must be 12h"
            )

        artifact_entries = manifest.get("artifacts")
        if not isinstance(artifact_entries, dict):
            raise InferenceConfigurationError(
                "RF artifact manifest is missing artifact entries"
            )
        manifest_filenames = {
            label: entry.get("filename")
            for label, entry in artifact_entries.items()
            if isinstance(entry, dict)
        }
        if manifest_filenames != self.artifact_filenames:
            raise InferenceConfigurationError(
                "RF artifact filenames do not match the deployment set"
            )
        if self.model_profile in {"calibrated", "expanded"}:
            if (
                manifest.get("model_profile") != self.model_profile
                or manifest.get("bundle_version") != ("expanded_rf_v4" if self.model_profile == "expanded" else "calibrated_rf_v3")
                or manifest.get("status") != "RESEARCH_CANDIDATE_NOT_CLINICALLY_VALIDATED"
                or manifest.get("target") != "In-hospital_death"
                or manifest.get("coverage_policy") != COVERAGE_POLICY
                or manifest.get("calibration") != {"method": "sigmoid", "cv_splits": 3, "ensemble": False, "random_state": 42}
                or manifest.get("runtime_versions", {}).get("sklearn") != sklearn.__version__
            ):
                raise InferenceConfigurationError("Calibrated research manifest is incompatible with this runtime")
        if self.model_profile == "expanded":
            if manifest.get("threshold_selection", {}).get("engineering_recall_floor") != 0.85 or manifest.get("separated_patients_evaluated") != 0:
                raise InferenceConfigurationError("Expanded research protocol mismatch")
            for group in ("source_sha256", "evaluation_evidence_sha256"):
                hashes = manifest.get(group)
                if not isinstance(hashes, dict) or not hashes:
                    raise InferenceConfigurationError("Expanded research provenance is missing")
                for name, digest in hashes.items():
                    path = (PROJECT_ROOT / name.replace('\\', '/')).resolve()
                    if not path.is_relative_to(PROJECT_ROOT) or not path.is_file() or self._sha256_file(path) != digest:
                        raise InferenceConfigurationError("Expanded research provenance mismatch")
        return manifest

    def _risk_thresholds(self) -> tuple[float, float]:
        boundaries = self.manifest.get("risk_boundaries")
        if not isinstance(boundaries, dict):
            raise InferenceConfigurationError(
                "RF artifact manifest is missing risk boundaries"
            )
        try:
            low_values = re.findall(r"\d+(?:\.\d+)?", boundaries["LOW"])
            medium_values = re.findall(
                r"\d+(?:\.\d+)?", boundaries["MEDIUM"]
            )
            high_values = re.findall(r"\d+(?:\.\d+)?", boundaries["HIGH"])
            if (
                len(low_values) != 1
                or len(medium_values) != 2
                or len(high_values) != 1
            ):
                raise ValueError("unexpected boundary format")
            medium_threshold = float(medium_values[0])
            high_threshold = float(medium_values[1])
            if (
                float(low_values[0]) != medium_threshold
                or float(high_values[0]) != high_threshold
                or not 0 <= medium_threshold < high_threshold <= 1
            ):
                raise ValueError("inconsistent boundaries")
        except (KeyError, TypeError, ValueError) as exc:
            raise InferenceConfigurationError(
                "RF artifact manifest risk boundaries are malformed"
            ) from exc
        if self.model_profile in {"calibrated", "expanded"} and self.manifest.get("thresholds") != {"medium": medium_threshold, "high": high_threshold}:
            raise InferenceConfigurationError("Calibrated numeric thresholds disagree with risk boundaries")
        return medium_threshold, high_threshold

    def _load_models(self) -> tuple[dict[str, Any], dict[str, int]]:
        models: dict[str, Any] = {}
        positive_indices: dict[str, int] = {}
        for checkpoint, filename in self.artifact_filenames.items():
            artifact_path = self.artifact_dir / filename
            if not artifact_path.is_file():
                raise InferenceConfigurationError(
                    f"RF V2 artifact not found: {artifact_path}"
                )
            entry = self.manifest["artifacts"][checkpoint]
            if (
                not isinstance(entry.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                or self._sha256_file(artifact_path) != entry["sha256"]
                or artifact_path.stat().st_size != entry.get("size_bytes")
            ):
                raise InferenceConfigurationError(f"Model artifact integrity mismatch: {filename}")
            try:
                model = joblib.load(artifact_path)
            except Exception as exc:
                raise InferenceConfigurationError(
                    f"Unable to load RF V2 artifact: {artifact_path}"
                ) from exc
            if not callable(getattr(model, "predict_proba", None)):
                raise InferenceConfigurationError(
                    f"RF V2 artifact lacks predict_proba: {filename}"
                )
            if list(getattr(model, "feature_names_in_", [])) != (
                self.feature_columns
            ):
                raise InferenceConfigurationError(
                    f"RF V2 artifact feature schema mismatch: {filename}"
                )
            pipeline = model
            if self.model_profile in {"calibrated", "expanded"}:
                if (
                    not isinstance(model, CalibratedClassifierCV)
                    or model.method != "sigmoid" or model.ensemble is not False
                    or len(getattr(model, "calibrated_classifiers_", [])) != 1
                ):
                    raise InferenceConfigurationError(f"Expected one fitted sigmoid research calibrator: {filename}")
                model.n_jobs = 1
                pipeline = model.calibrated_classifiers_[0].estimator
                if list(getattr(pipeline, "feature_names_in_", [])) != self.feature_columns:
                    raise InferenceConfigurationError(f"Calibrated base feature schema mismatch: {filename}")
            elif isinstance(model, CalibratedClassifierCV):
                raise InferenceConfigurationError("Original profile cannot load a calibrated candidate")
            classifiers = [
                step
                for step in getattr(pipeline, "named_steps", {}).values()
                if isinstance(step, RandomForestClassifier)
            ]
            if len(classifiers) != 1:
                raise InferenceConfigurationError(
                    f"RF V2 artifact must contain one RandomForestClassifier: {filename}"
                )
            classifier = classifiers[0]
            # Artifacts were trained and saved with n_jobs=-1. Inference is
            # deterministic with one worker and avoids Windows named-pipe
            # permissions required by joblib's runtime worker pool.
            classifier.n_jobs = 1
            classes = list(getattr(model, "classes_", []))
            if len(classes) != 2 or set(classes) != {0, 1}:
                raise InferenceConfigurationError(
                    f"RF V2 artifact lacks positive class 1: {filename}"
                )
            models[checkpoint] = model
            positive_indices[checkpoint] = classes.index(1)
        return models, positive_indices

    # -- public query interface -----------------------------------------------

    @property
    def patient_count(self) -> int:
        """Return the number of patients in the cohort."""
        return len(self._opaque_to_record)

    @property
    def models_ready(self) -> bool:
        """Return whether every validated runtime model remains loaded."""
        expected = set(self.artifact_filenames)
        return (
            set(self.models) == expected
            and set(self.positive_class_indices) == expected
            and all(
                callable(getattr(self.models[label], "predict_proba", None))
                for label in expected
            )
        )

    @property
    def patient_data_available(self) -> bool:
        """Check the initialized cohort's data source without loading patients."""
        first_record_id = next(iter(self._record_to_opaque), None)
        if first_record_id is None:
            return False
        try:
            return (get_patient_dir() / f"{first_record_id}.txt").is_file()
        except (FileNotFoundError, OSError):
            return False

    def get_global_index_status(self) -> GlobalIndexStatus:
        """Return safe complete-index state without starting preparation."""
        with self._global_index_lock:
            return self._global_index_status_unlocked()

    def prepare_global_index(self) -> GlobalIndexStatus:
        """Start one explicit background build unless ready or in progress."""
        with self._global_index_lock:
            if self._global_index_state in {"building", "ready"}:
                return self._global_index_status_unlocked()

            self._global_index_state = "building"
            self._global_index_completed = 0
            self._global_index_message = (
                "Preparing complete patient assessment index."
            )
            worker = Thread(
                target=self._run_global_index_build,
                name="silent-window-global-index",
                daemon=True,
            )
            self._global_index_thread = worker
            try:
                worker.start()
            except Exception:
                self._global_index_thread = None
                self._global_index_state = "failed"
                self._global_index_message = (
                    "Complete assessment index preparation failed."
                )
            return self._global_index_status_unlocked()

    def get_global_index_summaries(self) -> list[PatientSummary]:
        """Return a stable copy of the complete READY index for later queries."""
        with self._global_index_lock:
            if (
                self._global_index_state != "ready"
                or self._global_index is None
            ):
                raise PatientInferenceError(
                    "Complete assessment index is not ready"
                )
            return [
                self._global_index[patient_id]
                for patient_id in sorted(
                    self._global_index,
                    key=self._public_id_number,
                )
            ]

    def get_patient_page(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        risk: str | None = None,
        alert: str | None = None,
        scope: str = "page",
        sort_by: str = "patient_id",
        sort_order: str = "asc",
    ) -> PatientPage:
        """Return a page-scoped or complete-index patient result.

        ``scope=page`` preserves the responsive lazy-cache behavior used by
        the ordinary dashboard. ``scope=all`` reads only the validated READY
        complete assessment index and never performs inference or falls back
        to the lazy summary cache.
        """
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("Invalid pagination values")
        if sort_by != "patient_id" or sort_order not in {"asc", "desc"}:
            raise ValueError("Unsupported patient sort")
        if scope not in {"page", "all"}:
            raise ValueError("Unsupported patient scope")

        if scope == "all":
            return self._get_complete_index_page(
                page=page,
                page_size=page_size,
                search=search,
                risk=risk,
                alert=alert,
                sort_order=sort_order,
            )

        normalized_search = (search or "").strip().upper()
        public_ids = list(self._opaque_to_record)
        if normalized_search:
            public_ids = [
                patient_id
                for patient_id in public_ids
                if normalized_search in patient_id.upper()
            ]
        public_ids.sort(
            key=self._public_id_number,
            reverse=sort_order == "desc",
        )

        uses_assessment_filter = risk is not None or alert is not None
        if uses_assessment_filter:
            # An exact public-ID search remains useful on a cold process and
            # scores only that one requested patient.
            if (
                normalized_search in self._opaque_to_record
                and len(public_ids) == 1
            ):
                self.get_patient_summary(normalized_search)
            with self._summary_cache_lock:
                cached = dict(self._summary_cache)
            filtered_ids = []
            for patient_id in public_ids:
                summary = cached.get(patient_id)
                if summary is None:
                    continue
                if risk is not None and summary.risk_level != risk:
                    continue
                if alert is not None and summary.alert_state != alert:
                    continue
                filtered_ids.append(patient_id)
            total = len(filtered_ids)
            page_ids = self._page_slice(filtered_ids, page, page_size)
            items = [cached[patient_id] for patient_id in page_ids]
            result_scope = "cached_assessments"
        else:
            total = len(public_ids)
            page_ids = self._page_slice(public_ids, page, page_size)
            items = self._get_patient_summaries(page_ids)
            result_scope = "cohort"

        with self._summary_cache_lock:
            cached_assessments = len(self._summary_cache)
        return PatientPage(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=math.ceil(total / page_size),
            cohort_total=self.patient_count,
            cached_assessments=cached_assessments,
            result_scope=result_scope,
        )

    def _get_complete_index_page(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        risk: str | None,
        alert: str | None,
        sort_order: str,
    ) -> PatientPage:
        """Filter one stable complete-index snapshot before pagination."""
        try:
            complete = self.get_global_index_summaries()
        except PatientInferenceError as exc:
            raise GlobalIndexNotReadyError(
                "Complete assessment index is not ready"
            ) from exc

        assessment_counts = AssessmentCounts(
            high_risk=sum(item.risk_level == "HIGH" for item in complete),
            watch=sum(item.alert_state == "WATCH" for item in complete),
            no_alert=sum(
                item.alert_state == "NO_ALERT" for item in complete
            ),
            not_assessed=sum(item.assessment_status != "READY" for item in complete),
        )
        normalized_search = (search or "").strip().upper()
        matches = [
            item
            for item in complete
            if (
                not normalized_search
                or normalized_search in item.patient_id.upper()
            )
            and (risk is None or item.risk_level == risk)
            and (alert is None or item.alert_state == alert)
        ]
        matches.sort(
            key=lambda item: self._public_id_number(item.patient_id),
            reverse=sort_order == "desc",
        )
        total = len(matches)
        start = (page - 1) * page_size
        items = matches[start : start + page_size]
        with self._summary_cache_lock:
            cached_assessments = len(self._summary_cache)
        return PatientPage(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=math.ceil(total / page_size),
            cohort_total=self.patient_count,
            cached_assessments=cached_assessments,
            result_scope="complete_assessment_index",
            assessment_counts=assessment_counts,
        )

    def get_patient_summary(self, patient_id: str) -> PatientSummary:
        """Return a prefix-safe summary using only 6h and 12h scores."""
        self._record_id(patient_id)
        return self._get_patient_summaries([patient_id])[0]

    def get_patient_detail(
        self, patient_id: str, *, as_of_minutes: int = 1440,
    ) -> PatientDetail:
        """Return the three supported prefix-safe scores and observed vitals."""
        record_id = self._record_id(patient_id)
        if not isinstance(as_of_minutes, int) or not 0 <= as_of_minutes <= 1440:
            raise ValueError("Recorded-data view time must be between 0 and 1440 minutes")
        # Earlier views must never reuse the full-record detail cache.
        if as_of_minutes != 1440:
            return self._compute_detail(patient_id, record_id, as_of_minutes)
        if patient_id in self._detail_cache:
            return self._detail_cache[patient_id]
        with self._detail_cache_lock:
            if patient_id not in self._detail_cache:
                self._detail_cache[patient_id] = self._compute_detail(
                    patient_id, record_id
                )
            return self._detail_cache[patient_id]

    # -- complete assessment index -------------------------------------------

    def _global_index_status_unlocked(self) -> GlobalIndexStatus:
        return GlobalIndexStatus(
            state=self._global_index_state,
            total_patients=self.patient_count,
            completed_patients=self._global_index_completed,
            message=self._global_index_message,
        )

    def _run_global_index_build(self) -> None:
        """Build locally, persist atomically, then publish one complete index."""
        try:
            public_ids = sorted(
                self._opaque_to_record,
                key=self._public_id_number,
            )
            with self._summary_cache_lock:
                cached = dict(self._summary_cache)
            working = {
                patient_id: cached[patient_id]
                for patient_id in public_ids
                if patient_id in cached
                and cached[patient_id].patient_id == patient_id
            }
            missing_ids = [
                patient_id
                for patient_id in public_ids
                if patient_id not in working
            ]
            with self._global_index_lock:
                self._global_index_completed = len(working)

            for start in range(0, len(missing_ids), GLOBAL_INDEX_BATCH_SIZE):
                batch_ids = missing_ids[
                    start : start + GLOBAL_INDEX_BATCH_SIZE
                ]
                working.update(self._compute_summaries(batch_ids))
                with self._global_index_lock:
                    self._global_index_completed = len(working)

            self._validate_complete_global_index(working)
            self._persist_global_index(working)

            # Populate the ordinary cache only after the complete index and
            # its persisted file have both succeeded.
            with self._summary_cache_lock:
                self._summary_cache.update(working)
            with self._global_index_lock:
                self._global_index = dict(working)
                self._global_index_state = "ready"
                self._global_index_completed = self.patient_count
                self._global_index_message = (
                    "Complete patient assessment index is ready."
                )
        except Exception:
            with self._global_index_lock:
                self._global_index_state = "failed"
                self._global_index_message = (
                    "Complete assessment index preparation failed."
                )
        finally:
            with self._global_index_lock:
                self._global_index_thread = None

    def _validate_complete_global_index(
        self,
        index: dict[str, PatientSummary],
    ) -> None:
        expected_ids = set(self._opaque_to_record)
        if len(index) != self.patient_count or set(index) != expected_ids:
            raise ValueError("Assessment index does not cover the cohort")
        if any(
            summary.patient_id != patient_id
            for patient_id, summary in index.items()
        ):
            raise ValueError("Assessment index patient IDs are inconsistent")

    def _global_index_metadata(self) -> dict[str, Any]:
        artifact_hashes = {
            checkpoint: self._sha256_file(
                self.artifact_dir / filename
            )
            for checkpoint, filename in self.artifact_filenames.items()
        }
        return {
            "index_schema_version": GLOBAL_INDEX_SCHEMA_VERSION,
            "model_profile": self.model_profile,
            "expected_cohort_size": self.patient_count,
            "cohort_mapping_sha256": self._sha256_json(
                [
                    [patient_id, self._opaque_to_record[patient_id]]
                    for patient_id in sorted(
                        self._opaque_to_record,
                        key=self._public_id_number,
                    )
                ]
            ),
            "model_manifest_sha256": self._sha256_file(
                self.artifact_dir / self.manifest_filename
            ),
            "model_artifact_sha256": artifact_hashes,
            "feature_version": self.manifest["feature_version"],
            "feature_count": len(self.feature_columns),
            "feature_schema_sha256": self._sha256_json(
                self.feature_columns
            ),
            "feature_source_sha256": self._sha256_file(
                PROJECT_ROOT / "ml" / "features.py"
            ),
            "preprocessing_source_sha256": self._sha256_file(
                PROJECT_ROOT / "ml" / "preprocessing.py"
            ),
            "alert_policy_source_sha256": self._sha256_file(
                PROJECT_ROOT / "ml" / "alert_policy.py"
            ),
            "assessment_service_sha256": self._sha256_file(Path(__file__)),
            "coverage_source_sha256": self._sha256_file(PROJECT_ROOT / "ml" / "coverage.py"),
            "supported_cutoffs": self.cutoffs,
            "primary_checkpoint": PRIMARY_CHECKPOINT,
            "medium_threshold": self.medium_threshold,
            "high_threshold": self.high_threshold,
            "trend_stable_delta": TREND_STABLE_DELTA,
        }

    def _persist_global_index(
        self,
        index: dict[str, PatientSummary],
    ) -> None:
        self._validate_complete_global_index(index)
        payload = {
            "metadata": self._global_index_metadata(),
            "patients": [
                index[patient_id].model_dump(mode="json")
                for patient_id in sorted(index, key=self._public_id_number)
            ],
        }
        self.global_index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.global_index_path.with_name(
            f".{self.global_index_path.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary_path.open("x", encoding="utf-8") as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.global_index_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _load_persisted_global_index(self) -> None:
        if not self.global_index_path.is_file():
            return
        try:
            payload = json.loads(
                self.global_index_path.read_text(encoding="utf-8")
            )
            if not isinstance(payload, dict) or set(payload) != {
                "metadata", "patients",
            }:
                raise ValueError("Unexpected assessment index payload")
            if payload["metadata"] != self._global_index_metadata():
                raise ValueError("Assessment index metadata is stale")
            patient_payloads = payload["patients"]
            if not isinstance(patient_payloads, list):
                raise ValueError("Assessment index patients are malformed")
            allowed_fields = set(PatientSummary.model_fields)
            index: dict[str, PatientSummary] = {}
            for item in patient_payloads:
                if not isinstance(item, dict) or set(item) != allowed_fields:
                    raise ValueError("Assessment index fields are malformed")
                summary = PatientSummary.model_validate(item)
                if summary.patient_id in index:
                    raise ValueError("Assessment index IDs are duplicated")
                index[summary.patient_id] = summary
            self._validate_complete_global_index(index)
        except Exception:
            return

        with self._global_index_lock:
            self._global_index = index
            self._global_index_state = "ready"
            self._global_index_completed = self.patient_count
            self._global_index_message = (
                "Complete patient assessment index is ready."
            )

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _sha256_json(value: Any) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    # -- cache population -----------------------------------------------------

    def _get_patient_summaries(
        self, public_ids: list[str]
    ) -> list[PatientSummary]:
        """Return summaries, atomically caching only successful batches."""
        if not public_ids:
            return []
        with self._summary_cache_lock:
            missing_ids = [
                patient_id
                for patient_id in public_ids
                if patient_id not in self._summary_cache
            ]
            if missing_ids:
                computed = self._compute_summaries(missing_ids)
                self._summary_cache.update(computed)
            return [self._summary_cache[patient_id] for patient_id in public_ids]

    def _compute_summaries(
        self, public_ids: list[str]
    ) -> dict[str, PatientSummary]:
        """Compute one requested summary batch without publishing partial state."""
        record_ids = [
            self._opaque_to_record[public_id] for public_id in public_ids
        ]
        patient_data: dict[int, pd.DataFrame] = {}
        icu_types: dict[int, str] = {}
        for record_id in record_ids:
            patient, icu_type = self._load_patient_context(record_id)
            patient_data[record_id] = patient
            icu_types[record_id] = icu_type

        trajectories = self._score_patient_batch(
            record_ids, patient_data, self._primary_prefix(),
        )

        cache: dict[str, PatientSummary] = {}
        for public_id, record_id in zip(public_ids, record_ids, strict=True):
            trajectory = trajectories[record_id]
            primary = trajectory[-1]
            cache[public_id] = PatientSummary(
                patient_id=public_id,
                icu_type=icu_types[record_id],
                checkpoint="12h",
                **primary.model_dump(exclude={"checkpoint"}),
                risk_trend=self._risk_trend(
                    trajectory[0].risk_probability, primary.risk_probability,
                ),
            )

        return cache

    @staticmethod
    def _page_slice(
        patient_ids: list[str], page: int, page_size: int
    ) -> list[str]:
        start = (page - 1) * page_size
        return patient_ids[start : start + page_size]

    @staticmethod
    def _public_id_number(patient_id: str) -> int:
        return int(patient_id.removeprefix("ICU-"))

    # -- internal inference ---------------------------------------------------

    def _primary_prefix(self) -> tuple[str, ...]:
        return tuple(cp for cp, cutoff in self.cutoffs.items() if cutoff <= self.cutoffs[PRIMARY_CHECKPOINT])

    def _compute_summary(
        self, patient_id: str, record_id: int
    ) -> PatientSummary:
        """Compute a prefix-safe summary using only 6h and 12h scores."""
        patient, icu_type = self._load_patient_context(record_id)
        trajectory = self.score_preprocessed_patient(
            record_id,
            patient,
            self._primary_prefix(),
        )
        primary = trajectory[-1]
        return PatientSummary(
            patient_id=patient_id,
            icu_type=icu_type,
            checkpoint="12h",
            **primary.model_dump(exclude={"checkpoint"}),
            risk_trend=self._risk_trend(
                trajectory[0].risk_probability,
                primary.risk_probability,
            ),
        )

    def _compute_detail(
        self, patient_id: str, record_id: int, as_of_minutes: int = 1440,
    ) -> PatientDetail:
        """Compute chronology-safe 6h/12h/24h trajectory and vitals."""
        patient, icu_type = self._load_patient_context(record_id)
        patient = observations_up_to(patient, as_of_minutes)
        trajectory = self.score_preprocessed_patient(
            record_id,
            patient,
            tuple(self.cutoffs),
            available_through_minutes=as_of_minutes,
        )
        primary = next(point for point in trajectory if point.checkpoint == PRIMARY_CHECKPOINT)
        return PatientDetail(
            patient_id=patient_id,
            icu_type=icu_type,
            primary_checkpoint="12h",
            available_through_minutes=as_of_minutes,
            **primary.model_dump(exclude={"checkpoint"}),
            risk_trend=self._risk_trend(
                trajectory[0].risk_probability,
                primary.risk_probability,
            ),
            risk_trajectory=trajectory,
            vital_histories=self._vital_histories(patient),
        )

    def score_preprocessed_patient(
        self,
        record_id: int,
        patient: pd.DataFrame,
        checkpoints: tuple[str, ...],
        *,
        available_through_minutes: int = 1440,
    ) -> list[RiskTrajectoryPoint]:
        """Score ordered checkpoints and apply alert policy to each prefix."""
        if not checkpoints or any(label not in self.cutoffs for label in checkpoints):
            raise ValueError("Unsupported checkpoint sequence")
        expected_order = tuple(self.cutoffs)
        if checkpoints != expected_order[: len(checkpoints)]:
            raise ValueError("Checkpoints must be an ordered history prefix")
        if not isinstance(available_through_minutes, int) or not 0 <= available_through_minutes <= 1440:
            raise ValueError("Available time must be between 0 and 1440 minutes")
        return self._score_patient_batch(
            [record_id], {record_id: patient}, checkpoints,
            available_through_minutes=available_through_minutes,
        )[record_id]

    def _score_patient_batch(
        self,
        record_ids: list[int],
        patient_data: dict[int, pd.DataFrame],
        checkpoints: tuple[str, ...],
        *,
        available_through_minutes: int = 1440,
    ) -> dict[int, list[RiskTrajectoryPoint]]:
        """Block future and static-only assessments before model inference.

        One usable temporal observation is a minimum technical guard, not
        evidence of adequate clinical coverage. Missing feature values in
        otherwise eligible rows still use the saved training-time imputer.
        """
        try:
            probabilities = {record_id: [] for record_id in record_ids}
            counts = {record_id: [] for record_id in record_ids}
            for checkpoint in checkpoints:
                if self.cutoffs[checkpoint] > available_through_minutes:
                    for record_id in record_ids:
                        probabilities[record_id].append(None)
                        counts[record_id].append(0)
                    continue
                matrix = build_feature_matrix(
                    record_ids,
                    patient_data,
                    self.cutoffs[checkpoint],
                    version=2,
                )
                if list(matrix.columns) != self.feature_columns:
                    raise PatientInferenceError(
                        f"Runtime feature order mismatch at {checkpoint}"
                    )
                if np.isinf(matrix.to_numpy(dtype=float)).any():
                    raise PatientInferenceError("Non-finite patient measurements")
                observation_counts = usable_temporal_counts(matrix)
                eligible_ids = [rid for rid in record_ids if observation_counts.loc[rid] > 0]
                scores: dict[int, float] = {}
                if eligible_ids:
                    values = self.models[checkpoint].predict_proba(matrix.loc[eligible_ids])[
                        :, self.positive_class_indices[checkpoint]
                    ]
                    if (
                        len(values) != len(eligible_ids)
                        or not np.isfinite(values).all()
                        or ((values < 0) | (values > 1)).any()
                    ):
                        raise PatientInferenceError(f"Invalid RF probability at {checkpoint}")
                    scores = dict(zip(eligible_ids, map(float, values), strict=True))
                for record_id in record_ids:
                    counts[record_id].append(int(observation_counts.loc[record_id]))
                    probabilities[record_id].append(scores.get(record_id))

            trajectories = {}
            for record_id in record_ids:
                timeline = probabilities_to_alert_timeline(
                    probabilities[record_id], self.medium_threshold, self.high_threshold,
                )
                trajectory = []
                for checkpoint, count, policy in zip(checkpoints, counts[record_id], timeline, strict=True):
                    status = "READY"
                    reason = None
                    if self.cutoffs[checkpoint] > available_through_minutes:
                        status = "NOT_YET_AVAILABLE"
                        reason = "This checkpoint has not been reached in the selected recorded-data view."
                    elif policy["probability"] is None:
                        status = "INSUFFICIENT_DATA"
                        reason = "No usable model-supported vital or lab measurements were recorded by this checkpoint."
                    trajectory.append(RiskTrajectoryPoint(
                        checkpoint=checkpoint,
                        assessment_status=status,
                        assessment_reason=reason,
                        temporal_observation_count=count,
                        risk_probability=policy["probability"],
                        risk_level=policy["risk_level"],
                        alert_state=policy["alert_state"],
                    ))
                trajectories[record_id] = trajectory
            return trajectories
        except PatientInferenceError:
            raise
        except Exception as exc:
            raise PatientInferenceError(
                "Unable to calculate the patient assessment"
            ) from exc

    def _record_id(self, patient_id: str) -> int:
        try:
            return self._opaque_to_record[patient_id]
        except KeyError as exc:
            raise PatientNotFoundError(patient_id) from exc

    def _load_patient_context(self, record_id: int) -> tuple[pd.DataFrame, str]:
        try:
            patient = preprocess_patient(load_patient(record_id))
            icu_rows = patient[
                (patient["Parameter"] == "ICUType")
                & (patient["Time_minutes"] == 0)
            ]["Value"].dropna()
            if icu_rows.empty:
                raise ValueError("ICUType is missing at admission")
            icu_code = int(icu_rows.iloc[0])
            icu_type = ICU_TYPE_LABELS[icu_code]
        except Exception as exc:
            raise PatientInferenceError(
                f"Unable to prepare patient {record_id}"
            ) from exc
        return patient, icu_type

    @staticmethod
    def _risk_trend(
        probability_6h: float | None, probability_12h: float | None,
    ) -> str | None:
        if probability_6h is None or probability_12h is None:
            return None
        delta = probability_12h - probability_6h
        if delta > TREND_STABLE_DELTA:
            return "Rising"
        if delta < -TREND_STABLE_DELTA:
            return "Falling"
        return "Stable"

    @staticmethod
    def _vital_histories(patient: pd.DataFrame) -> list[VitalSeries]:
        visible = observations_up_to(patient, EXPECTED_CUTOFFS["24h"])
        histories: list[VitalSeries] = []
        for parameter in VITAL_PARAMETERS:
            measurements = visible[
                (visible["Parameter"] == parameter)
                & visible["Value"].notna()
            ].sort_values("Time_minutes", kind="stable")
            histories.append(
                VitalSeries(
                    parameter=parameter,
                    measurements=[
                        VitalMeasurement(
                            time_minutes=int(row.Time_minutes),
                            value=float(row.Value),
                        )
                        for row in measurements.itertuples(index=False)
                    ],
                )
            )
        return histories


# Constructed once when the backend process imports its service module.
_PATIENT_INFERENCE_SERVICE = PatientInferenceService()
_CALIBRATED_INFERENCE_SERVICE: PatientInferenceService | None = None
_EXPANDED_INFERENCE_SERVICE: PatientInferenceService | None = None
_MODEL_PROFILE_LOCK = Lock()


def get_patient_inference_service(model_profile: str = "original") -> PatientInferenceService:
    """Return a version-specific service; a missing candidate never falls back."""
    if model_profile == "original":
        return _PATIENT_INFERENCE_SERVICE
    if model_profile not in {"calibrated", "expanded"}:
        raise InferenceConfigurationError("Unknown model profile")
    global _CALIBRATED_INFERENCE_SERVICE, _EXPANDED_INFERENCE_SERVICE
    with _MODEL_PROFILE_LOCK:
        if model_profile == "expanded":
            if _EXPANDED_INFERENCE_SERVICE is None:
                _EXPANDED_INFERENCE_SERVICE = PatientInferenceService(model_profile="expanded")
            return _EXPANDED_INFERENCE_SERVICE
        if _CALIBRATED_INFERENCE_SERVICE is None:
            _CALIBRATED_INFERENCE_SERVICE = PatientInferenceService(model_profile="calibrated")
        return _CALIBRATED_INFERENCE_SERVICE
