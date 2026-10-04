"""Recent-window research inputs, always restricted to the assessment prefix."""

import numpy as np
import pandas as pd

from ml.features import TEMPORAL_PARAMETERS, _compute_slope, build_patient_features, get_feature_columns_v2
from ml.preprocessing import observations_up_to

RECENT_WINDOW_MINUTES = 240
RECENT_STATS = ("first_to_latest_delta", "recent4h_mean", "recent4h_count",
                "recent4h_slope", "recent4h_vs_earlier_mean", "missing")


def get_recent_feature_columns():
    return get_feature_columns_v2() + [f"{parameter}_{stat}" for parameter in TEMPORAL_PARAMETERS for stat in RECENT_STATS]


def build_recent_patient_features(patient, cutoff_minutes):
    features = build_patient_features(patient, cutoff_minutes, version=2)
    visible = observations_up_to(patient, cutoff_minutes)
    for parameter in TEMPORAL_PARAMETERS:
        observations = visible[(visible.Parameter == parameter) & visible.Value.notna()].sort_values("Time_minutes", kind="stable")
        if not np.isfinite(observations.Value.to_numpy(dtype=float)).all():
            raise ValueError("Observed values must be finite")
        recent = observations[observations.Time_minutes > cutoff_minutes - RECENT_WINDOW_MINUTES]
        earlier = observations[observations.Time_minutes <= cutoff_minutes - RECENT_WINDOW_MINUTES]
        features[f"{parameter}_first_to_latest_delta"] = float(observations.Value.iloc[-1] - observations.Value.iloc[0]) if len(observations) >= 2 else np.nan
        features[f"{parameter}_recent4h_mean"] = float(recent.Value.mean()) if len(recent) else np.nan
        features[f"{parameter}_recent4h_count"] = len(recent)
        features[f"{parameter}_recent4h_slope"] = _compute_slope(recent.Time_minutes.to_numpy(), recent.Value.to_numpy())
        features[f"{parameter}_recent4h_vs_earlier_mean"] = float(recent.Value.mean() - earlier.Value.mean()) if len(recent) and len(earlier) else np.nan
        features[f"{parameter}_missing"] = int(observations.empty)
    return features


def build_recent_feature_matrix(patient_ids, patient_data, cutoff_minutes):
    if len(set(patient_ids)) != len(patient_ids):
        raise ValueError("Patient IDs must be unique")
    return pd.DataFrame([build_recent_patient_features(patient_data[patient_id], cutoff_minutes)
                         for patient_id in patient_ids], index=pd.Index(patient_ids, name="PatientID"),
                        columns=get_recent_feature_columns())
