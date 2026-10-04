import numpy as np
import pandas as pd
import pytest

from ml.features import LEAKAGE_COLUMNS, build_patient_features, get_feature_columns_v2
from ml.recent_features import build_recent_feature_matrix, build_recent_patient_features, get_recent_feature_columns


def patient():
    return pd.DataFrame({"Parameter": ["Age", "HR", "HR", "HR", "HR", "HR", "RecordID", "Urine"],
                         "Time_minutes": [0, 100, 480, 600, 720, 900, 0, 700],
                         "Value": [60, 70, 80, 90, 100, 999, 12345, 1000]})


def test_recent_windows_have_exact_boundary_and_expected_change():
    result = build_recent_patient_features(patient(), 720)
    assert result["HR_recent4h_count"] == 2  # timestamp 480 belongs to earlier window
    assert result["HR_recent4h_mean"] == 95
    assert result["HR_recent4h_vs_earlier_mean"] == 20
    assert result["HR_first_to_latest_delta"] == 30
    assert result["HR_recent4h_slope"] == pytest.approx(10 / 120)
    assert result["HR_missing"] == 0


@pytest.mark.parametrize("cutoff", [360, 720, 1440])
def test_future_changes_cannot_affect_recent_or_original_inputs(cutoff):
    original = patient()
    future = pd.DataFrame({"Parameter": ["HR", "Age", "MAP"], "Time_minutes": [cutoff + 1] * 3, "Value": [1e9, 1e8, 1e7]})
    changed = pd.concat([original[original.Time_minutes <= cutoff], future], ignore_index=True)
    before = build_recent_patient_features(original, cutoff)
    after = build_recent_patient_features(changed, cutoff)
    pd.testing.assert_series_equal(pd.Series(before), pd.Series(after))
    base = build_patient_features(original, cutoff, version=2)
    pd.testing.assert_series_equal(pd.Series({name: before[name] for name in get_feature_columns_v2()}), pd.Series(base))


def test_absent_recent_measurements_stay_missing_instead_of_forward_filled():
    result = build_recent_patient_features(patient(), 1440)
    assert result["HR_recent4h_count"] == 0
    assert np.isnan(result["HR_recent4h_mean"])
    assert np.isnan(result["HR_recent4h_vs_earlier_mean"])
    assert result["HR_missing"] == 0  # old measurements still exist in the full prefix
    assert result["MAP_missing"] == 1
    assert np.isnan(result["MAP_first_to_latest_delta"])


def test_recent_feature_matrix_schema_has_no_outcomes_or_ids():
    matrix = build_recent_feature_matrix([123], {123: patient()}, 720)
    assert list(matrix.columns) == get_recent_feature_columns()
    assert len(matrix.columns) == 228
    assert not LEAKAGE_COLUMNS & set(matrix.columns)
    assert not np.isinf(matrix.to_numpy()).any()
    changed = patient()
    changed.loc[changed.Parameter.isin(["RecordID", "Urine"]), "Value"] = -123
    pd.testing.assert_frame_equal(matrix, build_recent_feature_matrix([123], {123: changed}, 720))
