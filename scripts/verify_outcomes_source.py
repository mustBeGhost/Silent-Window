"""Compare local outcomes with the public PhysioNet source, without replacing data."""

import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

from ml.data_loader import get_outcomes_path, load_outcomes
from scripts.train_rf_v2_artifacts import file_sha256


SOURCE_URL = "https://physionet.org/files/challenge-2012/1.0.0/Outcomes-a.txt"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "data_quality" / "outcome_source_verification.json"


def compare_outcomes(local: pd.DataFrame, official: pd.DataFrame) -> dict:
    if set(local.columns) != set(official.columns) or "RecordID" not in local:
        raise ValueError("Outcome source columns do not match")
    if local["RecordID"].duplicated().any() or official["RecordID"].duplicated().any():
        raise ValueError("Outcome sources must have unique patient IDs")
    local = local.set_index("RecordID").sort_index()
    official = official.set_index("RecordID").sort_index()
    missing = sorted(set(local.index) - set(official.index))
    common = local.index.intersection(official.index)
    matches = local.loc[common].eq(official.loc[common, local.columns]).all(axis=1)
    mismatched = sorted(int(value) for value in common[~matches])
    return {
        "local_rows": len(local), "official_rows": len(official),
        "matched_local_rows": int(matches.sum()),
        "local_ids_missing_from_official_source": [int(value) for value in missing],
        "mismatched_local_record_ids": mismatched,
        "all_local_outcome_rows_match_source": not missing and not mismatched,
    }


def main() -> None:
    with urlopen(SOURCE_URL, timeout=30) as response:
        raw = response.read()
    official = pd.read_csv(io.BytesIO(raw))
    report = {
        "source_url": SOURCE_URL,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "local_outcomes_sha256": file_sha256(get_outcomes_path()),
        **compare_outcomes(load_outcomes(), official),
        "note": "This checks the outcome rows only, not observation-file provenance or exact clinical checkpoint eligibility. No data was replaced.",
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["all_local_outcome_rows_match_source"]:
        raise RuntimeError("Local outcomes differ from the public source; review the verification report")


if __name__ == "__main__":
    main()
