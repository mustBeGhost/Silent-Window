"""
Silent Window — Dataset Inspection Script
==========================================
Performs structural, quality, and chronology checks on the PhysioNet
ICU dataset WITHOUT modifying any source files.

Run from the project root:
    python scripts/inspect_dataset.py
"""

import pandas as pd
import numpy as np
from pathlib import Path
from collections import Counter


# ── Paths ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "raw" / "dataset_2" / "train"
PATIENT_DIR = DATA_DIR / "set-a"
OUTCOMES_FILE = DATA_DIR / "Outcomes-train.txt"


def time_to_minutes(t: str) -> int:
    """Convert 'HH:MM' timestamp to total minutes."""
    parts = str(t).split(":")
    return int(parts[0]) * 60 + int(parts[1])


# ═══════════════════════════════════════════════════════════════════════════
# 1. STRUCTURE CHECK
# ═══════════════════════════════════════════════════════════════════════════
def check_structure():
    print("=" * 60)
    print("1. DATASET STRUCTURE")
    print("=" * 60)

    assert DATA_DIR.exists(), f"Data directory not found: {DATA_DIR}"
    assert PATIENT_DIR.exists(), f"Patient directory not found: {PATIENT_DIR}"
    assert OUTCOMES_FILE.exists(), f"Outcomes file not found: {OUTCOMES_FILE}"

    patient_files = sorted(PATIENT_DIR.glob("*.txt"))
    print(f"  Patient directory : {PATIENT_DIR.relative_to(PROJECT_ROOT)}")
    print(f"  Outcomes file     : {OUTCOMES_FILE.relative_to(PROJECT_ROOT)}")
    print(f"  Patient files     : {len(patient_files)}")
    print(f"  File extension    : .txt")
    return patient_files


# ═══════════════════════════════════════════════════════════════════════════
# 2. PATIENT FILE FORMAT
# ═══════════════════════════════════════════════════════════════════════════
def check_patient_format(patient_files):
    print()
    print("=" * 60)
    print("2. PATIENT FILE FORMAT")
    print("=" * 60)

    record_counts = []
    all_params = Counter()

    for f in patient_files:
        df = pd.read_csv(f)
        record_counts.append(len(df))
        all_params.update(df["Parameter"].unique())

    print(f"  Columns           : Time, Parameter, Value")
    print(f"  Time format       : HH:MM (elapsed hours:minutes from admission)")
    print(f"  Records per patient:")
    print(f"    Min             : {min(record_counts)}")
    print(f"    Max             : {max(record_counts)}")
    print(f"    Mean            : {np.mean(record_counts):.1f}")
    print(f"  Unique parameters : {len(all_params)}")
    print()
    print("  Parameter frequency (patients with at least one reading):")
    for param, count in all_params.most_common():
        pct = count / len(patient_files) * 100
        print(f"    {param:<15s}: {count:>5d} / {len(patient_files)}  ({pct:5.1f}%)")

    return all_params


# ═══════════════════════════════════════════════════════════════════════════
# 3. OUTCOMES / LABELS
# ═══════════════════════════════════════════════════════════════════════════
def check_outcomes(patient_files):
    print()
    print("=" * 60)
    print("3. OUTCOMES / LABELS")
    print("=" * 60)

    outcomes = pd.read_csv(OUTCOMES_FILE)
    print(f"  Columns           : {list(outcomes.columns)}")
    print(f"  Total patients    : {len(outcomes)}")
    print(f"  Unique RecordIDs  : {outcomes['RecordID'].nunique()}")
    print(f"  Duplicate IDs     : {outcomes['RecordID'].duplicated().sum()}")
    print()

    # In-hospital_death distribution
    deaths = outcomes["In-hospital_death"]
    pos = int(deaths.sum())
    neg = len(deaths) - pos
    print(f"  In-hospital_death:")
    print(f"    Positive (died) : {pos}")
    print(f"    Negative (lived): {neg}")
    print(f"    Positive rate   : {pos / len(deaths) * 100:.2f}%")
    print(f"    Missing labels  : {deaths.isna().sum()}")
    print()

    # Sentinel values in outcomes
    saps_missing = int((outcomes["SAPS-I"] == -1).sum())
    surv_missing = int((outcomes["Survival"] == -1).sum())
    print(f"  Sentinel -1 values:")
    print(f"    SAPS-I == -1    : {saps_missing}")
    print(f"    Survival == -1  : {surv_missing}")
    print()

    # ID matching
    file_ids = {int(f.stem) for f in patient_files}
    outcome_ids = set(outcomes["RecordID"].values)
    files_no_outcome = file_ids - outcome_ids
    outcomes_no_file = outcome_ids - file_ids
    print(f"  Patient-Outcome matching:")
    print(f"    Files without outcome : {len(files_no_outcome)}")
    print(f"    Outcomes without file : {len(outcomes_no_file)}")
    if files_no_outcome:
        print(f"      IDs: {sorted(files_no_outcome)[:10]}")
    if outcomes_no_file:
        print(f"      IDs: {sorted(outcomes_no_file)[:10]}")

    return outcomes


