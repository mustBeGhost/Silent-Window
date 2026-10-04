"""Checkpoint data coverage, independent of outcomes and future observations."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.features import STATIC_FEATURES, TEMPORAL_PARAMETERS
from ml.preprocessing import observations_up_to


BEDSIDE_PARAMETERS = ("HR", "GCS", "Temp", "MAP", "SysABP", "DiasABP")
COVERAGE_POLICY = "at_least_one_supported_temporal_observation_v1"


def usable_temporal_counts(matrix: pd.DataFrame) -> pd.Series:
    """Count observed inputs, excluding demographics and imputed values."""
    columns = [f"{parameter}_count" for parameter in TEMPORAL_PARAMETERS]
    counts = matrix[columns]
    if (
        not np.isfinite(counts.to_numpy(dtype=float)).all()
        or (counts < 0).any().any()
        or (counts % 1 != 0).any().any()
    ):
        raise ValueError("Temporal counts must be finite non-negative integers")
    return counts.sum(axis=1).astype(int)


def checkpoint_coverage(patient: pd.DataFrame, cutoff_minutes: int) -> dict:
    """Measure the preprocessed prefix without guessing clinical sufficiency.

    Age of the newest reading is a descriptive measure. It is not a validated
    freshness rule; labs and bedside measurements have different schedules.
    """
    visible = observations_up_to(patient, cutoff_minutes)
    supported = visible[
        visible["Parameter"].isin(TEMPORAL_PARAMETERS) & visible["Value"].notna()
    ]
    if not np.isfinite(supported["Value"].to_numpy(dtype=float)).all():
        raise ValueError("Supported observations must be finite")
    latest_times = supported.groupby("Parameter")["Time_minutes"].max()
    bedside = supported[supported["Parameter"].isin(BEDSIDE_PARAMETERS)]
    counts = supported["Parameter"].value_counts()
    static = visible[(visible["Time_minutes"] == 0) & visible["Value"].notna()]
    result = {
        "cutoff_minutes": cutoff_minutes,
        "scoreable": not supported.empty,
        "temporal_observation_count": len(supported),
        "supported_parameter_count": len(latest_times),
        "missing_static_parameter_count": sum(
            parameter not in set(static["Parameter"]) for parameter in STATIC_FEATURES
        ),
        "newest_measurement_age_minutes": (
            int(cutoff_minutes - supported["Time_minutes"].max()) if not supported.empty else None
        ),
        "newest_bedside_measurement_age_minutes": (
            int(cutoff_minutes - bedside["Time_minutes"].max()) if not bedside.empty else None
        ),
    }
    for parameter in TEMPORAL_PARAMETERS:
        result[f"{parameter}_count"] = int(counts.get(parameter, 0))
        result[f"{parameter}_age_minutes"] = (
            int(cutoff_minutes - latest_times[parameter]) if parameter in latest_times else None
        )
    return result


def summarize_coverage(rows: pd.DataFrame) -> dict:
    """Aggregate coverage only; these are not model-performance results."""
    def distribution(values: pd.Series) -> dict | None:
        known = values.dropna()
        if known.empty:
            return None
        return {
            "known_count": len(known),
            "min": float(known.min()),
            "median": float(known.median()),
            "p90": float(known.quantile(0.9)),
            "max": float(known.max()),
        }

    total = len(rows)
    return {
        "patients": total,
        "scoreable_patients": int(rows["scoreable"].sum()),
        "no_supported_measurements": int((~rows["scoreable"]).sum()),
        "patients_with_at_most_three_supported_parameters": int(
            (rows["supported_parameter_count"] <= 3).sum()
        ),
        "supported_parameter_count": distribution(rows["supported_parameter_count"]),
        "temporal_observation_count": distribution(rows["temporal_observation_count"]),
        "newest_measurement_age_minutes": distribution(rows["newest_measurement_age_minutes"]),
        "newest_bedside_measurement_age_minutes": distribution(rows["newest_bedside_measurement_age_minutes"]),
        "no_bedside_measurement": int(rows["newest_bedside_measurement_age_minutes"].isna().sum()),
        # These bins describe the data. They do not gate scoring or select a model.
        "newest_bedside_measurement_older_than_6h": int(
            (rows["newest_bedside_measurement_age_minutes"] > 360).sum()
        ),
        "parameter_presence": {
            parameter: {
                "patients_with_measurement": int((rows[f"{parameter}_count"] > 0).sum()),
                "patients_missing_measurement": int((rows[f"{parameter}_count"] == 0).sum()),
                "latest_age_minutes": distribution(rows[f"{parameter}_age_minutes"]),
            }
            for parameter in TEMPORAL_PARAMETERS
        },
    }
