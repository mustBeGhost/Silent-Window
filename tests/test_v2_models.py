"""
Tests for V2 features (slope) and CV model comparison integrity.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.features import (
    LEAKAGE_COLUMNS,
    TEMPORAL_PARAMETERS,
    V1_EXCLUDED,
    _compute_slope,
    build_patient_features,
    get_feature_columns_v2,
)
from ml.data_loader import discover_patient_ids
from sklearn.model_selection import StratifiedKFold


# -- Helpers ---------------------------------------------------------------

def _make_df(rows):
    df = pd.DataFrame(rows, columns=["Time", "Parameter", "Value"])
    def _t(s):
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    df["Time_minutes"] = df["Time"].apply(_t)
    df["_dup_urine"] = False
    return df.sort_values("Time_minutes", kind="stable").reset_index(drop=True)


BASELINE_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "baseline"


# ==========================================================================
# SLOPE SAFETY
# ==========================================================================

class TestSlopeChronologySafety:

    def test_slope_ignores_future_observations(self):
        """HR slope at 12h must not include 13h observation."""
        df = _make_df([
            ("00:00", "Age", 55),
            ("01:00", "HR", 80),
            ("06:00", "HR", 90),
            ("13:00", "HR", 200),  # FUTURE for 12h cutoff
        ])
        f = build_patient_features(df, cutoff_minutes=720, version=2)
        # Slope from [80@60, 90@360] = (90-80)/(360-60) = 10/300
        expected = 10.0 / 300.0
        assert f["HR_slope"] == pytest.approx(expected, abs=1e-9)

    def test_future_values_cannot_change_slope(self):
        base = _make_df([
            ("00:00", "Age", 55),
            ("02:00", "HR", 80),
            ("08:00", "HR", 100),
        ])
        f_base = build_patient_features(base, cutoff_minutes=720, version=2)

        extended = _make_df([
            ("00:00", "Age", 55),
            ("02:00", "HR", 80),
            ("08:00", "HR", 100),
            ("15:00", "HR", 999),
            ("20:00", "HR", -500),
        ])
        f_ext = build_patient_features(extended, cutoff_minutes=720, version=2)
        assert f_base["HR_slope"] == pytest.approx(f_ext["HR_slope"])


class TestSlopeEdgeCases:

    def test_fewer_than_2_observations_returns_nan(self):
        df = _make_df([
            ("00:00", "Age", 55),
            ("05:00", "HR", 80),
        ])
        f = build_patient_features(df, cutoff_minutes=720, version=2)
        assert math.isnan(f["HR_slope"])

    def test_zero_observations_returns_nan(self):
        df = _make_df([("00:00", "Age", 55)])
        f = build_patient_features(df, cutoff_minutes=720, version=2)
        assert math.isnan(f["HR_slope"])

    def test_equal_timestamps_returns_nan(self):
        """All measurements at same time -> slope undefined."""
        df = _make_df([
            ("00:00", "Age", 55),
            ("05:00", "HR", 80),
            ("05:00", "HR", 100),
        ])
        f = build_patient_features(df, cutoff_minutes=720, version=2)
        assert math.isnan(f["HR_slope"])

    def test_no_infinite_slope(self):
        """Slope must never be infinity."""
        df = _make_df([
            ("00:00", "Age", 55),
            ("01:00", "HR", 0),
            ("02:00", "HR", 1e15),
        ])
        f = build_patient_features(df, cutoff_minutes=720, version=2)
        assert np.isfinite(f["HR_slope"])


class TestSlopeComputation:

    def test_positive_slope(self):
        slope = _compute_slope(
            np.array([60, 120, 180]),
            np.array([80, 90, 100]),
        )
        # Linear increase: slope = 10/60
        assert slope == pytest.approx(10.0 / 60.0)

    def test_negative_slope(self):
        slope = _compute_slope(
            np.array([0, 60]),
            np.array([100, 80]),
        )
        assert slope == pytest.approx(-20.0 / 60.0)

    def test_flat_slope(self):
        slope = _compute_slope(
            np.array([0, 60, 120]),
            np.array([80, 80, 80]),
        )
        assert slope == pytest.approx(0.0)


# ==========================================================================
# V2 FEATURE COLUMNS
# ==========================================================================

class TestV2Columns:

    def test_v2_has_slope_columns(self):
        cols = get_feature_columns_v2()
        for param in TEMPORAL_PARAMETERS:
            assert f"{param}_slope" in cols

    def test_v2_count(self):
        cols = get_feature_columns_v2()
        # 4 static + 16 params * 8 stats = 4 + 128 = 132
        assert len(cols) == 4 + 16 * 8


# ==========================================================================
# CV INTEGRITY
# ==========================================================================

class TestCVIntegrity:

    @pytest.fixture(scope="class")
    def split_meta(self):
        meta_path = BASELINE_DIR / "split_metadata.json"
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f)

    def test_holdout_ids_never_in_cv(self, split_meta):
        """The 640 held-out IDs must never appear in development folds."""
        holdout = set(split_meta["test_ids"])
        dev_ids = split_meta["train_ids"]
        # Verify dev_ids are disjoint from holdout
        assert set(dev_ids) & holdout == set()

    def test_cv_folds_no_overlap(self, split_meta):
        dev_ids = split_meta["train_ids"]
        y = np.zeros(len(dev_ids))  # dummy
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        for train_idx, val_idx in skf.split(dev_ids, y):
            assert set(train_idx) & set(val_idx) == set()

    def test_every_dev_patient_in_validation_exactly_once(self, split_meta):
        dev_ids = split_meta["train_ids"]
        y = np.zeros(len(dev_ids))
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        all_val_indices = []
        for _, val_idx in skf.split(dev_ids, y):
            all_val_indices.extend(val_idx.tolist())
        assert sorted(all_val_indices) == list(range(len(dev_ids)))

    def test_no_forbidden_fields_in_v2_columns(self):
        cols = set(get_feature_columns_v2())
        for bad in LEAKAGE_COLUMNS | {"PatientID"} | V1_EXCLUDED:
            assert bad not in cols
