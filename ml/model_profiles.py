"""Explicit model versions shared by bundle training and application loading."""

MODEL_PROFILES = {
    "original": {
        "label": "Original Random Forest",
        "model_family": "Random Forest V2",
        "directory": "",
        "manifest_filename": "rf_v2_manifest.json",
        "filenames": {checkpoint: f"rf_v2_{checkpoint}.joblib" for checkpoint in ("6h", "12h", "24h")},
        "description": "Historical model and thresholds. Scores are not calibrated probabilities.",
    },
    "calibrated": {
        "label": "Calibrated research candidate",
        "model_family": "Calibrated Random Forest V3",
        "directory": "calibrated_rf_v3",
        "manifest_filename": "calibrated_rf_v3_manifest.json",
        "filenames": {checkpoint: f"rf_v3_{checkpoint}.joblib" for checkpoint in ("6h", "12h", "24h")},
        "description": "Sigmoid calibration and training-selected thresholds. Research candidate; no clear improvement in warning accuracy or proven clinical safety.",
    },
}
