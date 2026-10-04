"""Generate aggregate OOF threshold and alert-policy outputs.

Run from the project root:

    python -m scripts.run_alert_policy_analysis

No patient-level predictions are written to disk, and the 640-patient
holdout is excluded before feature generation and OOF prediction.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.alert_policy import probability_to_risk_level
from ml.data_loader import load_outcomes, load_patient, validate_id_matching
from ml.features import build_feature_matrix, get_feature_columns_v2
from ml.preprocessing import preprocess_patient
from ml.threshold_analysis import (
    DEFAULT_THRESHOLD_GRID,
    analyze_development_oof_thresholds,
    generate_oof_predictions,
    select_operating_points,
)
from ml.train_models import (
    CUTOFFS,
    N_SPLITS,
    RANDOM_STATE,
    audit_matrix,
    build_rf_pipeline,
    get_development_ids,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "alert_policy"


def _format_metrics_row(row: pd.Series) -> str:
    return (
        f"  {row['threshold']:.2f}  {int(row['tp']):3d}  "
        f"{int(row['fp']):4d}  {int(row['tn']):4d}  {int(row['fn']):3d}  "
        f"{row['precision']:.4f}  {row['recall']:.4f}  "
        f"{row['specificity']:.4f}  {row['false_positive_rate']:.4f}  "
        f"{row['f1']:.4f}"
    )


def main() -> None:
    print("Silent Window -- OOF Threshold and Alert-Policy Analysis")
    print("=" * 62)
    validate_id_matching()
    development_ids, holdout_ids = get_development_ids()
    if set(development_ids) & set(holdout_ids):
        raise RuntimeError("Development and holdout cohorts overlap")
    print(f"Development patients used: {len(development_ids)}")
    print(f"Held-out patients excluded: {len(holdout_ids)}")

    outcomes = load_outcomes().set_index("RecordID")
    y_development = outcomes.loc[development_ids, "In-hospital_death"].rename(
        "target"
    )

    patient_data = {}
    for position, patient_id in enumerate(development_ids, start=1):
        patient_data[patient_id] = preprocess_patient(load_patient(patient_id))
        if position % 500 == 0:
            print(f"  Loaded {position}/{len(development_ids)} development patients")

    feature_columns = get_feature_columns_v2()
    all_metrics: list[pd.DataFrame] = []
    for cutoff_label, cutoff_minutes in CUTOFFS.items():
        print(f"Generating RF OOF probabilities at {cutoff_label}...")
        X_development = build_feature_matrix(
            development_ids,
            patient_data,
            cutoff_minutes,
            version=2,
        )
        audit_matrix(X_development, f"{cutoff_label}_development")
        oof_predictions = generate_oof_predictions(
            X_development,
            y_development,
            lambda: build_rf_pipeline(feature_columns),
            n_splits=N_SPLITS,
            random_state=RANDOM_STATE,
        )
        metrics = analyze_development_oof_thresholds(
            oof_predictions,
            development_ids,
            holdout_ids,
            DEFAULT_THRESHOLD_GRID,
        )
        metrics.insert(0, "cutoff", cutoff_label)
        all_metrics.append(metrics)
        del oof_predictions

    threshold_metrics = pd.concat(all_metrics, ignore_index=True)
    metrics_12h = threshold_metrics[threshold_metrics["cutoff"] == "12h"]
    operating_points = select_operating_points(metrics_12h)
    selected = operating_points.set_index("operating_point")
    medium_threshold = float(selected.loc["HIGH_SENSITIVITY", "threshold"])
    high_threshold = float(selected.loc["LOWER_FALSE_ALARM", "threshold"])
    if medium_threshold >= high_threshold:
        raise RuntimeError(
            "Selected thresholds do not define ordered risk levels; "
            "review the fixed-grid operating-point rules"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    threshold_metrics.to_csv(OUTPUT_DIR / "threshold_metrics.csv", index=False)

    summary = [
        "Silent Window -- Alert Policy Summary",
        "=" * 48,
        "",
        "SAFETY AND SCOPE",
        "  Thresholds were derived only from OOF predictions for the 2,560",
        "  development patients.",
        "  The 640-patient held-out cohort was excluded and final held-out",
        "  evaluation has NOT been performed.",
        "  No identifying patient-level predictions were saved.",
        "  This policy is NOT clinically validated.",
        "  It is intended for a hackathon decision-support demonstration.",
        "",
        "THRESHOLD GRID",
        "  RF V2 OOF probabilities at 6h, 12h, and 24h.",
        f"  Fixed thresholds: {', '.join(f'{x:.2f}' for x in DEFAULT_THRESHOLD_GRID)}",
        "",
        "RF 12H THRESHOLD TRADEOFFS",
        "  thr   TP    FP    TN   FN    prec     recall   spec     FPR      F1",
    ]
    summary.extend(_format_metrics_row(row) for _, row in metrics_12h.iterrows())
    summary += [
        "",
        "ENGINEERING OPERATING-POINT RULES (RF 12H OOF ONLY)",
        "  HIGH_SENSITIVITY: lowest FPR among grid points with recall >= 0.70;",
        "    fallback is maximum recall then lowest FPR.",
        "  BALANCED: maximum F1, then lowest FPR.",
        "  LOWER_FALSE_ALARM: lowest FPR among grid points with recall >= 0.30;",
        "    fallback is maximum recall then lowest FPR.",
        "  Remaining ties prefer higher precision, then higher threshold.",
        "",
        "SELECTED OPERATING POINTS",
    ]
    for _, row in operating_points.iterrows():
        summary.append(
            f"  {row['operating_point']}: threshold={row['threshold']:.2f}, "
            f"precision={row['precision']:.4f}, recall={row['recall']:.4f}, "
            f"specificity={row['specificity']:.4f}, "
            f"FPR={row['false_positive_rate']:.4f}, F1={row['f1']:.4f}"
        )
    summary += [
        "",
        "RISK LEVEL MAPPING",
        f"  LOW: probability < {medium_threshold:.2f}",
        f"  MEDIUM: {medium_threshold:.2f} <= probability < {high_threshold:.2f}",
        f"  HIGH: probability >= {high_threshold:.2f}",
        "  The BALANCED point is retained as a comparison/default single-score",
        "  engineering operating point; persistence governs dashboard alerts.",
        "",
        "PERSISTENCE / WORSENING ALERT POLICY",
        "  LOW now -> NO_ALERT.",
        "  One isolated MEDIUM or HIGH checkpoint -> WATCH.",
        "  Two consecutive MEDIUM-or-higher checkpoints -> HIGH_ALERT.",
        "  This covers persistent elevated risk and worsening MEDIUM -> HIGH.",
        "  A single HIGH spike surrounded by LOW never produces HIGH_ALERT.",
        "  Each state uses only the history available at that checkpoint.",
        "  Supported checkpoints are 6h, 12h, and 24h; this is not continuous",
        "  hourly prediction.",
    ]
    (OUTPUT_DIR / "alert_policy_summary.txt").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )

    print(f"Saved aggregate threshold metrics to {OUTPUT_DIR}")
    print(
        "Risk mapping sanity check:",
        probability_to_risk_level(0.0, medium_threshold, high_threshold),
        probability_to_risk_level(1.0, medium_threshold, high_threshold),
    )
    print("640 held-out patients: NOT EVALUATED")


if __name__ == "__main__":
    main()
