"""
Tests for ml.features — chronology-safe feature engineering.

These tests use synthetic data to prove safety properties and
real data for smoke-testing.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from ml.features import (
    LEAKAGE_COLUMNS,
    STATIC_FEATURES,
    TEMPORAL_PARAMETERS,
    TEMPORAL_STATS,
    V1_EXCLUDED,
    build_feature_matrix,
    build_patient_features,
    get_feature_columns,
)


# -- Helpers ---------------------------------------------------------------

def make_patient_df(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    """
    Create a minimal patient DataFrame from (Time, Parameter, Value) tuples.

    Mimics the output of ``preprocess_patient`` with the columns the
    feature builder expects.
    """
    df = pd.DataFrame(rows, columns=["Time", "Parameter", "Value"])
    # Parse time -> minutes (simplified for tests)
    def _parse(t: str) -> int:
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    df["Time_minutes"] = df["Time"].apply(_parse)
    df["_dup_urine"] = False
    df = df.sort_values("Time_minutes", kind="stable").reset_index(drop=True)
    return df


# ==========================================================================
# A.  FUTURE-DATA LEAKAGE PROTECTION
# ==========================================================================

class TestLeakageProtection:
    """Prove that observations after the cutoff never affect features."""

    @pytest.fixture()
    def patient(self):
        return make_patient_df([
            ("00:00", "Age",  65),
            ("00:00", "Gender", 1),
            ("00:00", "Weight", 80),
            ("00:00", "ICUType", 2),
            ("01:00", "HR",   80),
            ("05:00", "HR",   90),
            ("13:00", "HR",  200),  # FUTURE for 12h cutoff
        ])

    def test_hr_latest_ignores_future(self, patient):
        f = build_patient_features(patient, cutoff_minutes=720)
        assert f["HR_latest"] == 90

    def test_hr_mean_ignores_future(self, patient):
        f = build_patient_features(patient, cutoff_minutes=720)
        assert f["HR_mean"] == pytest.approx(85.0)

    def test_hr_min_ignores_future(self, patient):
        f = build_patient_features(patient, cutoff_minutes=720)
        assert f["HR_min"] == 80

    def test_hr_max_ignores_future(self, patient):
        f = build_patient_features(patient, cutoff_minutes=720)
        assert f["HR_max"] == 90

    def test_hr_std_ignores_future(self, patient):
        f = build_patient_features(patient, cutoff_minutes=720)
        # std of [80, 90] only
        expected = pd.Series([80.0, 90.0]).std()
        assert f["HR_std"] == pytest.approx(expected)

    def test_hr_count_ignores_future(self, patient):
        f = build_patient_features(patient, cutoff_minutes=720)
        assert f["HR_count"] == 2

    def test_full_cutoff_includes_all(self, patient):
        f = build_patient_features(patient, cutoff_minutes=2880)
        assert f["HR_count"] == 3
        assert f["HR_latest"] == 200
        assert f["HR_max"] == 200


# ==========================================================================
# B.  time_since_last CORRECTNESS
# ==========================================================================

class TestTimeSinceLast:

    def test_basic(self):
        df = make_patient_df([
            ("00:00", "Age", 50),
            ("03:00", "HR",  80),
            ("08:00", "HR",  90),
        ])
        f = build_patient_features(df, cutoff_minutes=720)
        # 720 - 480 = 240
        assert f["HR_time_since_last"] == 240

    def test_measurement_at_cutoff(self):
        df = make_patient_df([
            ("00:00", "Age", 50),
            ("12:00", "HR",  80),
        ])
        f = build_patient_features(df, cutoff_minutes=720)
        assert f["HR_time_since_last"] == 0


# ==========================================================================
# C.  NO MEASUREMENT BEFORE CUTOFF
# ==========================================================================

class TestNoMeasurement:

    def test_missing_param_returns_nan_and_zero_count(self):
        df = make_patient_df([
            ("00:00", "Age", 50),
            ("00:00", "Gender", 1),
            ("00:00", "Weight", 75),
            ("00:00", "ICUType", 3),
        ])
        f = build_patient_features(df, cutoff_minutes=360)
        assert math.isnan(f["HR_latest"])
        assert math.isnan(f["HR_mean"])
        assert math.isnan(f["HR_min"])
        assert math.isnan(f["HR_max"])
        assert math.isnan(f["HR_std"])
        assert f["HR_count"] == 0
        assert math.isnan(f["HR_time_since_last"])

    def test_future_only_measurement_returns_empty(self):
        df = make_patient_df([
            ("00:00", "Age", 50),
            ("13:00", "HR",  100),  # after 12h cutoff
        ])
        f = build_patient_features(df, cutoff_minutes=720)
        assert f["HR_count"] == 0
        assert math.isnan(f["HR_latest"])


# ==========================================================================
# D.  RecordID IS NOT A PREDICTIVE FEATURE
# ==========================================================================

class TestRecordIDExcluded:

    def test_recordid_not_in_feature_columns(self):
        cols = get_feature_columns()
        assert "RecordID" not in cols

    def test_leakage_columns_defined(self):
        for col in ["RecordID", "In-hospital_death", "Survival",
                     "Length_of_stay", "SAPS-I", "SOFA"]:
            assert col in LEAKAGE_COLUMNS


# ==========================================================================
# E.  URINE IS NOT IN V1 FEATURES
# ==========================================================================

class TestUrineExcluded:

    def test_urine_not_in_temporal_parameters(self):
        assert "Urine" not in TEMPORAL_PARAMETERS

    def test_urine_in_v1_excluded(self):
        assert "Urine" in V1_EXCLUDED

    def test_urine_not_in_feature_columns(self):
        cols = get_feature_columns()
        urine_cols = [c for c in cols if c.startswith("Urine")]
        assert urine_cols == []


# ==========================================================================
# F.  HEIGHT IS NOT IN V1 FEATURES
# ==========================================================================

class TestHeightExcluded:

    def test_height_not_in_static_features(self):
        assert "Height" not in STATIC_FEATURES

    def test_height_in_v1_excluded(self):
        assert "Height" in V1_EXCLUDED

    def test_height_not_in_feature_columns(self):
        cols = get_feature_columns()
        assert "Height" not in cols


# ==========================================================================
# G.  DETERMINISTIC COLUMN ORDER
# ==========================================================================

class TestColumnOrder:

    def test_get_feature_columns_deterministic(self):
        c1 = get_feature_columns()
        c2 = get_feature_columns()
        assert c1 == c2

    def test_columns_start_with_static(self):
        cols = get_feature_columns()
        for i, sf in enumerate(STATIC_FEATURES):
            assert cols[i] == sf

    def test_temporal_columns_grouped_by_param(self):
        cols = get_feature_columns()
        n_static = len(STATIC_FEATURES)
        n_stats = len(TEMPORAL_STATS)
        for i, param in enumerate(TEMPORAL_PARAMETERS):
            start = n_static + i * n_stats
            for j, stat in enumerate(TEMPORAL_STATS):
                assert cols[start + j] == f"{param}_{stat}"

    def test_total_feature_count(self):
        cols = get_feature_columns()
        expected = len(STATIC_FEATURES) + len(TEMPORAL_PARAMETERS) * len(TEMPORAL_STATS)
        assert len(cols) == expected


# ==========================================================================
# H.  CUTOFF VALIDATION
# ==========================================================================

class TestCutoffValidation:

    def test_negative_cutoff_raises(self):
        df = make_patient_df([("00:00", "Age", 50)])
        with pytest.raises(ValueError):
            build_patient_features(df, cutoff_minutes=-1)

    def test_over_2880_cutoff_raises(self):
        df = make_patient_df([("00:00", "Age", 50)])
        with pytest.raises(ValueError):
            build_patient_features(df, cutoff_minutes=2881)


# ==========================================================================
# I.  BUILD FEATURE MATRIX
# ==========================================================================

class TestBuildFeatureMatrix:

    def test_matrix_shape_and_index(self):
        p1 = make_patient_df([
            ("00:00", "Age", 50), ("00:00", "Gender", 1),
            ("00:00", "Weight", 70), ("00:00", "ICUType", 1),
            ("02:00", "HR", 80),
        ])
        p2 = make_patient_df([
            ("00:00", "Age", 60), ("00:00", "Gender", 0),
            ("00:00", "Weight", 90), ("00:00", "ICUType", 3),
            ("04:00", "HR", 100),
        ])
        data = {1: p1, 2: p2}
        matrix = build_feature_matrix([1, 2], data, cutoff_minutes=360)

        assert matrix.shape[0] == 2
        assert list(matrix.index) == [1, 2]
        assert list(matrix.columns) == get_feature_columns()
        assert "PatientID" not in matrix.columns
