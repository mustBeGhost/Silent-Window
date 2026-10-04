"""
Silent Window -- Cross-Validated Model Comparison (V2 features)
================================================================
Run from project root::

    python -m ml.train_models

Compares Logistic Regression and Random Forest using 5-fold
stratified CV on the 2,560 DEVELOPMENT patients only.

The 640-patient held-out set is NEVER evaluated here.

METHODOLOGY:
    1. Load split_metadata.json to identify the 640 held-out IDs.
    2. Use ONLY the remaining 2,560 development patients.
    3. 5-fold StratifiedKFold (shuffle=True, random_state=42).
    4. V2 features (V1 + slope) at 6h, 12h, 24h cutoffs.
    5. Preprocessing fitted per fold on training portion only.
    6. Report mean +/- std ROC-AUC and PR-AUC plus confusion stats.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.data_loader import (
    discover_patient_ids,
    load_outcomes,
    load_patient,
    validate_id_matching,
)
from ml.features import (
    LEAKAGE_COLUMNS,
    V1_EXCLUDED,
    build_feature_matrix,
    get_feature_columns_v2,
)
from ml.preprocessing import preprocess_patient

# -- Constants -------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "model_comparison"
BASELINE_DIR = PROJECT_ROOT / "data" / "processed" / "baseline"

CUTOFFS = {"6h": 360, "12h": 720, "24h": 1440}
RANDOM_STATE = 42
N_SPLITS = 5
FEATURE_VERSION = 2


# ==========================================================================
# PIPELINE BUILDERS
# ==========================================================================

def _build_preprocessor(feature_cols: list[str]) -> ColumnTransformer:
    cat_cols = ["ICUType"]
    num_cols = [c for c in feature_cols if c not in cat_cols]
    return ColumnTransformer(
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


def build_lr_pipeline(feature_cols: list[str]) -> Pipeline:
    return Pipeline([
        ("preprocess", _build_preprocessor(feature_cols)),
        ("classifier", LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            random_state=RANDOM_STATE,
            solver="lbfgs",
        )),
    ])


def build_rf_pipeline(feature_cols: list[str]) -> Pipeline:
    return Pipeline([
        ("preprocess", _build_preprocessor(feature_cols)),
        ("classifier", RandomForestClassifier(
            n_estimators=200,
            max_depth=12,
            min_samples_leaf=10,
            class_weight="balanced",
            random_state=RANDOM_STATE,
            n_jobs=-1,
        )),
    ])


MODEL_BUILDERS = {
    "LogReg": build_lr_pipeline,
    "RF": build_rf_pipeline,
}


# ==========================================================================
# DATA LOADING
# ==========================================================================

def load_all_patients(patient_ids: list[int] | None = None) -> dict[int, pd.DataFrame]:
    ids = discover_patient_ids() if patient_ids is None else list(patient_ids)
    data: dict[int, pd.DataFrame] = {}
    for i, pid in enumerate(ids):
        data[pid] = preprocess_patient(load_patient(pid))
        if (i + 1) % 500 == 0:
            print(f"  Loaded {i + 1}/{len(ids)} patients")
    return data


def get_development_ids() -> tuple[list[int], list[int]]:
    """Load split metadata and return (dev_ids, holdout_ids)."""
    meta_path = BASELINE_DIR / "split_metadata.json"
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    holdout_ids = meta["test_ids"]  # Previously examined; excluded from development fitting.
    train_ids = meta["train_ids"]   # 2560 development patients
    return train_ids, holdout_ids


# ==========================================================================
# CROSS-VALIDATION
# ==========================================================================

def cross_validate_model(
    model_name: str,
    X: pd.DataFrame,
    y: pd.Series,
    feature_cols: list[str],
    cutoff_label: str,
) -> dict:
    """Run 5-fold stratified CV for one model at one cutoff."""
    skf = StratifiedKFold(
        n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE,
    )

    fold_metrics: list[dict] = []
    agg_y_true, agg_y_pred, agg_y_prob = [], [], []

    for fold_idx, (train_idx, val_idx) in enumerate(skf.split(X, y)):
        X_tr = X.iloc[train_idx]
        X_va = X.iloc[val_idx]
        y_tr = y.iloc[train_idx]
        y_va = y.iloc[val_idx]

        pipe = MODEL_BUILDERS[model_name](feature_cols)
        pipe.fit(X_tr, y_tr)

        y_pred = pipe.predict(X_va)
        y_prob = pipe.predict_proba(X_va)[:, 1]

        fold_metrics.append({
            "roc_auc": roc_auc_score(y_va, y_prob),
            "pr_auc": average_precision_score(y_va, y_prob),
            "precision": precision_score(y_va, y_pred, zero_division=0),
            "recall": recall_score(y_va, y_pred, zero_division=0),
            "f1": f1_score(y_va, y_pred, zero_division=0),
        })

        agg_y_true.extend(y_va.values)
        agg_y_pred.extend(y_pred)
        agg_y_prob.extend(y_prob)

    # Aggregate
    fm = pd.DataFrame(fold_metrics)
    agg_cm = confusion_matrix(agg_y_true, agg_y_pred)
    tn, fp, fn, tp = agg_cm.ravel()

    result = {
        "model": model_name,
        "cutoff": cutoff_label,
        "roc_auc_mean": round(fm["roc_auc"].mean(), 4),
        "roc_auc_std": round(fm["roc_auc"].std(), 4),
        "pr_auc_mean": round(fm["pr_auc"].mean(), 4),
        "pr_auc_std": round(fm["pr_auc"].std(), 4),
        "precision_mean": round(fm["precision"].mean(), 4),
        "recall_mean": round(fm["recall"].mean(), 4),
        "f1_mean": round(fm["f1"].mean(), 4),
        "oof_tp": int(tp),
        "oof_fp": int(fp),
        "oof_tn": int(tn),
        "oof_fn": int(fn),
        "oof_fpr": round(fp / (fp + tn), 4) if (fp + tn) > 0 else 0.0,
    }
    return result


# ==========================================================================
# AUDIT
# ==========================================================================

def audit_matrix(X: pd.DataFrame, label: str) -> None:
    cols = set(X.columns)
    for bad in LEAKAGE_COLUMNS:
        assert bad not in cols, f"LEAKAGE in {label}: {bad}"
    assert "PatientID" not in cols, f"{label}: PatientID in features"
    for excl in V1_EXCLUDED:
        excl_cols = [c for c in cols if c.startswith(excl)]
        assert not excl_cols, f"{label}: excluded {excl_cols}"


# ==========================================================================
# MAIN
# ==========================================================================

def main() -> None:
    print("Silent Window -- Cross-Validated Model Comparison (V2)")
    print("=" * 58)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # -- Validate ----------------------------------------------------------
    print("\n1. Validating input integrity...")
    validate_id_matching()
    dev_ids, holdout_ids = get_development_ids()
    all_ids = set(discover_patient_ids())

    assert set(dev_ids) & set(holdout_ids) == set(), \
        "Dev/holdout overlap!"
    assert set(dev_ids) | set(holdout_ids) == all_ids, \
        "Dev+holdout != all IDs"
    print(f"  Development patients: {len(dev_ids)}")
    print(f"  Separated development holdout (previously examined): {len(holdout_ids)}")

    # -- Load data ---------------------------------------------------------
    print("\n2. Loading development patients only...")
    patient_data = load_all_patients(dev_ids)
    outcomes = load_outcomes()

    # Build target series for development patients
    outcome_map = dict(zip(
        outcomes["RecordID"].values,
        outcomes["In-hospital_death"].values,
    ))
    y_dev = pd.Series(
        [outcome_map[pid] for pid in dev_ids],
        index=dev_ids,
        name="target",
    )
    print(f"  Dev positive: {int(y_dev.sum())} / {len(y_dev)} "
          f"({y_dev.mean()*100:.1f}%)")

    # -- Feature columns ---------------------------------------------------
    feature_cols = get_feature_columns_v2()
    print(f"\n3. V2 feature count: {len(feature_cols)}")

    # -- Save V2 schema ----------------------------------------------------
    schema_lines = [
        "Silent Window V2 Feature Schema",
        "=" * 40,
        f"Total features (before one-hot): {len(feature_cols)}",
        "",
        "V2 = V1 + slope per temporal parameter",
        "",
        "NEW in V2 (per temporal parameter):",
        "  {param}_slope  (least-squares, >=2 obs required)",
        "",
        "All V1 features retained.",
    ]
    (OUTPUT_DIR / "feature_schema_v2.txt").write_text(
        "\n".join(schema_lines), encoding="utf-8"
    )

    # -- CV per model x cutoff ---------------------------------------------
    all_results: list[dict] = []

    for cutoff_label, cutoff_min in CUTOFFS.items():
        print(f"\n{'=' * 58}")
        print(f"4. Building V2 features at {cutoff_label} "
              f"(cutoff={cutoff_min} min)...")
        X_dev = build_feature_matrix(
            dev_ids, patient_data, cutoff_min, version=FEATURE_VERSION,
        )
        audit_matrix(X_dev, f"{cutoff_label}_dev")
        print(f"  Leakage audit: PASSED")
        print(f"  Shape: {X_dev.shape}")

        for model_name in MODEL_BUILDERS:
            print(f"\n  -- {model_name} @ {cutoff_label} "
                  f"(5-fold CV) --")
            result = cross_validate_model(
                model_name, X_dev, y_dev, feature_cols, cutoff_label,
            )
            all_results.append(result)
            print(f"     ROC-AUC : {result['roc_auc_mean']:.4f} "
                  f"+/- {result['roc_auc_std']:.4f}")
            print(f"     PR-AUC  : {result['pr_auc_mean']:.4f} "
                  f"+/- {result['pr_auc_std']:.4f}")
            print(f"     Prec    : {result['precision_mean']:.4f}")
            print(f"     Recall  : {result['recall_mean']:.4f}")
            print(f"     F1      : {result['f1_mean']:.4f}")
            print(f"     OOF CM  : TP={result['oof_tp']} FP={result['oof_fp']} "
                  f"TN={result['oof_tn']} FN={result['oof_fn']}")
            print(f"     FPR     : {result['oof_fpr']:.4f}")

    # -- Save results ------------------------------------------------------
    results_df = pd.DataFrame(all_results)
    results_df.to_csv(OUTPUT_DIR / "cv_metrics.csv", index=False)

    # -- Summary -----------------------------------------------------------
    print(f"\n{'=' * 58}")
    print("CROSS-VALIDATION COMPARISON TABLE")
    print(f"{'=' * 58}")
    header = (f"{'Model':>8s} {'Cut':>4s} | "
              f"{'ROC-AUC':>15s} | {'PR-AUC':>15s} | "
              f"{'Prec':>6s} {'Rec':>6s} {'F1':>6s} | {'FPR':>6s}")
    print(header)
    print("-" * len(header))
    for r in all_results:
        print(f"{r['model']:>8s} {r['cutoff']:>4s} | "
              f"{r['roc_auc_mean']:.4f}+/-{r['roc_auc_std']:.4f} | "
              f"{r['pr_auc_mean']:.4f}+/-{r['pr_auc_std']:.4f} | "
              f"{r['precision_mean']:.4f} {r['recall_mean']:.4f} "
              f"{r['f1_mean']:.4f} | {r['oof_fpr']:.4f}")

    # -- Summary text file -------------------------------------------------
    summary_lines = [
        "Silent Window -- Model Comparison Summary",
        "=" * 50,
        "",
        "PROTOCOL:",
        f"  Development patients: {len(dev_ids)}",
        f"  Separated development holdout (previously examined): {len(holdout_ids)}",
        f"  CV: StratifiedKFold(n_splits={N_SPLITS}, "
        f"shuffle=True, random_state={RANDOM_STATE})",
        f"  Feature version: V2 (V1 + slope)",
        f"  Features (before OHE): {len(feature_cols)}",
        "",
        "MODELS:",
        "  LogReg: LogisticRegression(class_weight='balanced', "
        "max_iter=1000, solver='lbfgs')",
        "  RF: RandomForestClassifier(n_estimators=200, max_depth=12, "
        "min_samples_leaf=10, class_weight='balanced')",
        "",
        "RESULTS (mean +/- std across 5 folds):",
    ]
    for r in all_results:
        summary_lines.append(
            f"  {r['model']:>6s} @ {r['cutoff']}: "
            f"ROC-AUC={r['roc_auc_mean']:.4f}+/-{r['roc_auc_std']:.4f}  "
            f"PR-AUC={r['pr_auc_mean']:.4f}+/-{r['pr_auc_std']:.4f}  "
            f"FPR={r['oof_fpr']:.4f}"
        )
    summary_lines += [
        "",
        "NOTE: The 640-patient holdout was NOT evaluated by this command; its earlier baseline results have been examined.",
        "NOTE: Threshold tuning has NOT been performed.",
        "NOTE: Model selection should consider earliness vs performance.",
    ]
    (OUTPUT_DIR / "model_comparison_summary.txt").write_text(
        "\n".join(summary_lines), encoding="utf-8"
    )

    print(f"\nSaved outputs to {OUTPUT_DIR}")
    print("\n640 separated patients: NOT EVALUATED BY THIS COMMAND (previously examined baseline).")
    print("Done.")


if __name__ == "__main__":
    main()
