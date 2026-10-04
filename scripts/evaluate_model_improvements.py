"""Evaluate fixed model/input candidates without replacing deployed models."""

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from threadpoolctl import threadpool_limits

from ml.features import get_feature_columns_v2
from ml.model_improvement import CANDIDATES, RECALL_TARGET, candidate_model, evaluate_model_improvements
from ml.recent_features import RECENT_STATS, RECENT_WINDOW_MINUTES, build_recent_feature_matrix, get_recent_feature_columns
from ml.train_models import CUTOFFS, audit_matrix
from scripts.evaluate_recall_targets import SOURCES as PRIOR_SOURCES, raw_digest
from scripts.train_rf_v2_artifacts import cohort_fingerprint, file_sha256, load_development_patients, load_development_target, validated_training_cohorts
from ml.data_loader import get_outcomes_path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/processed/evaluation_v3/model_improvement_metrics.json"
WEBSITE = ROOT / "frontend/src/data/modelImprovements.json"
BASELINE = ROOT / "data/processed/evaluation_v3/recall_target_metrics.json"
SOURCES = (*PRIOR_SOURCES, "ml/recent_features.py", "ml/model_improvement.py", "scripts/evaluate_model_improvements.py")


def website_summary(report):
    return {
        "status": report["status"], "completed_at_utc": report["completed_at_utc"],
        "training_recall_target": RECALL_TARGET, "primary_checkpoint": "12h",
        "development_patients": report["development_patients"], "death_labels": report["death_labels"],
        "research_promotion_gate": report["research_promotion_gate"],
        "selected_in_folds": [fold["training_selected_candidate"] for fold in report["fold_results"]],
        "candidates": [{"id": name, **settings, **report["results"][name]}
                       for name, settings in report["candidate_definitions"].items()],
        "training_selected": report["results"]["training_selected"],
    }


