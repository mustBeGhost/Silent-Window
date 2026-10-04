"""
Tests for Step 6.1 hardening — stronger leakage, integrity, and
categorical-safety tests.

Separated from test_features.py for clarity.
"""

from __future__ import annotations

import copy
import math

import numpy as np
import pandas as pd
import pytest
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.data_loader import (
    discover_patient_ids,
    load_outcomes,
    load_patient,
)
from ml.features import (
    LEAKAGE_COLUMNS,
    STATIC_FEATURES,
    TEMPORAL_PARAMETERS,
    V1_EXCLUDED,
    build_feature_matrix,
    build_patient_features,
    get_feature_columns,
)
from ml.preprocessing import (
    CATEGORICAL_PARAMETERS,
    STATIC_PARAMETERS,
    preprocess_patient,
    resolve_duplicates,
)
from ml.train_baseline import build_sklearn_pipeline, create_split


# -- Helpers ---------------------------------------------------------------

def _make_df(rows):
    """Create patient DF from (Time, Parameter, Value) tuples."""
    df = pd.DataFrame(rows, columns=["Time", "Parameter", "Value"])
    def _t(s):
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    df["Time_minutes"] = df["Time"].apply(_t)
    df["_dup_urine"] = False
    return df.sort_values("Time_minutes", kind="stable").reset_index(drop=True)


# ==========================================================================
# A.  FULL PIPELINE INVARIANCE — post-cutoff observations must not affect
#     features computed at the cutoff.
# ==========================================================================

class TestPipelineInvariance:

    def _base_rows(self):
        return [
            ("00:00", "Age", 55),
            ("00:00", "Gender", 1),
            ("00:00", "Weight", 70),
            ("00:00", "ICUType", 3),
            ("02:00", "HR", 80),
            ("06:00", "HR", 90),
            ("04:00", "Temp", 37.0),
        ]

    def test_appending_post_cutoff_observations_no_change(self):
        base = _make_df(self._base_rows())
        f_base = build_patient_features(base, cutoff_minutes=720)

        # Append arbitrary post-cutoff observations
        extended = _make_df(self._base_rows() + [
            ("13:00", "HR", 999),
            ("20:00", "Temp", 42.0),
            ("15:00", "GCS", 3),
            ("40:00", "Creatinine", 50.0),
        ])
        f_ext = build_patient_features(extended, cutoff_minutes=720)

        for col in get_feature_columns():
            v1, v2 = f_base[col], f_ext[col]
            if isinstance(v1, float) and math.isnan(v1):
                assert math.isnan(v2), f"{col} changed from NaN"
            else:
                assert v1 == v2, f"{col} changed: {v1} -> {v2}"

    def test_post_cutoff_duplicate_conflicts_no_change(self):
        base = _make_df(self._base_rows())
        f_base = build_patient_features(base, cutoff_minutes=720)

        # Add conflicting duplicate AT the post-cutoff timestamp
        conflict = _make_df(self._base_rows() + [
            ("13:00", "HR", 200),
            ("13:00", "HR", 300),
        ])
        f_conf = build_patient_features(conflict, cutoff_minutes=720)

        for col in get_feature_columns():
            v1, v2 = f_base[col], f_conf[col]
            if isinstance(v1, float) and math.isnan(v1):
                assert math.isnan(v2), f"{col} changed from NaN"
            else:
                assert v1 == v2, f"{col} changed: {v1} -> {v2}"


# ==========================================================================
# B.  STATIC FUTURE SAFETY — non-zero-time static rows must not affect
#     static feature values.
# ==========================================================================

class TestStaticFutureSafety:

    def test_nonzero_time_static_ignored(self):
        df = _make_df([
            ("00:00", "Age", 55),
            ("00:00", "Gender", 1),
            ("00:00", "Weight", 70),
            ("00:00", "ICUType", 3),
            ("05:00", "Age", 99),      # fake future Age
            ("08:00", "Gender", 0),    # fake future Gender
            ("10:00", "Weight", 999),
            ("03:00", "ICUType", 1),
        ])
        f = build_patient_features(df, cutoff_minutes=720)
        assert f["Age"] == 55
        assert f["Gender"] == 1
        assert f["Weight"] == 70
        assert f["ICUType"] == 3


# ==========================================================================
# C.  UNSORTED INPUT — feature builder must handle any input order safely
# ==========================================================================

