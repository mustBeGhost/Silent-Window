"""Coverage invariance and timing-field interpretation regression checks."""

import numpy as np
import pandas as pd
import pytest

from ml.coverage import checkpoint_coverage, summarize_coverage, usable_temporal_counts
from ml.features import build_feature_matrix
from scripts.audit_checkpoint_coverage import outcome_timing_diagnostics
from scripts.verify_outcomes_source import compare_outcomes


def frame(rows):
    return pd.DataFrame(rows, columns=["Time_minutes", "Parameter", "Value"])


def test_future_and_outcome_rows_cannot_change_checkpoint_coverage():
    patient = frame([(0, "Age", 50), (60, "HR", 80), (300, "Creatinine", 1.0)])
    extended = pd.concat([patient, frame([
        (361, "HR", 500), (720, "GCS", 3), (0, "In-hospital_death", 1),
    ])], ignore_index=True)
    assert checkpoint_coverage(patient, 360) == checkpoint_coverage(extended, 360)


def test_missing_and_excluded_parameters_do_not_qualify():
    result = checkpoint_coverage(frame([
        (0, "Age", 50), (0, "ICUType", 3), (60, "HR", np.nan), (60, "Urine", 100),
    ]), 360)
    assert not result["scoreable"]
    assert result["temporal_observation_count"] == 0
    assert result["newest_measurement_age_minutes"] is None


def test_bedside_and_lab_freshness_are_separate():
    result = checkpoint_coverage(frame([(60, "HR", 80), (350, "Creatinine", 1)]), 360)
    assert result["supported_parameter_count"] == 2
    assert result["newest_measurement_age_minutes"] == 10
    assert result["newest_bedside_measurement_age_minutes"] == 300
    assert result["HR_age_minutes"] == 300


def test_coverage_and_feature_counts_use_the_same_prefix():
    patient = frame([(0, "Age", 50), (60, "HR", 80), (200, "HR", 90), (361, "GCS", 8)])
    matrix = build_feature_matrix([1], {1: patient}, 360, version=2)
    coverage = checkpoint_coverage(patient, 360)
    assert usable_temporal_counts(matrix).loc[1] == coverage["temporal_observation_count"] == 2


@pytest.mark.parametrize("value", [-1, 0.5, np.inf, np.nan])
def test_invalid_temporal_counts_are_rejected(value):
    patient = frame([(60, "HR", 80)])
    matrix = build_feature_matrix([1], {1: patient}, 360, version=2)
    matrix["HR_count"] = matrix["HR_count"].astype(float)
    matrix.loc[1, "HR_count"] = value
    with pytest.raises(ValueError, match="non-negative integers"):
        usable_temporal_counts(matrix)


def test_coverage_summary_keeps_missing_readings_out_of_age_distribution():
    rows = pd.DataFrame([
        checkpoint_coverage(frame([(60, "HR", 80)]), 360),
        checkpoint_coverage(frame([(0, "Age", 50)]), 360),
    ])
    summary = summarize_coverage(rows)
    assert summary["patients"] == 2
    assert summary["no_supported_measurements"] == 1
    assert summary["newest_measurement_age_minutes"]["known_count"] == 1
    assert summary["newest_measurement_age_minutes"]["median"] == 300


def test_hospital_days_cannot_be_misrepresented_as_exact_icu_eligibility():
    outcomes = pd.DataFrame({
        "RecordID": [1, 2, 3], "Length_of_stay": [5, -1, 1],
        "Survival": [1, -1, -1], "In-hospital_death": [1, 0, 0],
    })
    original = outcomes.copy(deep=True)
    diagnostic = outcome_timing_diagnostics(outcomes)
    assert diagnostic["landmark_eligibility"] == "UNKNOWN_FROM_AVAILABLE_FIELDS"
    assert diagnostic["flag_counts"]["hospital_death_with_survival_0_or_1_days"] == 1
    assert diagnostic["flag_counts"]["hospital_stay_unknown"] == 1
    assert not diagnostic["exact_icu_discharge_time_available"]
    pd.testing.assert_frame_equal(outcomes, original)


def test_invalid_target_labels_cannot_enter_diagnostics():
    outcomes = pd.DataFrame({
        "RecordID": [1], "Length_of_stay": [5], "Survival": [-1], "In-hospital_death": [np.nan],
    })
    with pytest.raises(ValueError, match="binary"):
        outcome_timing_diagnostics(outcomes)


def test_source_comparison_accepts_an_identical_subset_without_changing_data():
    official = pd.DataFrame({"RecordID": [1, 2, 3], "In-hospital_death": [0, 1, 0]})
    local = official.iloc[[2, 0]].copy()
    original = local.copy(deep=True)
    report = compare_outcomes(local, official)
    assert report["all_local_outcome_rows_match_source"]
    assert report["matched_local_rows"] == 2
    pd.testing.assert_frame_equal(local, original)


def test_source_comparison_identifies_changed_labels_and_missing_ids():
    official = pd.DataFrame({"RecordID": [1, 2], "In-hospital_death": [0, 1]})
    local = pd.DataFrame({"RecordID": [1, 3], "In-hospital_death": [1, 0]})
    report = compare_outcomes(local, official)
    assert not report["all_local_outcome_rows_match_source"]
    assert report["mismatched_local_record_ids"] == [1]
    assert report["local_ids_missing_from_official_source"] == [3]
