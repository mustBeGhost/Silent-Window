"""Application registry extension; historical profile definitions stay intact."""
from ml.model_profiles import MODEL_PROFILES as HISTORICAL_PROFILES
from ml.checkpoint_expansion import CUTOFFS

MODEL_PROFILES = {
    **HISTORICAL_PROFILES,
    "expanded": {
        "label": "Five-checkpoint research candidate",
        "model_family": "Calibrated Random Forest V4",
        "directory": "expanded_rf_v4",
        "manifest_filename": "expanded_rf_v4_manifest.json",
        "filenames": {cp: f"rf_v4_{cp}.joblib" for cp in CUTOFFS},
        "description": "6h, 9h, 12h, 18h and 24h assessments; 85% training recall target. Research demonstration with substantial survivor warnings.",
    },
}


def profile_cutoffs(profile):
    if profile not in MODEL_PROFILES:
        raise ValueError("Unknown model profile")
    return dict(CUTOFFS) if profile == "expanded" else {"6h": 360, "12h": 720, "24h": 1440}