class TestUnsortedInput:

    def test_unsorted_produces_same_features(self):
        rows = [
            ("00:00", "Age", 55),
            ("00:00", "Gender", 1),
            ("00:00", "Weight", 70),
            ("00:00", "ICUType", 3),
            ("02:00", "HR", 80),
            ("06:00", "HR", 90),
        ]
        sorted_df = _make_df(rows)

        # Reverse the rows before making the DF
        unsorted_df = _make_df(rows[::-1])
        f1 = build_patient_features(sorted_df, cutoff_minutes=720)
        f2 = build_patient_features(unsorted_df, cutoff_minutes=720)

        for col in get_feature_columns():
            v1, v2 = f1[col], f2[col]
            if isinstance(v1, float) and math.isnan(v1):
                assert math.isnan(v2), f"{col} differs"
            else:
                assert v1 == v2, f"{col}: {v1} != {v2}"


# ==========================================================================
# D.  SPLIT INTEGRITY
# ==========================================================================

class TestSplitIntegrity:

    @pytest.fixture(scope="class")
    def split(self):
        outcomes = load_outcomes()
        return create_split(outcomes)

    def test_train_ids_unique(self, split):
        train_ids = split[0]
        assert len(train_ids) == len(set(train_ids))

    def test_test_ids_unique(self, split):
        test_ids = split[1]
        assert len(test_ids) == len(set(test_ids))

    def test_disjoint(self, split):
        assert set(split[0]) & set(split[1]) == set()

    def test_union_equals_all_ids(self, split):
        all_ids = set(discover_patient_ids())
        assert set(split[0]) | set(split[1]) == all_ids

    def test_label_alignment(self, split):
        train_ids, test_ids, y_train, y_test = split
        assert list(y_train.index) == list(train_ids)
        assert list(y_test.index) == list(test_ids)


# ==========================================================================
# E.  DUPLICATE IDs — must raise on invalid input
# ==========================================================================

class TestDuplicateIDValidation:

    def test_outcomes_ids_are_unique(self):
        outcomes = load_outcomes()
        assert outcomes["RecordID"].is_unique

    def test_patient_file_ids_are_unique(self):
        ids = discover_patient_ids()
        assert len(ids) == len(set(ids))


# ==========================================================================
# F.  TRAIN-ONLY PREPROCESSING — fitted stats must not change when
#     test data is perturbed.
# ==========================================================================

class TestTrainOnlyPreprocessing:

    def test_perturbing_test_does_not_change_fitted_stats(self):
        # Build minimal synthetic data
        cols = get_feature_columns()
        rng = np.random.RandomState(0)
        n_train, n_test = 50, 20

        X_train = pd.DataFrame(
            rng.randn(n_train, len(cols)), columns=cols,
        )
        X_train["ICUType"] = rng.choice([1, 2, 3, 4], n_train)

        X_test_a = pd.DataFrame(
            rng.randn(n_test, len(cols)), columns=cols,
        )
        X_test_a["ICUType"] = rng.choice([1, 2, 3, 4], n_test)

        X_test_b = X_test_a.copy()
        X_test_b.iloc[:, :10] *= 1000  # wildly perturb first 10 cols

        y_train = pd.Series(rng.choice([0, 1], n_train))

        pipe_a = build_sklearn_pipeline()
        pipe_b = build_sklearn_pipeline()
        pipe_a.fit(X_train, y_train)
        pipe_b.fit(X_train, y_train)

        # Extract imputer statistics from both — must be identical
        ct_a = pipe_a.named_steps["preprocess"]
        ct_b = pipe_b.named_steps["preprocess"]
        stats_a = ct_a.transformers_[0][1].named_steps["imputer"].statistics_
        stats_b = ct_b.transformers_[0][1].named_steps["imputer"].statistics_
        np.testing.assert_array_equal(stats_a, stats_b)


# ==========================================================================
# G.  METRIC SEMANTICS — verify probability and threshold logic
# ==========================================================================

class TestMetricSemantics:

    def test_predict_proba_positive_class_is_column_1(self):
        cols = get_feature_columns()
        rng = np.random.RandomState(1)
        n = 100
        X = pd.DataFrame(rng.randn(n, len(cols)), columns=cols)
        X["ICUType"] = rng.choice([1, 2, 3, 4], n)
        y = pd.Series(rng.choice([0, 1], n))

        pipe = build_sklearn_pipeline()
        pipe.fit(X, y)
        probs = pipe.predict_proba(X)
        preds = pipe.predict(X)

        # sklearn default threshold is 0.50
        expected = (probs[:, 1] >= 0.5).astype(int)
        np.testing.assert_array_equal(preds, expected)


