"""
Silent Window -- Logistic Regression Baseline (V1)
====================================================
Run from project root::

    python -m ml.train_baseline

Trains three independent LogisticRegression models at 6 h, 12 h, 24 h
cutoffs using chronology-safe features.

METHODOLOGY GUARANTEES:
    1. Single patient-level train/test split (80/20, stratified,
       random_state=42) shared across all three cutoffs.
    2. Preprocessing (imputation + scaling) fitted on training set ONLY.
    3. class_weight="balanced" to handle the 6.2:1 imbalance.
    4. Evaluation on held-out test set per cutoff.
    5. No outcome-file columns used as features.
    6. RecordID used only for joining; never a model feature.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# -- Project imports -------------------------------------------------------
from ml.data_loader import (
    discover_patient_ids,
    load_outcomes,
    load_patient,
    validate_id_matching,
)
from ml.features import (
    LEAKAGE_COLUMNS,
    STATIC_FEATURES,
    TEMPORAL_PARAMETERS,
    TEMPORAL_STATS,
    build_feature_matrix,
    get_feature_columns,
)
from ml.preprocessing import preprocess_patient

# -- Paths -----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "baseline"
ARTIFACT_DIR = PROJECT_ROOT / "ml" / "artifacts"

CUTOFFS = {
    "6h": 360,
    "12h": 720,
    "24h": 1440,
}

RANDOM_STATE = 42


# ==========================================================================
# 1.  DATA LOADING
# ==========================================================================

def load_all_patients() -> dict[int, pd.DataFrame]:
    """Load and preprocess all patients.  Returns {pid: DataFrame}."""
    ids = discover_patient_ids()
    data: dict[int, pd.DataFrame] = {}
    for i, pid in enumerate(ids):
        data[pid] = preprocess_patient(load_patient(pid))
        if (i + 1) % 500 == 0:
            print(f"  Loaded {i + 1}/{len(ids)} patients")
    return data


# ==========================================================================
# 2.  TRAIN / TEST SPLIT
# ==========================================================================

def create_split(
    outcomes: pd.DataFrame,
) -> tuple[list[int], list[int], pd.Series, pd.Series]:
    """
    Create a single patient-level 80/20 stratified split.

    Returns:
        (train_ids, test_ids, y_train, y_test)
    """
    ids = outcomes["RecordID"].values
    y = outcomes["In-hospital_death"].values

    train_ids, test_ids, y_train, y_test = train_test_split(
        ids, y,
        test_size=0.20,
        random_state=RANDOM_STATE,
        stratify=y,
    )
    return (
        list(train_ids), list(test_ids),
        pd.Series(y_train, index=train_ids, name="target"),
        pd.Series(y_test, index=test_ids, name="target"),
    )


# ==========================================================================
# 3.  SKLEARN PREPROCESSING PIPELINE
# ==========================================================================

def build_sklearn_pipeline() -> Pipeline:
    """
    Build a scikit-learn Pipeline with ColumnTransformer.

    - Numerical features: median impute -> standard scale
    - ICUType: most-frequent impute -> one-hot encode
    - Gender: treated as binary numeric (median impute -> scale)
    """
    feature_cols = get_feature_columns()

    # ICUType is the only multi-class categorical in V1
    cat_cols = ["ICUType"]

    # Everything else is numeric (including binary Gender)
    num_cols = [c for c in feature_cols if c not in cat_cols]

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]), num_cols),
            ("cat", Pipeline([
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("encoder", OneHotEncoder(handle_unknown="ignore",
                                          sparse_output=False)),
            ]), cat_cols),
        ],
        remainder="drop",
    )

    pipe = Pipeline([
        ("preprocess", preprocessor),
        ("classifier", LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            random_state=RANDOM_STATE,
            solver="lbfgs",
        )),
    ])
    return pipe


# ==========================================================================
# 4.  EVALUATION
# ==========================================================================

def evaluate(
    pipe: Pipeline,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    label: str,
) -> dict:
    """Evaluate a fitted pipeline on the test set."""
    y_pred = pipe.predict(X_test)
    y_prob = pipe.predict_proba(X_test)[:, 1]

    roc = roc_auc_score(y_test, y_prob)
    pr = average_precision_score(y_test, y_prob)
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)
    cm = confusion_matrix(y_test, y_pred)

    metrics = {
        "cutoff": label,
        "roc_auc": round(roc, 4),
        "pr_auc": round(pr, 4),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(f1, 4),
        "test_size": len(y_test),
        "test_positive": int(y_test.sum()),
        "predicted_positive": int(y_pred.sum()),
        "tn": int(cm[0, 0]),
        "fp": int(cm[0, 1]),
        "fn": int(cm[1, 0]),
        "tp": int(cm[1, 1]),
    }

    print(f"\n{'=' * 50}")
    print(f"  {label} MODEL  (threshold=0.50)")
    print(f"{'=' * 50}")
    print(f"  ROC-AUC           : {metrics['roc_auc']:.4f}")
    print(f"  PR-AUC (Avg Prec) : {metrics['pr_auc']:.4f}")
    print(f"  Precision         : {metrics['precision']:.4f}")
    print(f"  Recall            : {metrics['recall']:.4f}")
    print(f"  F1                : {metrics['f1']:.4f}")
    print(f"  Test size         : {metrics['test_size']}")
    print(f"  Test positive     : {metrics['test_positive']} "
          f"({metrics['test_positive']/metrics['test_size']*100:.1f}%)")
    print(f"  Predicted positive: {metrics['predicted_positive']}")
    print(f"  Confusion matrix  :")
    print(f"    TN={metrics['tn']}  FP={metrics['fp']}")
    print(f"    FN={metrics['fn']}  TP={metrics['tp']}")

    return metrics


# ==========================================================================
# 5.  LEAKAGE AUDIT
# ==========================================================================

def audit_features(X: pd.DataFrame, label: str) -> None:
    """Assert no leakage columns exist in feature matrix."""
    cols = set(X.columns)
    for bad in LEAKAGE_COLUMNS:
        assert bad not in cols, f"LEAKAGE DETECTED in {label}: {bad} in features!"
    # Also check no patient ID column
    assert "PatientID" not in cols, f"{label}: PatientID found in features!"
    # Check V1 exclusions
    for excl in ["Height", "Urine"]:
        excl_cols = [c for c in cols if c.startswith(excl)]
        assert not excl_cols, f"{label}: excluded column(s) found: {excl_cols}"


# ==========================================================================
# 6.  MAIN
# ==========================================================================

def main() -> None:
    print("Silent Window -- Logistic Regression Baseline (V1)")
    print("=" * 55)

    # -- Directories -------------------------------------------------------
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    # -- Load data ---------------------------------------------------------
    print("\n1. Loading all patients...")
    patient_data = load_all_patients()
    outcomes = load_outcomes()

    # -- Input integrity validation ----------------------------------------
    print("\n2. Validating input integrity...")
    validate_id_matching()  # raises on mismatch
    print("  Patient-file IDs == outcome IDs: OK")

    file_ids = set(discover_patient_ids())
    outcome_ids = outcomes["RecordID"].values
    labels = outcomes["In-hospital_death"].values

    assert len(outcome_ids) == len(set(outcome_ids)), \
        "Outcome patient IDs are not unique!"
    assert len(file_ids) == len(discover_patient_ids()), \
        "Patient file IDs are not unique!"
    assert not pd.Series(labels).isna().any(), \
        "Labels contain missing values!"
    assert set(np.unique(labels)) <= {0, 1}, \
        f"Labels are not binary {{0,1}}: {set(np.unique(labels))}"
    print("  Unique IDs, non-missing binary labels: OK")

    # -- Split -------------------------------------------------------------
    print("\n3. Creating train/test split (80/20, stratified, seed=42)...")
    train_ids, test_ids, y_train, y_test = create_split(outcomes)

    # Verify split integrity
    train_set = set(train_ids)
    test_set = set(test_ids)
    overlap = train_set & test_set
    assert len(train_ids) == len(train_set), "Duplicate train IDs!"
    assert len(test_ids) == len(test_set), "Duplicate test IDs!"
    assert len(overlap) == 0, f"FATAL: {len(overlap)} patients in both sets!"
    assert train_set | test_set == file_ids, \
        "Union of train+test does not equal all dataset patient IDs!"
    print(f"  Train: {len(train_ids)} ({int(y_train.sum())} positive)")
    print(f"  Test : {len(test_ids)} ({int(y_test.sum())} positive)")
    print(f"  Overlap: {len(overlap)} (must be 0)")
    print(f"  Union == all IDs: OK")

    # Save split metadata
    split_meta = {
        "random_state": RANDOM_STATE,
        "test_size": 0.20,
        "train_count": len(train_ids),
        "test_count": len(test_ids),
        "train_positive": int(y_train.sum()),
        "test_positive": int(y_test.sum()),
        "train_ids": sorted(int(x) for x in train_ids),
        "test_ids": sorted(int(x) for x in test_ids),
    }
    meta_path = OUTPUT_DIR / "split_metadata.json"
    meta_path.write_text(json.dumps(split_meta, indent=2), encoding="utf-8")
    print(f"  Saved split metadata -> {meta_path.name}")

    # Save feature schema
    schema_path = OUTPUT_DIR / "feature_schema.txt"
    schema_lines = [
        "Silent Window V1 Feature Schema",
        "=" * 40,
        f"Total features (before one-hot): {len(get_feature_columns())}",
        "",
        "STATIC FEATURES:",
    ]
    for f in STATIC_FEATURES:
        schema_lines.append(f"  {f}")
    schema_lines.append("")
    schema_lines.append("TEMPORAL FEATURES (per parameter):")
    for stat in TEMPORAL_STATS:
        schema_lines.append(f"  {{param}}_{stat}")
    schema_lines.append("")
    schema_lines.append("TEMPORAL PARAMETERS:")
    for p in TEMPORAL_PARAMETERS:
        schema_lines.append(f"  {p}")
    schema_lines.append("")
    schema_lines.append("EXCLUDED FROM V1:")
    schema_lines.append("  Height (47% missing, suspicious extremes)")
    schema_lines.append("  Urine (duplicate aggregation unresolved)")
    schema_lines.append("")
    schema_lines.append("Gender: treated as binary numeric (0/1),")
    schema_lines.append("  imputed with median, scaled with StandardScaler.")
    schema_lines.append("ICUType: categorical, imputed with most_frequent,")
    schema_lines.append("  encoded with OneHotEncoder(handle_unknown='ignore').")
    schema_path.write_text("\n".join(schema_lines), encoding="utf-8")
    print(f"  Saved feature schema -> {schema_path.name}")

    # -- Train & evaluate per cutoff ---------------------------------------
    all_metrics: list[dict] = []

    for label, cutoff in CUTOFFS.items():
        print(f"\n{'=' * 55}")
        print(f"3. Building features for {label} (cutoff={cutoff} min)...")

        X_train = build_feature_matrix(train_ids, patient_data, cutoff)
        X_test = build_feature_matrix(test_ids, patient_data, cutoff)

        # LEAKAGE AUDIT
        audit_features(X_train, f"{label}_train")
        audit_features(X_test, f"{label}_test")
        print(f"  Leakage audit: PASSED")

        # Align y with feature matrix index
        y_tr = y_train.loc[X_train.index]
        y_te = y_test.loc[X_test.index]

        # Build and fit pipeline (on TRAINING data only)
        pipe = build_sklearn_pipeline()
        pipe.fit(X_train, y_tr)

        # Evaluate
        metrics = evaluate(pipe, X_test, y_te, label)
        all_metrics.append(metrics)

        # Save model artifact
        artifact_path = ARTIFACT_DIR / f"logistic_{label}.joblib"
        joblib.dump(pipe, artifact_path)
        print(f"  Saved model -> {artifact_path.name}")

    # -- Comparison table --------------------------------------------------
    print(f"\n{'=' * 55}")
    print("BASELINE COMPARISON TABLE")
    print(f"{'=' * 55}")
    print(f"{'Cutoff':>8s} | {'ROC-AUC':>8s} | {'PR-AUC':>8s} | "
          f"{'Prec':>6s} | {'Recall':>6s} | {'F1':>6s}")
    print("-" * 55)
    for m in all_metrics:
        print(f"{m['cutoff']:>8s} | {m['roc_auc']:>8.4f} | {m['pr_auc']:>8.4f} | "
              f"{m['precision']:>6.4f} | {m['recall']:>6.4f} | {m['f1']:>6.4f}")

    print(f"\nInterpretation: earlier cutoffs trade predictive power for")
    print(f"earlier warning.  This is a V1 baseline; performance is")
    print(f"expected to improve with additional features and models.")

    # -- Save metrics ------------------------------------------------------
    metrics_df = pd.DataFrame(all_metrics)
    metrics_path = OUTPUT_DIR / "baseline_metrics.csv"
    metrics_df.to_csv(metrics_path, index=False)
    print(f"\nSaved metrics -> {metrics_path.name}")

    # -- Final leakage summary ---------------------------------------------
    print(f"\n{'=' * 55}")
    print("LEAKAGE AUDIT SUMMARY")
    print(f"{'=' * 55}")
    print(f"  RecordID in X          : NO")
    print(f"  In-hospital_death in X : NO")
    print(f"  Survival in X          : NO")
    print(f"  Length_of_stay in X    : NO")
    print(f"  SAPS-I in X            : NO")
    print(f"  SOFA in X              : NO")
    print(f"  Urine in V1 X          : NO")
    print(f"  Height in V1 X         : NO")
    print(f"  Train/test overlap     : 0")
    print(f"  Same split all cutoffs : YES")
    print(f"  Preprocess fit on train: YES")
    print(f"  Chronology enforced    : YES (observations_up_to)")

    print(f"\nDone. All outputs saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
