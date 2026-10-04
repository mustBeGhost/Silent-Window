"""Reproducible coverage and outcome-timing audit; no models are fitted/scored.

Run: python -m scripts.audit_checkpoint_coverage
Outputs go to data/processed/data_quality. Patient IDs in the audit CSV are for
local traceability only, never website responses. Outcome diagnostics are not
model inputs and never determine runtime scoring eligibility.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.coverage import COVERAGE_POLICY, checkpoint_coverage, summarize_coverage
from ml.data_loader import (
    get_outcomes_path, get_patient_dir, load_outcomes, load_patient,
)
from ml.preprocessing import preprocess_patient
from ml.train_models import CUTOFFS
from scripts.train_rf_v2_artifacts import (
    cohort_fingerprint, file_sha256, validated_training_cohorts,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "data_quality"
SOURCE_URL = "https://physionet.org/content/challenge-2012/1.0.0/"


def outcome_timing_diagnostics(outcomes: pd.DataFrame) -> dict:
    """Flag conflicts without treating rounded hospital days as ICU timestamps."""
    if outcomes["RecordID"].isna().any() or outcomes["RecordID"].duplicated().any():
        raise ValueError("Outcome IDs must be present and unique")
    if not outcomes["In-hospital_death"].isin([0, 1]).all():
        raise ValueError("Hospital-death labels must be binary and present")
    stay = outcomes["Length_of_stay"]
    survival = outcomes["Survival"]
    death = outcomes["In-hospital_death"] == 1
    flags = {
        "hospital_stay_unknown": stay.isna() | (stay == -1),
        "hospital_stay_0_or_1_days": stay.isin([0, 1]),
        "survival_0_or_1_days": survival.isin([0, 1]),
        "hospital_death_with_survival_0_or_1_days": death & survival.isin([0, 1]),
        "hospital_death_with_unknown_survival": death & (survival.isna() | (survival == -1)),
        "survival_less_than_known_hospital_stay_but_survivor_label": (
            ~death & (stay >= 0) & (survival >= 0) & (survival < stay)
        ),
    }
    return {
        "patients": len(outcomes),
        "hospital_death_labels": int(death.sum()),
        "flag_counts": {name: int(mask.sum()) for name, mask in flags.items()},
        "flagged_record_ids": {
            name: sorted(int(value) for value in outcomes.loc[mask, "RecordID"])
            for name, mask in flags.items()
        },
        "exact_icu_discharge_time_available": False,
        "exact_death_time_available": False,
        "landmark_eligibility": "UNKNOWN_FROM_AVAILABLE_FIELDS",
        "note": "Flags overlap. Day-level hospital outcomes cannot prove alive-and-in-ICU status at 6h/12h/24h. No patients were silently removed based on these flags.",
    }


def main() -> None:
    development, separated = validated_training_cohorts()
    outcomes = load_outcomes()
    all_ids = sorted(development + separated)
    if set(outcomes["RecordID"]) != set(all_ids):
        raise ValueError("Outcome IDs do not match the frozen cohorts")
    diagnostics = outcome_timing_diagnostics(outcomes)
    development_set = set(development)
    raw_digest = hashlib.sha256()
    rows = []
    short_records = {checkpoint: [] for checkpoint in CUTOFFS}
    for position, patient_id in enumerate(all_ids, start=1):
        path = get_patient_dir() / f"{patient_id}.txt"
        raw_digest.update(f"{patient_id}:{file_sha256(path)}\n".encode("ascii"))
        patient = preprocess_patient(load_patient(patient_id))
        if np.isinf(patient["Value"].to_numpy(dtype=float)).any():
            raise ValueError(f"Non-finite input in record {patient_id}")
        # Full-record extent is audit-only. It is never an earlier model input.
        last_recorded_minute = int(patient["Time_minutes"].max()) if len(patient) else 0
        for checkpoint, cutoff in CUTOFFS.items():
            rows.append({
                "record_id": patient_id,
                "cohort": "development" if patient_id in development_set else "development_holdout",
                "checkpoint": checkpoint,
                **checkpoint_coverage(patient, cutoff),
            })
            if last_recorded_minute < cutoff:
                short_records[checkpoint].append(patient_id)
        if position % 500 == 0:
            print(f"Audited {position}/{len(all_ids)} records", flush=True)
    coverage = pd.DataFrame(rows)
    summary = {
        "schema_version": 1,
        "coverage_policy": COVERAGE_POLICY,
        "source_documentation": SOURCE_URL,
        "raw_patient_files_sha256": raw_digest.hexdigest(),
        "outcomes_sha256": file_sha256(get_outcomes_path()),
        "split_sha256": file_sha256(PROJECT_ROOT / "data" / "processed" / "baseline" / "split_metadata.json"),
        "development_cohort_sha256": cohort_fingerprint(development),
        "source_sha256": {
            name: file_sha256(PROJECT_ROOT / name)
            for name in ("ml/coverage.py", "ml/data_loader.py", "ml/preprocessing.py", "scripts/audit_checkpoint_coverage.py")
        },
        "outcome_timing": diagnostics,
        "records_ending_before_checkpoint": {
            checkpoint: {"count": len(ids), "record_ids": ids} for checkpoint, ids in short_records.items()
        },
        "coverage": {
            cohort: {
                checkpoint: summarize_coverage(coverage[
                    (coverage["checkpoint"] == checkpoint)
                    & ((coverage["cohort"] == cohort) if cohort != "all" else True)
                ])
                for checkpoint in CUTOFFS
            }
            for cohort in ("all", "development", "development_holdout")
        },
        "limits": [
            "Coverage is descriptive, not proof of clinical sufficiency.",
            "Development-holdout coverage is data-quality reporting only, never performance evaluation or model selection.",
            "No exact ICU exit/death times exist here; checkpoint clinical eligibility remains unresolved.",
            "An observation file ending early does not prove discharge or death.",
        ],
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(OUTPUT_DIR / "checkpoint_coverage.csv", index=False)
    (OUTPUT_DIR / "coverage_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("Coverage audit complete; no models fitted or scored.", flush=True)
    print(json.dumps({
        "coverage": {
            checkpoint: {key: summary["coverage"]["development"][checkpoint][key]
                for key in ("patients", "scoreable_patients", "no_supported_measurements", "supported_parameter_count", "no_bedside_measurement")}
            for checkpoint in CUTOFFS
        },
        "timing_flags": diagnostics["flag_counts"],
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