def main():
    development, separated = validated_training_cohorts()
    baseline = json.loads(BASELINE.read_text())
    protected_paths = list((ROOT / "ml/artifacts").rglob("*.joblib")) + list((ROOT / "ml/artifacts").rglob("*manifest.json"))
    protected_paths += list((ROOT / "data/processed/evaluation_v3").glob("*.json"))
    protected_paths = [path for path in protected_paths if path != OUTPUT]
    protected = {str(path.relative_to(ROOT)): file_sha256(path) for path in protected_paths}
    sources = {name: file_sha256(ROOT / name) for name in SOURCES}
    data_hashes = {
        "raw_development_patient_files_sha256": raw_digest(development),
        "outcomes_sha256": file_sha256(get_outcomes_path()),
        "split_sha256": file_sha256(ROOT / "data/processed/baseline/split_metadata.json"),
        "development_cohort_sha256": cohort_fingerprint(development),
        "separated_cohort_sha256": cohort_fingerprint(separated),
    }
    if any(baseline[name] != value for name, value in data_hashes.items()):
        raise RuntimeError("Input data differs from the earlier threshold experiment")
    print("Fixed six-candidate comparison at 85% training recall. No separated patients evaluated.", flush=True)
    print("Research promotion gate: no fewer detected than the RF control and at least 10% fewer survivor warnings.", flush=True)
    patient_data = load_development_patients(development)
    target = load_development_target(development)
    matrices = {"v2": {}, "recent": {}}
    for checkpoint, cutoff in CUTOFFS.items():
        print(f"Building prefix-only recent-window inputs at {checkpoint}", flush=True)
        matrix = build_recent_feature_matrix(development, patient_data, cutoff)
        if np.isinf(matrix.to_numpy(dtype=float)).any():
            raise ValueError("Infinite recent features")
        matrices["recent"][checkpoint] = matrix
        matrices["v2"][checkpoint] = matrix[get_feature_columns_v2()].copy()
        audit_matrix(matrices["v2"][checkpoint], f"{checkpoint}_improvement_control")
    del patient_data
    # Bound OpenMP/BLAS use for reproducible local runs; model workers also use one job.
    with threadpool_limits(limits=1):
        results = evaluate_model_improvements(matrices, target, development, separated,
                                             progress=lambda message: print(message, flush=True))
    if results["results"]["rf_v2"]["any_warning"] != baseline["results"]["calibrated"]["85"]["checkpoints"]["12h"]["any_warning"]:
        raise RuntimeError("RF control failed to reproduce the previous 85% warning results")
    if any(file_sha256(ROOT / name) != value for name, value in protected.items()):
        raise RuntimeError("A protected model or earlier report changed during evaluation")
    if any(file_sha256(ROOT / name) != value for name, value in sources.items()):
        raise RuntimeError("Experiment source changed during evaluation")
    if raw_digest(development) != data_hashes["raw_development_patient_files_sha256"] or file_sha256(get_outcomes_path()) != data_hashes["outcomes_sha256"] or file_sha256(ROOT / "data/processed/baseline/split_metadata.json") != data_hashes["split_sha256"]:
        raise RuntimeError("Input data changed during evaluation")
    definitions = {}
    for name, settings in CANDIDATES.items():
        model = candidate_model(name, list(matrices[settings["features"]]["12h"].columns))
        estimator = model.estimator.named_steps["classifier"]
        definitions[name] = {**settings, "feature_count": len(matrices[settings["features"]]["12h"].columns),
                             "classifier": type(estimator).__name__, "classifier_settings": estimator.get_params()}
    report = {
        "schema_version": 1, "status": "EXPLORATORY_NESTED_DEVELOPMENT_ONLY_NOT_DEPLOYED",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(), "target": "In-hospital_death",
        "primary_checkpoint": "12h", "training_recall_target": RECALL_TARGET,
        "runtime_versions": {"python": platform.python_version(), "sklearn": sklearn.__version__,
                             "pandas": pd.__version__, "numpy": np.__version__},
        "outer_cv": baseline["outer_cv"], "calibration": baseline["calibration"],
        "threshold_selection": {**baseline["threshold_selection"], "engineering_recall_floors": {"medium": RECALL_TARGET, "high": 0.30}},
        "model_selection": {"population": "INNER_OOF_TRAINING_ONLY", "objective": "minimum survivor FP meeting 85% training recall; TP then AP then name break ties",
                            "feature_sets_and_hyperparameters_fixed_before_run": True, "outer_labels_used_for_selection": False},
        "recent_features": {"window_minutes": RECENT_WINDOW_MINUTES, "statistics": list(RECENT_STATS),
                            "ordered_columns": get_recent_feature_columns(), "missing_values_are_not_filled_from_future": True},
        "candidate_definitions": definitions, **data_hashes, "source_sha256": sources,
        "protected_file_sha256": protected, "control_reproduced": True, "separated_patients_evaluated": 0, **results,
        "limitations": [
            "Known development patients were reused; this is exploratory evidence, not an untouched final test.",
            "Outer validation labels were not used for model or threshold selection. Fixed-candidate comparisons are descriptive.",
            "The selected procedure may use different families across folds; its score is not the score of a single globally selected family.",
            "Targets are training recall goals, not guarantees; validation recall can differ between candidates.",
            "The 10% research promotion gate is an engineering choice and is not a clinical safety standard.",
            "Survivor warnings are false positives against death labels; actual clinical need and event timing are unknown.",
            "Measurement availability can reflect hospital practices, so recent-window/count features may not transfer to other hospitals.",
            "No individual predictions were persisted and no model bundles or runtime thresholds changed.",
        ],
    }
    OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    WEBSITE.write_text(json.dumps(website_summary(report), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for name, metrics in results["results"].items():
        counts = metrics["any_warning"]
        print(f"{name}: detected {counts['tp']}, missed {counts['fn']}, survivors warned {counts['fp']}, ROC-AUC {metrics['roc_auc']:.4f}", flush=True)
    print(f"Training-selected procedure passes research gate: {results['research_promotion_gate']['passed']}", flush=True)


if __name__ == "__main__":
    main()