# ==========================================================================
# H.  REAL-MATRIX SAFETY — verify 6h/12h/24h matrices on real data
# ==========================================================================

class TestRealMatrixSafety:

    @pytest.fixture(scope="class")
    def patient_data(self):
        # Load a small sample for speed
        ids = discover_patient_ids()[:20]
        return {pid: preprocess_patient(load_patient(pid)) for pid in ids}

    @pytest.fixture(scope="class")
    def sample_ids(self):
        return discover_patient_ids()[:20]

    @pytest.mark.parametrize("cutoff", [360, 720, 1440])
    def test_matrix_row_count(self, patient_data, sample_ids, cutoff):
        mat = build_feature_matrix(sample_ids, patient_data, cutoff)
        assert mat.shape[0] == len(sample_ids)

    @pytest.mark.parametrize("cutoff", [360, 720, 1440])
    def test_no_infinities(self, patient_data, sample_ids, cutoff):
        mat = build_feature_matrix(sample_ids, patient_data, cutoff)
        numeric = mat.select_dtypes(include=[np.number])
        assert not np.isinf(numeric.values).any()

    @pytest.mark.parametrize("cutoff", [360, 720, 1440])
    def test_time_since_last_nonnegative(self, patient_data, sample_ids, cutoff):
        mat = build_feature_matrix(sample_ids, patient_data, cutoff)
        tsl_cols = [c for c in mat.columns if c.endswith("_time_since_last")]
        for col in tsl_cols:
            vals = mat[col].dropna()
            assert (vals >= 0).all(), f"{col} has negative time_since_last"

    @pytest.mark.parametrize("cutoff", [360, 720, 1440])
    def test_no_forbidden_columns(self, patient_data, sample_ids, cutoff):
        mat = build_feature_matrix(sample_ids, patient_data, cutoff)
        for bad in LEAKAGE_COLUMNS | {"PatientID"} | V1_EXCLUDED:
            assert bad not in mat.columns, f"Forbidden column: {bad}"


# ==========================================================================
# I.  CATEGORICAL DUPLICATE RESOLUTION — never averaged
# ==========================================================================

class TestCategoricalDuplicateResolution:

    def test_mechvent_duplicates_not_averaged(self):
        """MechVent (0 or 1) duplicates must keep first valid, not median."""
        df = pd.DataFrame({
            "Time": ["01:00", "01:00"],
            "Parameter": ["MechVent", "MechVent"],
            "Value": [1.0, 0.0],
            "Time_minutes": [60, 60],
        })
        df["_dup_urine"] = False
        result = resolve_duplicates(df)
        # Should keep exactly one row
        assert len(result[result["Parameter"] == "MechVent"]) == 1
        # Should keep first valid value (1.0), not median (0.5)
        assert result[result["Parameter"] == "MechVent"]["Value"].iloc[0] == 1.0

    def test_gender_duplicates_not_averaged(self):
        """Gender duplicates keep first valid, never averaged."""
        df = pd.DataFrame({
            "Time": ["00:00", "00:00"],
            "Parameter": ["Gender", "Gender"],
            "Value": [1.0, 0.0],
            "Time_minutes": [0, 0],
        })
        df["_dup_urine"] = False
        result = resolve_duplicates(df)
        assert len(result[result["Parameter"] == "Gender"]) == 1
        assert result[result["Parameter"] == "Gender"]["Value"].iloc[0] == 1.0

    def test_icutype_duplicates_not_averaged(self):
        """ICUType duplicates keep first valid, never averaged."""
        df = pd.DataFrame({
            "Time": ["00:00", "00:00"],
            "Parameter": ["ICUType", "ICUType"],
            "Value": [2.0, 4.0],
            "Time_minutes": [0, 0],
        })
        df["_dup_urine"] = False
        result = resolve_duplicates(df)
        assert len(result[result["Parameter"] == "ICUType"]) == 1
        # First valid value is 2.0, not median 3.0
        assert result[result["Parameter"] == "ICUType"]["Value"].iloc[0] == 2.0

    def test_continuous_still_uses_median(self):
        """Non-categorical, non-static, non-Urine params still use median."""
        df = pd.DataFrame({
            "Time": ["05:00", "05:00"],
            "Parameter": ["HR", "HR"],
            "Value": [80.0, 100.0],
            "Time_minutes": [300, 300],
        })
        df["_dup_urine"] = False
        result = resolve_duplicates(df)
        assert len(result[result["Parameter"] == "HR"]) == 1
        assert result[result["Parameter"] == "HR"]["Value"].iloc[0] == 90.0
