"""Integrity tests for aggregate Model Performance visualization data."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import auc

from ml.features import get_feature_columns_v2
from ml.model_performance import readable_feature_label
from ml.train_models import get_development_ids
from scripts.train_rf_v2_artifacts import cohort_fingerprint, file_sha256


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = (
    PROJECT_ROOT / "frontend" / "src" / "data"
    / "modelPerformance.json"
)
ARTIFACT_DIR = PROJECT_ROOT / "ml" / "artifacts"
MANIFEST_PATH = ARTIFACT_DIR / "rf_v2_manifest.json"
CV_METRICS_PATH = (
    PROJECT_ROOT / "data" / "processed" / "model_comparison"
    / "cv_metrics.csv"
)


@pytest.fixture(scope="module")
def visualization_data() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_visualization_metadata_is_development_only(
    visualization_data,
) -> None:
    metadata = visualization_data["metadata"]
    development_ids, separated_ids = get_development_ids()

    assert len(development_ids) == 2560
    assert len(separated_ids) == 640
    assert set(development_ids).isdisjoint(separated_ids)
    assert metadata == {
        "model_family": "Random Forest V2",
        "primary_checkpoint": "12h",
        "validation_method": "Development 5-fold cross-validation",
        "development_cohort_size": 2560,
        "development_cohort_sha256": cohort_fingerprint(development_ids),
        "n_splits": 5,
        "random_state": 42,
        "feature_version": "V2",
    }


def test_roc_artifact_has_all_supported_checkpoints(
    visualization_data,
) -> None:
    curves = visualization_data["roc_curves"]

    assert [curve["checkpoint"] for curve in curves] == ["6h", "12h", "24h"]
    assert [curve["primary"] for curve in curves] == [False, True, False]


@pytest.mark.parametrize("checkpoint", ["6h", "12h", "24h"])
def test_roc_coordinates_are_valid_and_auc_matches_curve(
    visualization_data,
    checkpoint,
) -> None:
    curve = next(
        item for item in visualization_data["roc_curves"]
        if item["checkpoint"] == checkpoint
    )
    fpr = np.array([point["fpr"] for point in curve["points"]])
    tpr = np.array([point["tpr"] for point in curve["points"]])

    assert np.all((0 <= fpr) & (fpr <= 1))
    assert np.all((0 <= tpr) & (tpr <= 1))
    assert np.all(np.diff(fpr) >= 0)
    assert (fpr[0], tpr[0]) == (0, 0)
    assert (fpr[-1], tpr[-1]) == (1, 1)
    assert auc(fpr, tpr) == pytest.approx(curve["roc_auc"], abs=1e-8)


def test_reproduced_fold_auc_matches_recorded_development_cv(
    visualization_data,
) -> None:
    recorded = pd.read_csv(CV_METRICS_PATH)
    recorded = recorded[recorded["model"] == "RF"].set_index("cutoff")

    for curve in visualization_data["roc_curves"]:
        checkpoint = curve["checkpoint"]
        assert round(curve["fold_mean_roc_auc"], 4) == pytest.approx(
            recorded.loc[checkpoint, "roc_auc_mean"], abs=1e-12,
        )
        assert round(curve["fold_std_roc_auc"], 4) == pytest.approx(
            recorded.loc[checkpoint, "roc_auc_std"], abs=1e-12,
        )


def test_feature_importance_matches_fitted_12h_artifact(
    visualization_data,
    manifest,
) -> None:
    section = visualization_data["feature_importance"]
    artifact_path = ARTIFACT_DIR / manifest["artifacts"]["12h"]["filename"]
    model = joblib.load(artifact_path)
    classifier = next(
        step for step in model.named_steps.values()
        if isinstance(step, RandomForestClassifier)
    )
    preprocessor = next(
        step for step in model.named_steps.values()
        if step is not classifier
        and callable(getattr(step, "get_feature_names_out", None))
    )
    classifier.n_jobs = 1
    transformed_names = list(preprocessor.get_feature_names_out())
    importances = np.asarray(classifier.feature_importances_)
    ranked = np.argsort(-importances, kind="stable")[:10]

    assert list(model.feature_names_in_) == get_feature_columns_v2()
    assert len(transformed_names) == len(importances) == 135
    assert section["input_feature_count"] == 132
    assert section["transformed_feature_count"] == 135
    assert section["top_n"] == 10
    for rank, (stored, index) in enumerate(
        zip(section["features"], ranked, strict=True), start=1
    ):
        assert stored["rank"] == rank
        assert stored["technical_name"] == transformed_names[index]
        assert stored["label"] == readable_feature_label(
            transformed_names[index]
        )
        assert stored["importance"] == pytest.approx(
            importances[index], abs=5e-13,
        )


def test_feature_importances_are_ordered_highest_first(
    visualization_data,
) -> None:
    values = [
        item["importance"]
        for item in visualization_data["feature_importance"]["features"]
    ]

    assert values == sorted(values, reverse=True)


def test_visualization_artifact_contains_no_patient_level_data(
    visualization_data,
) -> None:
    serialized = json.dumps(visualization_data).lower()
    forbidden = {
        "patient_id",
        "recordid",
        "record_id",
        "y_true",
        "y_prob",
        "in-hospital_death",
        "outcome",
        "observation",
        "separated_cohort",
        "filesystem",
    }

    assert all(term not in serialized for term in forbidden)
    assert DATA_PATH.stat().st_size < 200_000


@pytest.mark.parametrize("checkpoint", ["6h", "12h", "24h"])
def test_production_rf_artifact_hashes_remain_manifested(
    manifest,
    checkpoint,
) -> None:
    artifact = manifest["artifacts"][checkpoint]
    artifact_path = ARTIFACT_DIR / artifact["filename"]

    assert file_sha256(artifact_path) == artifact["sha256"]


def test_feature_importance_source_hash_is_the_12h_artifact(
    visualization_data,
    manifest,
) -> None:
    assert visualization_data["feature_importance"]["source_model_sha256"] == (
        manifest["artifacts"]["12h"]["sha256"]
    )
