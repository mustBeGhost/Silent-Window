"""
Silent Window — Preprocessing
===============================
Safe, minimal preprocessing for ICU patient observations.

Design rules:
    1. At prediction time *T*, only observations with Time ≤ T may be used.
    2. Sentinel ``-1`` is replaced with ``NaN`` **only** for Height, Weight,
       Gender — the three parameters verified to use ``-1`` as "unknown".
    3. Duplicate ``(Time, Parameter)`` resolution uses **median** for
       continuous measurements but **preserves** Urine duplicates.
    4. Gender is **never** averaged — it is categorical.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ── Constants ────────────────────────────────────────────────────────────

# Parameters whose -1 values are verified sentinels for "unknown".
SENTINEL_PARAMETERS: frozenset[str] = frozenset({"Height", "Weight", "Gender"})

# Static demographic parameters recorded once at admission (time 00:00).
STATIC_PARAMETERS: frozenset[str] = frozenset({
    "RecordID", "Age", "Gender", "Height", "ICUType", "Weight",
})

# Urine duplicates are preserved because multiple readings at the same
# timestamp may represent distinct clinical events (catheter vs. void).
# Aggregation without medical context could be misleading.
URINE_PARAMETER: str = "Urine"

# Categorical parameters that must never be averaged.
CATEGORICAL_PARAMETERS: frozenset[str] = frozenset({
    "Gender", "ICUType", "MechVent",
})


# ── Sentinel handling ────────────────────────────────────────────────────

def replace_sentinels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replace ``-1`` sentinel values with ``NaN``, **only** for the verified
    parameters: Height, Weight, Gender.

    Does **not** modify the original DataFrame.

    Args:
        df: Patient DataFrame with columns ``Parameter`` and ``Value``.

    Returns:
        New DataFrame with sentinels replaced.
    """
    df = df.copy()
    mask = df["Parameter"].isin(SENTINEL_PARAMETERS) & (df["Value"] == -1)
    df.loc[mask, "Value"] = np.nan
    return df


# ── Duplicate resolution ────────────────────────────────────────────────

def resolve_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Resolve duplicate ``(Time, Parameter)`` pairs.

    Strategy
    --------
    * **Static demographics** (RecordID, Age, Gender, Height, ICUType,
      Weight): keep the first valid (non-NaN) value.  Gender is **never**
      averaged.
    * **Urine**: all rows are preserved and flagged via a boolean column
      ``_dup_urine`` set to ``True``.  No aggregation is performed —
      deferred to clinical review.
    * **All other continuous measurements**: aggregated using **median**.

    Does **not** modify the original DataFrame.

    Args:
        df: Patient DataFrame with columns ``Time``, ``Time_minutes``,
            ``Parameter``, ``Value``.

    Returns:
        New DataFrame with duplicates resolved.  Contains an additional
        boolean column ``_dup_urine`` (``True`` for flagged Urine rows).
    """
    df = df.copy()
    df["_dup_urine"] = False

    dup_mask = df.duplicated(subset=["Time", "Parameter"], keep=False)
    if not dup_mask.any():
        return df

    non_dup = df[~dup_mask].copy()
    dup = df[dup_mask].copy()

    resolved_parts: list[pd.DataFrame] = [non_dup]

    for (time, param), group in dup.groupby(["Time", "Parameter"]):
        if param in STATIC_PARAMETERS:
            # Keep first valid (non-NaN) value; never average categoricals.
            valid = group.dropna(subset=["Value"])
            row = valid.iloc[[0]].copy() if len(valid) > 0 else group.iloc[[0]].copy()
            resolved_parts.append(row)

        elif param == URINE_PARAMETER:
            # Flag but preserve — aggregation strategy TBD.
            flagged = group.copy()
            flagged["_dup_urine"] = True
            resolved_parts.append(flagged)

        elif param in CATEGORICAL_PARAMETERS:
            # Categorical parameters (e.g. MechVent) must never be
            # averaged.  Keep the first valid (non-NaN) value, identical
            # to the static-parameter rule.
            valid = group.dropna(subset=["Value"])
            row = valid.iloc[[0]].copy() if len(valid) > 0 else group.iloc[[0]].copy()
            resolved_parts.append(row)

        else:
            # Continuous measurement -> median.
            median_val = group["Value"].median()
            row = group.iloc[[0]].copy()
            row["Value"] = median_val
            resolved_parts.append(row)

    result = pd.concat(resolved_parts, ignore_index=True)
    result = result.sort_values("Time_minutes", kind="stable").reset_index(drop=True)
    return result


# ── Chronological filter (SAFETY-CRITICAL) ───────────────────────────────

def observations_up_to(
    patient_df: pd.DataFrame,
    cutoff_minutes: int,
) -> pd.DataFrame:
    """
    Return **only** observations with ``Time_minutes <= cutoff_minutes``.

    This function is **safety-critical** for the early-warning system:
    future observations must never leak into predictions at time *T*.

    Args:
        patient_df: Patient DataFrame containing a ``Time_minutes`` column.
        cutoff_minutes: Maximum allowed time in minutes (inclusive).
                        Must be in ``[0, 2880]``.

    Returns:
        Filtered copy of the DataFrame.

    Raises:
        ValueError: If *cutoff_minutes* is outside ``[0, 2880]``.
        KeyError: If ``Time_minutes`` column is missing.
    """
    if not isinstance(cutoff_minutes, (int, float)):
        raise ValueError(
            f"cutoff_minutes must be numeric, got {type(cutoff_minutes).__name__}"
        )
    if cutoff_minutes < 0:
        raise ValueError(f"cutoff_minutes must be >= 0, got {cutoff_minutes}")
    if cutoff_minutes > 2880:
        raise ValueError(
            f"cutoff_minutes must be <= 2880 (48 hours), got {cutoff_minutes}"
        )
    if "Time_minutes" not in patient_df.columns:
        raise KeyError("DataFrame missing required column: Time_minutes")

    return patient_df[patient_df["Time_minutes"] <= cutoff_minutes].copy()


# ── Combined pipeline ───────────────────────────────────────────────────

def preprocess_patient(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply the full safe preprocessing pipeline to a patient DataFrame.

    Steps (in order):
        1. Replace sentinels (``-1`` → ``NaN`` for Height, Weight, Gender).
        2. Resolve duplicate ``(Time, Parameter)`` pairs.
        3. Ensure chronological order.

    Does **not** modify the original DataFrame.
    Does **not** apply chronological filtering — call
    :func:`observations_up_to` separately.

    Args:
        df: Raw patient DataFrame from :func:`ml.data_loader.load_patient`.

    Returns:
        Preprocessed DataFrame.
    """
    result = replace_sentinels(df)
    result = resolve_duplicates(result)
    return result