# ═══════════════════════════════════════════════════════════════════════════
# 4. CHRONOLOGY CHECK
# ═══════════════════════════════════════════════════════════════════════════
def check_chronology(patient_files):
    print()
    print("=" * 60)
    print("4. TIME / CHRONOLOGY")
    print("=" * 60)

    global_min = float("inf")
    global_max = float("-inf")
    not_sorted_count = 0
    out_of_range_count = 0

    for f in patient_files:
        df = pd.read_csv(f)
        minutes = [time_to_minutes(t) for t in df["Time"]]

        local_min, local_max = min(minutes), max(minutes)
        global_min = min(global_min, local_min)
        global_max = max(global_max, local_max)

        # Chronological order
        if not all(minutes[i] <= minutes[i + 1] for i in range(len(minutes) - 1)):
            not_sorted_count += 1

        # Out-of-range
        for m in minutes:
            if m < 0 or m > 2880:
                out_of_range_count += 1

    print(f"  Earliest observation : {global_min} min  ({global_min // 60}h {global_min % 60}m)")
    print(f"  Latest observation   : {global_max} min  ({global_max // 60}h {global_max % 60}m)")
    print(f"  Observation window   : ~{global_max // 60} hours")
    print(f"  Files NOT sorted     : {not_sorted_count}")
    print(f"  Records outside 0-48h: {out_of_range_count}")


# ═══════════════════════════════════════════════════════════════════════════
# 5. MISSING-DATA CHECK
# ═══════════════════════════════════════════════════════════════════════════
def check_missing_data(patient_files):
    print()
    print("=" * 60)
    print("5. MISSING-DATA CHECK")
    print("=" * 60)

    sentinel_counts = Counter()
    for f in patient_files:
        df = pd.read_csv(f)
        mask = df["Value"].astype(float) == -1
        for param in df.loc[mask, "Parameter"]:
            sentinel_counts[param] += 1

    print("  Sentinel -1 values by parameter:")
    if sentinel_counts:
        for param, count in sentinel_counts.most_common():
            print(f"    {param:<15s}: {count}")
    else:
        print("    (none)")

    print()
    print("  Missingness mechanism:")
    print("    - Absent rows   : parameters simply not recorded at a timestamp")
    print("    - Sentinel -1   : Height, Weight, Gender use -1 for unknown")
    print("    - NaN           : not observed in this dataset")


# ═══════════════════════════════════════════════════════════════════════════
# 6. DATA QUALITY CHECK
# ═══════════════════════════════════════════════════════════════════════════
def check_data_quality(patient_files):
    print()
    print("=" * 60)
    print("6. DATA QUALITY")
    print("=" * 60)

    dup_rows = 0
    empty_files = []
    non_numeric = 0
    multi_time_param = 0

    for f in patient_files:
        df = pd.read_csv(f)

        if len(df) == 0:
            empty_files.append(f.name)
            continue

        dup_rows += int(df.duplicated().sum())

        # Non-numeric values
        for v in df["Value"]:
            try:
                float(v)
            except (ValueError, TypeError):
                non_numeric += 1

        # Duplicate (time, parameter) pairs
        tp = list(zip(df["Time"], df["Parameter"]))
        if len(tp) != len(set(tp)):
            multi_time_param += 1

    print(f"  Duplicate rows            : {dup_rows}")
    print(f"  Empty patient files       : {len(empty_files)}")
    print(f"  Non-numeric values        : {non_numeric}")
    print(f"  Files with dup (time,param): {multi_time_param}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════
def main():
    print()
    print("Silent Window — Dataset Inspection")
    print("=" * 60)

    patient_files = check_structure()
    check_patient_format(patient_files)
    check_outcomes(patient_files)
    check_chronology(patient_files)
    check_missing_data(patient_files)
    check_data_quality(patient_files)

    print()
    print("=" * 60)
    print("INSPECTION COMPLETE — no data was modified.")
    print("=" * 60)


if __name__ == "__main__":
    main()
