"""
Silent Window -- Feature Engineering (V1)
==========================================
Chronology-safe feature generation for ICU early-warning prediction.

SAFETY RULE:
    Every feature at cutoff T is computed using **only** observations
    where Time_minutes <= T.  This is enforced by calling
    ``observations_up_to()`` from ``ml.preprocessing``.

V1 SCOPE:
    - Static features : Age, Gender, Weight, ICUType
    - Temporal params : HR, GCS, Temp, MAP, SysABP, DiasABP, Glucose,
                        Creatinine, BUN, WBC, Platelets, HCT, Na, K,
                        HCO3, Mg
    - Temporal stats  : latest, mean, min, max, std, count, time_since_last

EXCLUDED FROM V1:
    - Height  (47% missing, suspicious extremes)
    - Urine   (duplicate aggregation semantics unresolved)
    - Slope/trend (deferred to V2 for correctness baseline first)
    - Sparse params (RespRate, Troponin, Cholesterol, etc.)

EXCLUDED FROM ALL VERSIONS (leakage / identifier):
    - RecordID, In-hospital_death, Survival, Length_of_stay, SAPS-I, SOFA
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from ml.preprocessing import observations_up_to

# -- V1 parameter lists ---------------------------------------------------

STATIC_FEATURES: list[str] = ["Age", "Gender", "Weight", "ICUType"]

TEMPORAL_PARAMETERS: list[str] = [
    "HR", "GCS", "Temp", "MAP", "SysABP", "DiasABP",
    "Glucose", "Creatinine", "BUN", "WBC", "Platelets",
    "HCT", "Na", "K", "HCO3", "Mg",
]

# Temporal statistics generated per parameter (V1)
TEMPORAL_STATS: list[str] = [
    "latest", "mean", "min", "max", "std", "count", "time_since_last",
]

# V2 adds slope
TEMPORAL_STATS_V2: list[str] = TEMPORAL_STATS + ["slope"]

# Parameters explicitly excluded from V1/V2
V1_EXCLUDED: frozenset[str] = frozenset({"Height", "Urine"})

# Outcome/identifier columns that must NEVER be features
LEAKAGE_COLUMNS: frozenset[str] = frozenset({
    "RecordID", "In-hospital_death", "Survival",
    "Length_of_stay", "SAPS-I", "SOFA",
})


def get_feature_columns() -> list[str]:
    """Return the deterministic, ordered list of V1 feature column names."""
    cols: list[str] = list(STATIC_FEATURES)
    for param in TEMPORAL_PARAMETERS:
        for stat in TEMPORAL_STATS:
            cols.append(f"{param}_{stat}")
    return cols


def get_feature_columns_v2() -> list[str]:
    """Return the deterministic, ordered list of V2 feature column names.

    V2 = V1 + one slope feature per temporal parameter.
    """
    cols: list[str] = list(STATIC_FEATURES)
    for param in TEMPORAL_PARAMETERS:
        for stat in TEMPORAL_STATS_V2:
            cols.append(f"{param}_{stat}")
    return cols


def _compute_slope(times: np.ndarray, values: np.ndarray) -> float:
    """Compute least-squares slope of value over time.

    Args:
        times: 1-D array of measurement times in minutes.
        values: 1-D array of measurement values.

    Returns:
        Slope (value per minute).  Returns ``NaN`` if fewer than 2
        measurements or if all timestamps are identical.
    """
    if len(values) < 2:
        return np.nan
    t = times.astype(float)
    v = values.astype(float)
    t_range = t.max() - t.min()
    if t_range == 0:
        # All measurements at the same timestamp -> slope undefined
        return np.nan
    # Least-squares: slope = cov(t,v) / var(t)
    t_mean = t.mean()
    v_mean = v.mean()
    numerator = ((t - t_mean) * (v - v_mean)).sum()
    denominator = ((t - t_mean) ** 2).sum()
    if denominator == 0:
        return np.nan
    slope = numerator / denominator
    # Guard against infinity from floating-point edge cases
    if not np.isfinite(slope):
        return np.nan
    return float(slope)


def build_patient_features(
    patient_df: pd.DataFrame,
    cutoff_minutes: int,
    version: int = 1,
) -> dict[str, object]:
    """
    Build a single feature row for one patient at a specified cutoff.

    Uses ``observations_up_to()`` to enforce chronological safety --
    observations after ``cutoff_minutes`` are never used.

    Args:
        patient_df: Preprocessed patient DataFrame (output of
            ``preprocess_patient``).  Must contain columns:
            ``Time``, ``Time_minutes``, ``Parameter``, ``Value``.
        cutoff_minutes: Prediction cutoff in minutes.  Must be in
            ``[0, 2880]``.
        version: Feature version.  1 = V1 (no slope), 2 = V2 (with slope).

    Returns:
        Dictionary mapping feature names to values.  Missing features
        are ``NaN`` (numeric) or ``0`` (counts).  Column order matches
        ``get_feature_columns()`` (V1) or ``get_feature_columns_v2()`` (V2).
    """
    # Enforce chronological safety
    obs = observations_up_to(patient_df, cutoff_minutes)

    features: dict[str, object] = {}

    # -- Static features (recorded at time 0) ------------------------------
    for param in STATIC_FEATURES:
        row = obs[(obs["Parameter"] == param) & (obs["Time_minutes"] == 0)]
        if len(row) > 0:
            features[param] = row.iloc[0]["Value"]
        else:
            features[param] = np.nan

    # -- Temporal features -------------------------------------------------
    for param in TEMPORAL_PARAMETERS:
        param_obs = obs[obs["Parameter"] == param]
        values = param_obs["Value"].dropna()
        times = param_obs.loc[values.index, "Time_minutes"]

        if len(values) == 0:
            features[f"{param}_latest"] = np.nan
            features[f"{param}_mean"] = np.nan
            features[f"{param}_min"] = np.nan
            features[f"{param}_max"] = np.nan
            features[f"{param}_std"] = np.nan
            features[f"{param}_count"] = 0
            features[f"{param}_time_since_last"] = np.nan
            if version >= 2:
                features[f"{param}_slope"] = np.nan
        else:
            # latest = last observed valid value (chronological order)
            last_idx = values.index[-1]
            features[f"{param}_latest"] = values.iloc[-1]
            features[f"{param}_mean"] = values.mean()
            features[f"{param}_min"] = values.min()
            features[f"{param}_max"] = values.max()
            features[f"{param}_std"] = values.std() if len(values) >= 2 else np.nan
            features[f"{param}_count"] = len(values)
            last_time = times.loc[last_idx]
            features[f"{param}_time_since_last"] = cutoff_minutes - last_time

            if version >= 2:
                features[f"{param}_slope"] = _compute_slope(
                    times.values, values.values
                )

    return features


def build_feature_matrix(
    patient_ids: list[int],
    patient_data: dict[int, pd.DataFrame],
    cutoff_minutes: int,
    version: int = 1,
) -> pd.DataFrame:
    """
    Build a feature matrix for multiple patients at a single cutoff.

    Args:
        patient_ids: List of patient IDs.
        patient_data: Mapping from patient ID to preprocessed DataFrame.
        cutoff_minutes: Prediction cutoff.
        version: Feature version (1 or 2).

    Returns:
        DataFrame with one row per patient, columns from
        ``get_feature_columns()`` (V1) or ``get_feature_columns_v2()`` (V2),
        indexed by patient ID.
    """
    rows: list[dict] = []
    for pid in patient_ids:
        feats = build_patient_features(
            patient_data[pid], cutoff_minutes, version=version,
        )
        feats["PatientID"] = pid
        rows.append(feats)

    df = pd.DataFrame(rows)
    df = df.set_index("PatientID")

    # Enforce deterministic column order
    expected_cols = (
        get_feature_columns_v2() if version >= 2 else get_feature_columns()
    )
    df = df[expected_cols]
    return df
