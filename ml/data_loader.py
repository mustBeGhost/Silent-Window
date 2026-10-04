"""
Silent Window — Data Loader
============================
Functions for loading and validating ICU patient data from the
extracted PhysioNet dataset.

Dataset structure:
    data/raw/dataset_2/train/
        set-a/              <- individual patient .txt files
        Outcomes-train.txt  <- labels / outcomes

Each patient file is a long-format CSV with columns:
    Time (HH:MM), Parameter (str), Value (numeric)

Design rules:
    - Uses pathlib; no hard-coded absolute Windows paths.
    - Invalid rows raise clear errors; nothing is silently discarded.
    - Returned DataFrames are always in chronological order.
"""

from __future__ import annotations

from pathlib import Path
from typing import Set, Tuple

import pandas as pd


# ── Path resolution ──────────────────────────────────────────────────────

def get_project_root() -> Path:
    """Return the project root directory (parent of ``ml/``)."""
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """Return the path to the extracted train directory."""
    data_dir = get_project_root() / "data" / "raw" / "dataset_2" / "train"
    if not data_dir.exists():
        raise FileNotFoundError(
            f"Extracted dataset not found at: {data_dir}\n"
            "Run extraction first: extract Dataset 2.zip into data/raw/dataset_2/"
        )
    return data_dir


def get_patient_dir() -> Path:
    """Return the path to the patient files directory."""
    patient_dir = get_data_dir() / "set-a"
    if not patient_dir.exists():
        raise FileNotFoundError(f"Patient directory not found: {patient_dir}")
    return patient_dir


def get_outcomes_path() -> Path:
    """Return the path to the outcomes file."""
    path = get_data_dir() / "Outcomes-train.txt"
    if not path.exists():
        raise FileNotFoundError(f"Outcomes file not found: {path}")
    return path


# ── Discovery ────────────────────────────────────────────────────────────

def discover_patient_files() -> list[Path]:
    """Discover all patient ``.txt`` files, sorted by filename."""
    patient_dir = get_patient_dir()
    files = sorted(patient_dir.glob("*.txt"))
    if not files:
        raise FileNotFoundError(f"No patient files found in: {patient_dir}")
    return files


def discover_patient_ids() -> list[int]:
    """Return a sorted list of all patient IDs derived from filenames."""
    return [int(f.stem) for f in discover_patient_files()]


# ── Time parsing ─────────────────────────────────────────────────────────

def parse_time_to_minutes(time_str: str) -> int:
    """
    Parse an ``HH:MM`` timestamp string to integer minutes.

    Args:
        time_str: Time in ``"HH:MM"`` format (hours may exceed 24).

    Returns:
        Integer total minutes (e.g. ``"01:30"`` → ``90``).

    Raises:
        ValueError: If the format is invalid or values are negative.
    """
    try:
        parts = str(time_str).split(":")
        if len(parts) != 2:
            raise ValueError(f"Expected HH:MM format, got: {time_str!r}")
        hours, minutes = int(parts[0]), int(parts[1])
        if hours < 0:
            raise ValueError(f"Negative hours in time: {time_str!r}")
        if minutes < 0 or minutes >= 60:
            raise ValueError(f"Invalid minutes in time: {time_str!r}")
        return hours * 60 + minutes
    except (TypeError, IndexError) as exc:
        raise ValueError(f"Cannot parse time: {time_str!r}") from exc


# ── Loading ──────────────────────────────────────────────────────────────

def load_patient(patient_id: int) -> pd.DataFrame:
    """
    Load a single patient's observation file.

    Args:
        patient_id: The numeric patient / record ID.

    Returns:
        DataFrame with columns ``Time``, ``Parameter``, ``Value``,
        ``Time_minutes``.  Sorted chronologically by ``Time_minutes``.

    Raises:
        FileNotFoundError: If the patient file does not exist.
        ValueError: If the file has unexpected structure or non-numeric values.
    """
    filepath = get_patient_dir() / f"{patient_id}.txt"
    if not filepath.exists():
        raise FileNotFoundError(f"Patient file not found: {filepath}")

    df = pd.read_csv(filepath)

    # ── validate columns ────────────────────────────────────────────────
    required = {"Time", "Parameter", "Value"}
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        raise ValueError(
            f"Patient {patient_id}: missing columns {missing}. "
            f"Found: {list(df.columns)}"
        )

    # ── parse time ──────────────────────────────────────────────────────
    df["Time_minutes"] = df["Time"].apply(parse_time_to_minutes)

    # ── convert value (flag non-numeric rather than silently dropping) ──
    original_values = df["Value"].copy()
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")

    coerced = df["Value"].isna() & original_values.notna()
    if coerced.any():
        bad = df.loc[coerced, ["Time", "Parameter"]].to_dict("records")
        raise ValueError(
            f"Patient {patient_id}: non-numeric Value(s) at: {bad}"
        )

    # ── chronological sort ──────────────────────────────────────────────
    df = df.sort_values("Time_minutes", kind="stable").reset_index(drop=True)
    return df


def load_outcomes() -> pd.DataFrame:
    """
    Load the outcomes / labels file.

    Returns:
        DataFrame with columns ``RecordID``, ``SAPS-I``, ``SOFA``,
        ``Length_of_stay``, ``Survival``, ``In-hospital_death``.

    Raises:
        FileNotFoundError: If the outcomes file is missing.
        ValueError: If required columns are absent.
    """
    df = pd.read_csv(get_outcomes_path())
    required = {"RecordID", "In-hospital_death"}
    if not required.issubset(df.columns):
        raise ValueError(f"Outcomes file missing columns: {required - set(df.columns)}")
    return df


def validate_id_matching() -> Tuple[Set[int], Set[int]]:
    """
    Validate that patient-file IDs and outcome IDs match exactly.

    Returns:
        ``(file_ids, outcome_ids)`` as sets.

    Raises:
        ValueError: If there are any mismatches.
    """
    file_ids = set(discover_patient_ids())
    outcome_ids = set(load_outcomes()["RecordID"].values)

    files_no_outcome = file_ids - outcome_ids
    outcomes_no_file = outcome_ids - file_ids

    if files_no_outcome or outcomes_no_file:
        raise ValueError(
            f"Patient / outcome ID mismatch!\n"
            f"  Files without outcome: {len(files_no_outcome)}\n"
            f"  Outcomes without file: {len(outcomes_no_file)}"
        )

    return file_ids, outcome_ids
