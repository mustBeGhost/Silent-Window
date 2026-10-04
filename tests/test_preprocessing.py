"""
Tests for ml.preprocessing
"""

import pytest
import numpy as np
import pandas as pd

from ml.data_loader import discover_patient_ids, load_patient
from ml.preprocessing import (
    observations_up_to,
    preprocess_patient,
    replace_sentinels,
    resolve_duplicates,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_df(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    """Build a small test DataFrame from (time, parameter, value) tuples."""
    df = pd.DataFrame(rows, columns=["Time", "Parameter", "Value"])
    df["Time_minutes"] = df["Time"].apply(
        lambda t: int(t.split(":")[0]) * 60 + int(t.split(":")[1])
    )
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    return df


# ═════════════════════════════════════════════════════════════════════════
# Sentinel replacement
# ═════════════════════════════════════════════════════════════════════════

class TestSentinelReplacement:

    def test_height_minus1_becomes_nan(self):
        df = _make_df([("00:00", "Height", -1)])
        result = replace_sentinels(df)
        assert np.isnan(result["Value"].iloc[0])

    def test_weight_minus1_becomes_nan(self):
        df = _make_df([("00:00", "Weight", -1)])
        result = replace_sentinels(df)
        assert np.isnan(result["Value"].iloc[0])

    def test_gender_minus1_becomes_nan(self):
        df = _make_df([("00:00", "Gender", -1)])
        result = replace_sentinels(df)
        assert np.isnan(result["Value"].iloc[0])

    def test_other_minus1_not_replaced(self):
        """Only Height/Weight/Gender sentinels are touched."""
        df = _make_df([
            ("00:00", "Height", -1),
            ("01:00", "HR", -1),
            ("02:00", "Temp", -1),
        ])
        result = replace_sentinels(df)
        assert np.isnan(result[result["Parameter"] == "Height"]["Value"].iloc[0])
        assert result[result["Parameter"] == "HR"]["Value"].iloc[0] == -1
        assert result[result["Parameter"] == "Temp"]["Value"].iloc[0] == -1

    def test_valid_values_unchanged(self):
        df = _make_df([("00:00", "Height", 170)])
        result = replace_sentinels(df)
        assert result["Value"].iloc[0] == 170

    def test_does_not_modify_original(self):
        df = _make_df([("00:00", "Height", -1)])
        _ = replace_sentinels(df)
        assert df["Value"].iloc[0] == -1


# ═════════════════════════════════════════════════════════════════════════
# Duplicate resolution
# ═════════════════════════════════════════════════════════════════════════

class TestDuplicateResolution:

    def test_no_duplicates_passthrough(self):
        df = _make_df([
            ("00:00", "HR", 80),
            ("01:00", "HR", 85),
        ])
        result = resolve_duplicates(df)
        assert len(result) == 2

    def test_continuous_median_odd(self):
        df = _make_df([
            ("01:00", "Temp", 36.5),
            ("01:00", "Temp", 37.5),
            ("01:00", "Temp", 38.0),
        ])
        result = resolve_duplicates(df)
        temp = result[result["Parameter"] == "Temp"]
        assert len(temp) == 1
        assert temp["Value"].iloc[0] == 37.5

    def test_continuous_median_even(self):
        df = _make_df([
            ("01:00", "MAP", 70),
            ("01:00", "MAP", 80),
        ])
        result = resolve_duplicates(df)
        row = result[result["Parameter"] == "MAP"]
        assert len(row) == 1
        assert row["Value"].iloc[0] == 75.0  # median of 70, 80

    def test_gender_never_averaged(self):
        df = _make_df([
            ("00:00", "Gender", 0),
            ("00:00", "Gender", 1),
        ])
        result = resolve_duplicates(df)
        gender = result[result["Parameter"] == "Gender"]
        assert len(gender) == 1
        # Must be one of the original values, not 0.5
        assert gender["Value"].iloc[0] in (0, 1)

    def test_urine_preserved_and_flagged(self):
        df = _make_df([
            ("01:00", "Urine", 400),
            ("01:00", "Urine", 0),
        ])
        result = resolve_duplicates(df)
        urine = result[result["Parameter"] == "Urine"]
        assert len(urine) == 2
        assert urine["_dup_urine"].all()

    def test_non_dup_urine_not_flagged(self):
        df = _make_df([
            ("01:00", "Urine", 200),
            ("02:00", "Urine", 300),
        ])
        result = resolve_duplicates(df)
        assert not result["_dup_urine"].any()

    def test_does_not_modify_original(self):
        df = _make_df([
            ("01:00", "Temp", 36.5),
            ("01:00", "Temp", 37.5),
        ])
        original_len = len(df)
        _ = resolve_duplicates(df)
        assert len(df) == original_len

    def test_result_chronological(self):
        df = _make_df([
            ("02:00", "HR", 90),
            ("01:00", "Temp", 37.0),
            ("01:00", "Temp", 38.0),
            ("00:00", "HR", 80),
        ])
        result = resolve_duplicates(df)
        mins = result["Time_minutes"].values
        assert all(mins[i] <= mins[i + 1] for i in range(len(mins) - 1))


# ═════════════════════════════════════════════════════════════════════════
# Chronological filter
# ═════════════════════════════════════════════════════════════════════════

class TestChronologicalFilter:

    def test_basic_filter(self):
        df = _make_df([
            ("00:00", "HR", 80),
            ("06:00", "HR", 85),
            ("12:00", "HR", 90),
            ("24:00", "HR", 95),
        ])
        result = observations_up_to(df, 720)
        assert len(result) == 3
        assert result["Time_minutes"].max() <= 720

    def test_never_returns_future(self):
        df = _make_df([
            ("00:00", "HR", 80),
            ("12:01", "HR", 85),
        ])
        result = observations_up_to(df, 720)
        assert len(result) == 1
        assert (result["Time_minutes"] <= 720).all()

    def test_cutoff_inclusive(self):
        df = _make_df([
            ("12:00", "HR", 90),
        ])
        result = observations_up_to(df, 720)
        assert len(result) == 1

    def test_cutoff_zero_returns_only_admission(self):
        df = _make_df([
            ("00:00", "RecordID", 12345),
            ("00:00", "Age", 65),
            ("01:00", "HR", 80),
        ])
        result = observations_up_to(df, 0)
        assert (result["Time_minutes"] == 0).all()
        assert len(result) == 2

    def test_cutoff_2880_returns_all(self):
        df = _make_df([
            ("00:00", "HR", 80),
            ("48:00", "HR", 90),
        ])
        result = observations_up_to(df, 2880)
        assert len(result) == 2

    def test_cutoff_below_zero_raises(self):
        df = _make_df([("00:00", "HR", 80)])
        with pytest.raises(ValueError):
            observations_up_to(df, -1)

    def test_cutoff_above_2880_raises(self):
        df = _make_df([("00:00", "HR", 80)])
        with pytest.raises(ValueError):
            observations_up_to(df, 2881)

    def test_does_not_modify_original(self):
        df = _make_df([
            ("00:00", "HR", 80),
            ("24:00", "HR", 90),
        ])
        original_len = len(df)
        _ = observations_up_to(df, 720)
        assert len(df) == original_len


# ═════════════════════════════════════════════════════════════════════════
# Integration with real data
# ═════════════════════════════════════════════════════════════════════════

class TestRealPatientPreprocessing:

    def test_full_pipeline_on_real_patient(self):
        pid = discover_patient_ids()[0]
        raw = load_patient(pid)
        processed = preprocess_patient(raw)

        assert len(processed) > 0

        # Chronological
        mins = processed["Time_minutes"].values
        assert all(mins[i] <= mins[i + 1] for i in range(len(mins) - 1))

        # Filter to 12 h
        filtered = observations_up_to(processed, 720)
        assert filtered["Time_minutes"].max() <= 720

    def test_preprocessing_does_not_modify_loaded_df(self):
        pid = discover_patient_ids()[0]
        raw = load_patient(pid)
        raw_copy = raw.copy()
        _ = preprocess_patient(raw)
        pd.testing.assert_frame_equal(raw, raw_copy)
