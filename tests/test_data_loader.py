"""
Tests for ml.data_loader
"""

import pytest
import pandas as pd
from pathlib import Path

from ml.data_loader import (
    discover_patient_files,
    discover_patient_ids,
    get_project_root,
    load_outcomes,
    load_patient,
    parse_time_to_minutes,
    validate_id_matching,
)


# ═════════════════════════════════════════════════════════════════════════
# Discovery
# ═════════════════════════════════════════════════════════════════════════

class TestDiscovery:

    def test_discover_3200_patient_files(self):
        files = discover_patient_files()
        assert len(files) == 3200

    def test_discover_3200_patient_ids(self):
        ids = discover_patient_ids()
        assert len(ids) == 3200
        assert all(isinstance(i, int) for i in ids)

    def test_patient_files_are_sorted(self):
        files = discover_patient_files()
        names = [f.name for f in files]
        assert names == sorted(names)


# ═════════════════════════════════════════════════════════════════════════
# Outcomes
# ═════════════════════════════════════════════════════════════════════════

class TestOutcomes:

    def test_outcomes_count(self):
        outcomes = load_outcomes()
        assert len(outcomes) == 3200

    def test_outcomes_unique_ids(self):
        outcomes = load_outcomes()
        assert outcomes["RecordID"].nunique() == 3200

    def test_outcomes_required_columns(self):
        outcomes = load_outcomes()
        assert "RecordID" in outcomes.columns
        assert "In-hospital_death" in outcomes.columns


# ═════════════════════════════════════════════════════════════════════════
# ID matching
# ═════════════════════════════════════════════════════════════════════════

class TestIDMatching:

    def test_ids_match_exactly(self):
        file_ids, outcome_ids = validate_id_matching()
        assert file_ids == outcome_ids


# ═════════════════════════════════════════════════════════════════════════
# Time parsing
# ═════════════════════════════════════════════════════════════════════════

class TestTimeParsing:

    def test_midnight(self):
        assert parse_time_to_minutes("00:00") == 0

    def test_one_hour(self):
        assert parse_time_to_minutes("01:00") == 60

    def test_48_hours(self):
        assert parse_time_to_minutes("48:00") == 2880

    def test_mixed(self):
        assert parse_time_to_minutes("01:30") == 90

    def test_large_hour(self):
        assert parse_time_to_minutes("47:59") == 2879

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_time_to_minutes("abc")

    def test_too_many_colons_raises(self):
        with pytest.raises(ValueError):
            parse_time_to_minutes("01:02:03")

    def test_negative_minutes_raises(self):
        with pytest.raises(ValueError):
            parse_time_to_minutes("01:-5")

    def test_minutes_60_raises(self):
        with pytest.raises(ValueError):
            parse_time_to_minutes("01:60")


# ═════════════════════════════════════════════════════════════════════════
# Load patient
# ═════════════════════════════════════════════════════════════════════════

class TestLoadPatient:

    def test_load_real_patient_structure(self):
        pid = discover_patient_ids()[0]
        df = load_patient(pid)
        assert "Time" in df.columns
        assert "Parameter" in df.columns
        assert "Value" in df.columns
        assert "Time_minutes" in df.columns
        assert len(df) > 0

    def test_patient_chronological_order(self):
        pid = discover_patient_ids()[0]
        df = load_patient(pid)
        minutes = df["Time_minutes"].values
        assert all(minutes[i] <= minutes[i + 1] for i in range(len(minutes) - 1))

    def test_value_is_numeric(self):
        pid = discover_patient_ids()[0]
        df = load_patient(pid)
        assert pd.api.types.is_numeric_dtype(df["Value"])

    def test_nonexistent_patient_raises(self):
        with pytest.raises(FileNotFoundError):
            load_patient(999999999)


# ═════════════════════════════════════════════════════════════════════════
# Raw-data safety
# ═════════════════════════════════════════════════════════════════════════

class TestRawDataSafety:

    def test_loading_does_not_modify_raw_file(self):
        pid = discover_patient_ids()[0]
        filepath = (
            get_project_root()
            / "data" / "raw" / "dataset_2" / "train" / "set-a"
            / f"{pid}.txt"
        )
        content_before = filepath.read_text()
        _ = load_patient(pid)
        content_after = filepath.read_text()
        assert content_before == content_after
