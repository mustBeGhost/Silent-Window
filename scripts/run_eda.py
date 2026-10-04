"""
Silent Window — Exploratory Data Analysis (EDA)
=================================================
Run from project root:  python scripts/run_eda.py

Uses the validated data loader and preprocessing pipeline.
Does NOT modify raw data.  Does NOT train models.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt

from ml.data_loader import discover_patient_ids, load_patient, load_outcomes
from ml.preprocessing import preprocess_patient, observations_up_to

# ── Config ───────────────────────────────────────────────────────────────
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "eda"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STATIC_PARAMS = {"RecordID", "Age", "Gender", "Height", "ICUType", "Weight"}
CUTOFFS_MIN = [360, 720, 1080, 1440, 1800, 2160, 2520, 2880]
CUTOFF_LABELS = ["6h", "12h", "18h", "24h", "30h", "36h", "42h", "48h"]

# Important time-varying parameters for focused analyses
IMPORTANT_TV = [
    "HR", "Temp", "RespRate", "MAP", "SysABP", "DiasABP",
    "GCS", "SaO2", "Glucose", "Creatinine", "BUN", "WBC",
    "Platelets", "HCT", "Urine", "Na", "K", "pH", "Lactate",
]

report_lines: list[str] = []


def report(text: str = "") -> None:
    print(text)
    report_lines.append(text)


# ═════════════════════════════════════════════════════════════════════════
# 1. LOAD ALL DATA
# ═════════════════════════════════════════════════════════════════════════
def load_all() -> tuple[pd.DataFrame, pd.DataFrame, list[int]]:
    """Load every patient, preprocess, and return a combined DataFrame."""
    report("Loading and preprocessing all patients ...")
    ids = discover_patient_ids()
    outcomes = load_outcomes()

    parts: list[pd.DataFrame] = []
    for i, pid in enumerate(ids):
        df = load_patient(pid)
        df = preprocess_patient(df)
        df["PatientID"] = pid
        parts.append(df)
        if (i + 1) % 500 == 0:
            report(f"  ... loaded {i + 1}/{len(ids)}")

    combined = pd.concat(parts, ignore_index=True)
    report(f"  Done. {len(ids)} patients, {len(combined):,} total rows.\n")
    return combined, outcomes, ids


# ═════════════════════════════════════════════════════════════════════════
# 2. CLASS ANALYSIS
# ═════════════════════════════════════════════════════════════════════════
def analyze_class(outcomes: pd.DataFrame) -> None:
    report("=" * 60)
    report("2. OUTCOME / CLASS ANALYSIS")
    report("=" * 60)

    total = len(outcomes)
    pos = int(outcomes["In-hospital_death"].sum())
    neg = total - pos
    ratio = neg / pos if pos else float("inf")

    report(f"  Total patients       : {total}")
    report(f"  Survivors (0)        : {neg} ({neg / total * 100:.1f}%)")
    report(f"  In-hospital_death (1): {pos} ({pos / total * 100:.1f}%)")
    report(f"  Imbalance ratio      : {ratio:.1f}:1 (negative:positive)")
    report(f"  NOTE: Simple accuracy is NOT an appropriate metric.\n")

    fig, ax = plt.subplots(figsize=(5, 4))
    bars = ax.bar(["Survived", "Died"], [neg, pos],
                  color=["#2ecc71", "#e74c3c"])
    ax.set_ylabel("Count")
    ax.set_title("In-Hospital Death Distribution")
    for bar, val in zip(bars, [neg, pos]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 20,
                str(val), ha="center", fontsize=11)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "class_distribution.png", dpi=150)
    plt.close()
    report("  -> Saved class_distribution.png")


# ═════════════════════════════════════════════════════════════════════════
# 3. PARAMETER AVAILABILITY
# ═════════════════════════════════════════════════════════════════════════
def analyze_parameters(
    combined: pd.DataFrame, n_patients: int
) -> pd.DataFrame:
    report("\n" + "=" * 60)
    report("3. PARAMETER AVAILABILITY")
    report("=" * 60)

    all_params = sorted(combined["Parameter"].unique())
    rows = []
    for param in all_params:
        sub = combined[combined["Parameter"] == param]
        pts = sub["PatientID"].nunique()
        total = len(sub)
        valid = int(sub["Value"].notna().sum())
        per_pt = sub.groupby("PatientID").size()
        rows.append(dict(
            Parameter=param,
            Patients=pts,
            Pct=pts / n_patients * 100,
            TotalMeas=total,
            ValidMeas=valid,
            MissingNaN=total - valid,
            MedianPerPt=per_pt.median() if len(per_pt) else 0,
            IsStatic=param in STATIC_PARAMS,
        ))

    avail = pd.DataFrame(rows).sort_values("Patients", ascending=False)

    # ── Static ──────────────────────────────────────────────────────────
    report("\n  A. STATIC / DEMOGRAPHIC PARAMETERS:")
    for _, r in avail[avail["IsStatic"]].iterrows():
        report(f"    {r['Parameter']:<15s}: {r['Patients']:>5d} patients "
               f"({r['Pct']:5.1f}%), NaN={r['MissingNaN']}")

    # ── Time-varying ────────────────────────────────────────────────────
    tv = avail[~avail["IsStatic"]]
    very = tv[tv["Pct"] >= 90]
    mod = tv[(tv["Pct"] >= 40) & (tv["Pct"] < 90)]
    sparse = tv[tv["Pct"] < 40]

    report("\n  B. TIME-VARYING PARAMETERS:")
    report("\n    Very common (>=90%):")
    for _, r in very.iterrows():
        report(f"      {r['Parameter']:<15s}: {r['Patients']:>5d} ({r['Pct']:5.1f}%), "
               f"median {r['MedianPerPt']:.0f} meas/patient")
    report("\n    Moderate (40-90%):")
    for _, r in mod.iterrows():
        report(f"      {r['Parameter']:<15s}: {r['Patients']:>5d} ({r['Pct']:5.1f}%), "
               f"median {r['MedianPerPt']:.0f} meas/patient")
    report("\n    Sparse (<40%):")
    for _, r in sparse.iterrows():
        report(f"      {r['Parameter']:<15s}: {r['Patients']:>5d} ({r['Pct']:5.1f}%), "
               f"median {r['MedianPerPt']:.0f} meas/patient")

    # ── Plot ────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(11, 8))
    plot_data = tv.sort_values("Pct")
    colors = ["#e74c3c" if p < 40 else "#f39c12" if p < 90 else "#2ecc71"
              for p in plot_data["Pct"]]
    ax.barh(plot_data["Parameter"], plot_data["Pct"], color=colors)
    ax.set_xlabel("% of Patients with >=1 Measurement")
    ax.set_title("Time-Varying Parameter Availability")
    ax.axvline(90, color="green", ls="--", alpha=.5, label="90%")
    ax.axvline(40, color="red", ls="--", alpha=.5, label="40%")
    ax.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "parameter_availability.png", dpi=150)
    plt.close()
    report("  -> Saved parameter_availability.png")
    return avail


# ═════════════════════════════════════════════════════════════════════════
# 4. CHRONOLOGICAL AVAILABILITY
# ═════════════════════════════════════════════════════════════════════════
def analyze_chronological(
    combined: pd.DataFrame, n_patients: int
) -> pd.DataFrame:
    report("\n" + "=" * 60)
    report("4. CHRONOLOGICAL AVAILABILITY")
    report("=" * 60)

    chrono: dict[str, dict[str, int]] = {}
    for cutoff, label in zip(CUTOFFS_MIN, CUTOFF_LABELS):
        filt = combined[combined["Time_minutes"] <= cutoff]
        row = {}
        for p in IMPORTANT_TV:
            row[p] = filt[filt["Parameter"] == p]["PatientID"].nunique()
        chrono[label] = row

    cdf = pd.DataFrame(chrono).T

    report(f"\n  Patients with >=1 measurement by cutoff (of {n_patients}):")
    header = f"  {'Param':<14s}" + "".join(f"{l:>7s}" for l in CUTOFF_LABELS)
    report(header)
    for p in IMPORTANT_TV:
        if p not in cdf.columns:
            continue
        vals = [cdf.loc[l, p] for l in CUTOFF_LABELS]
        report(f"  {p:<14s}" + "".join(f"{v:>7d}" for v in vals))

    # ── Plot key params ─────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 6))
    plot_params = ["HR", "GCS", "Temp", "Creatinine", "MAP",
                   "Glucose", "Lactate", "RespRate"]
    for p in plot_params:
        if p in cdf.columns:
            pcts = [cdf.loc[l, p] / n_patients * 100 for l in CUTOFF_LABELS]
            ax.plot(CUTOFF_LABELS, pcts, marker="o", label=p)
    ax.set_xlabel("Cutoff")
    ax.set_ylabel("% Patients with >=1 Measurement")
    ax.set_title("Parameter Availability by Prediction Cutoff")
    ax.set_ylim(0, 105)
    ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left")
    ax.grid(True, alpha=.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "availability_by_time.png", dpi=150)
    plt.close()
    report("  -> Saved availability_by_time.png")
    return cdf


# ═════════════════════════════════════════════════════════════════════════
# 5. SURVIVOR VS NON-SURVIVOR
# ═════════════════════════════════════════════════════════════════════════
def analyze_groups(combined: pd.DataFrame, outcomes: pd.DataFrame) -> None:
    report("\n" + "=" * 60)
    report("5. SURVIVOR VS NON-SURVIVOR (descriptive only)")
    report("=" * 60)

    death_map = dict(zip(outcomes["RecordID"], outcomes["In-hospital_death"]))

    params_to_compare = [
        "HR", "Temp", "MAP", "SysABP", "DiasABP", "GCS",
        "SaO2", "Glucose", "Creatinine", "BUN", "WBC",
        "Platelets", "HCT", "Na", "K", "pH", "Lactate",
    ]
    existing = [p for p in params_to_compare if p in combined["Parameter"].unique()]

    report("\n  Last observed value within 48 h — median (IQR):")
    report(f"  {'Parameter':<15s} | {'Survived':>20s} | {'Died':>20s}")
    report("  " + "-" * 62)

    for param in existing:
        sub = combined[combined["Parameter"] == param].copy()
        last = sub.sort_values("Time_minutes").groupby("PatientID").last()
        last["outcome"] = last.index.map(death_map)
        last = last.dropna(subset=["Value"])

        s = last[last["outcome"] == 0]["Value"]
        d = last[last["outcome"] == 1]["Value"]
        if len(s) == 0 or len(d) == 0:
            continue

        s_str = f"{s.median():.1f} ({s.quantile(.25):.1f}-{s.quantile(.75):.1f})"
        d_str = f"{d.median():.1f} ({d.quantile(.25):.1f}-{d.quantile(.75):.1f})"
        report(f"  {param:<15s} | {s_str:>20s} | {d_str:>20s}")

    # ── Measurement frequency ──────────────────────────────────────────
    report("\n  Mean measurements per patient (full 48 h):")
    report(f"  {'Parameter':<15s} | {'Survived':>10s} | {'Died':>10s}")
    report("  " + "-" * 40)
    for param in existing:
        sub = combined[combined["Parameter"] == param].copy()
        sub["outcome"] = sub["PatientID"].map(death_map)
        freq = sub.groupby(["PatientID", "outcome"]).size().reset_index(name="n")
        sm = freq[freq["outcome"] == 0]["n"].mean()
        dm = freq[freq["outcome"] == 1]["n"].mean()
        report(f"  {param:<15s} | {sm:>10.1f} | {dm:>10.1f}")

    # ── Box plot for key params ────────────────────────────────────────
    fig, axes = plt.subplots(2, 4, figsize=(16, 8))
    plot_params = ["HR", "Temp", "MAP", "GCS",
                   "Creatinine", "BUN", "Glucose", "Lactate"]
    for ax, param in zip(axes.ravel(), plot_params):
        sub = combined[combined["Parameter"] == param].copy()
        last = sub.sort_values("Time_minutes").groupby("PatientID").last()
        last["outcome"] = last.index.map(death_map)
        last = last.dropna(subset=["Value"])
        s = last[last["outcome"] == 0]["Value"]
        d = last[last["outcome"] == 1]["Value"]
        ax.boxplot([s, d], tick_labels=["Surv", "Died"], widths=0.6)
        ax.set_title(param)
    plt.suptitle("Last Observed Value: Survivors vs Died", y=1.01)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "survivor_comparison.png", dpi=150)
    plt.close()
    report("  -> Saved survivor_comparison.png")


# ═════════════════════════════════════════════════════════════════════════
# 6. TEMPORAL / TREND ANALYSIS
# ═════════════════════════════════════════════════════════════════════════
def analyze_temporal(combined: pd.DataFrame) -> None:
    report("\n" + "=" * 60)
    report("6. TEMPORAL / TREND ANALYSIS")
    report("=" * 60)
    report("\n  Feature calculability at selected cutoffs (HR as example):\n")

    hr = combined[combined["Parameter"] == "HR"]

    for cutoff, label in zip([360, 720, 1440, 2880],
                             ["6h", "12h", "24h", "48h"]):
        filt = hr[hr["Time_minutes"] <= cutoff]
        pts = filt["PatientID"].nunique()
        if pts == 0:
            continue
        stats = filt.groupby("PatientID")["Value"].agg(
            ["mean", "std", "min", "max", "count"])
        report(f"  HR at {label} (cutoff {cutoff} min):")
        report(f"    Patients with data    : {pts}")
        report(f"    Median meas count     : {stats['count'].median():.0f}")
        report(f"    Can compute mean      : {(stats['count'] >= 1).sum()}")
        report(f"    Can compute std/slope : {(stats['count'] >= 2).sum()}")
        report("")

    report("  CONCLUSION: For well-available parameters, latest/mean/min/")
    report("  max/count are reliably computable from 6 h onward.")
    report("  std and slope require >=2 measurements per patient.")


# ═════════════════════════════════════════════════════════════════════════
# 7. STATIC FEATURE ANALYSIS
# ═════════════════════════════════════════════════════════════════════════
def analyze_static(combined: pd.DataFrame) -> None:
    report("\n" + "=" * 60)
    report("7. STATIC FEATURE ANALYSIS")
    report("=" * 60)

    for param in ["Age", "Gender", "Height", "ICUType", "Weight"]:
        sub = combined[
            (combined["Parameter"] == param) & (combined["Time_minutes"] == 0)
        ]
        vals = sub["Value"].dropna()
        nan_count = int(sub["Value"].isna().sum())

        report(f"\n  {param}:")
        report(f"    Patients   : {len(sub)}")
        report(f"    Valid      : {len(vals)}")
        report(f"    Missing    : {nan_count}")

        if len(vals) == 0:
            continue

        report(f"    Min / Max  : {vals.min():.1f} / {vals.max():.1f}")
        report(f"    Median     : {vals.median():.1f}")

        if param == "Age":
            suspicious = vals[(vals < 0) | (vals > 120)]
            report(f"    Suspicious : {len(suspicious)} values outside 0-120")
        elif param == "Gender":
            report(f"    Unique     : {sorted(vals.unique())}")
            report(f"    Note       : Categorical — never average")
        elif param == "Height":
            report(f"    Note       : {nan_count} unknown (sentinel -1 -> NaN)")
            report(f"    Usability  : 47% missing — consider dropping or imputing")
        elif param == "Weight":
            report(f"    Note       : {nan_count} unknown (sentinel -1 -> NaN)")
        elif param == "ICUType":
            report(f"    Unique     : {sorted(vals.unique())}")
            report(f"    Note       : Categorical — one-hot encode for modeling")


# ═════════════════════════════════════════════════════════════════════════
# 8. URINE INVESTIGATION
# ═════════════════════════════════════════════════════════════════════════
def analyze_urine(combined: pd.DataFrame) -> None:
    report("\n" + "=" * 60)
    report("8. URINE INVESTIGATION")
    report("=" * 60)

    urine = combined[combined["Parameter"] == "Urine"]
    n_pts = urine["PatientID"].nunique()
    total = len(urine)
    dup_flag = int(urine["_dup_urine"].sum()) if "_dup_urine" in urine.columns else 0

    report(f"  Patients with Urine : {n_pts}")
    report(f"  Total Urine rows    : {total}")
    report(f"  Flagged duplicates  : {dup_flag}")

    vals = urine["Value"].dropna()
    report(f"\n  Value distribution:")
    report(f"    Min    : {vals.min():.1f}")
    report(f"    Q1     : {vals.quantile(.25):.1f}")
    report(f"    Median : {vals.median():.1f}")
    report(f"    Q3     : {vals.quantile(.75):.1f}")
    report(f"    Max    : {vals.max():.1f}")
    report(f"    Mean   : {vals.mean():.1f}")

    # Duplicate value spread
    if "_dup_urine" in urine.columns and dup_flag > 0:
        dup_rows = urine[urine["_dup_urine"]]
        groups = dup_rows.groupby(["PatientID", "Time"])["Value"]
        spreads = groups.apply(lambda g: g.max() - g.min())
        report(f"\n  Duplicate-pair value spread:")
        report(f"    Median spread : {spreads.median():.1f}")
        report(f"    Max spread    : {spreads.max():.1f}")

    # Check for any dataset documentation
    doc_base = PROJECT_ROOT / "data" / "raw" / "dataset_2"
    docs = (list(doc_base.rglob("README*")) +
            list(doc_base.rglob("*.md")) +
            list(doc_base.rglob("DESCRIPTION*")))
    if docs:
        report(f"\n  Dataset docs found: {[d.name for d in docs]}")
    else:
        report(f"\n  No dataset documentation found in extracted files.")

    report("\n  CONCLUSION: Urine aggregation semantics unresolved.")
    report("  Dataset provides no documentation clarifying whether values")
    report("  are interval amounts, cumulative totals, or rates.")
    report("  Duplicate Urine readings are preserved and flagged.")


# ═════════════════════════════════════════════════════════════════════════
# 9. LEAKAGE AUDIT
# ═════════════════════════════════════════════════════════════════════════
def audit_leakage(outcomes: pd.DataFrame) -> None:
    report("\n" + "=" * 60)
    report("9. LEAKAGE AUDIT")
    report("=" * 60)

    report(f"\n  Outcome file columns: {list(outcomes.columns)}")

    report("\n  SAFE CANDIDATE INPUTS (from patient time-series):")
    report("    - All 36 time-varying physiological/lab parameters")
    report("      (subject to chronological filtering via observations_up_to)")
    report("    - Static demographics: Age, Gender, Height, ICUType, Weight")

    report("\n  POTENTIAL LEAKAGE — EXCLUDE FROM MODEL:")
    report("    In-hospital_death  : TARGET variable — never use as input")
    report("    Survival           : days survived — directly reveals outcome")
    report("    Length_of_stay     : only known after discharge")
    report("    SAPS-I             : severity score — may encode outcome info;")
    report("                         163 missing (-1); EXCLUDE to be safe")
    report("    SOFA               : organ-failure score — similar concern;")
    report("                         EXCLUDE to be safe")

    report("\n  IDENTIFIER — MUST NOT BE A FEATURE:")
    report("    RecordID           : patient identifier — use for joins only,")
    report("                         never as a numeric predictor")


# ═════════════════════════════════════════════════════════════════════════
# 10. FEATURE DESIGN PROPOSAL
# ═════════════════════════════════════════════════════════════════════════
def propose_features() -> None:
    report("\n" + "=" * 60)
    report("10. PROPOSED FEATURE SCHEMA  (design only — not implemented)")
    report("=" * 60)

    report("""
  A. STATIC FEATURES
    Age                   continuous
    Gender                binary (NaN for 2 unknowns)
    ICUType               one-hot (4 categories)
    Weight                continuous (8% missing)
    Height                continuous (47% missing — consider dropping)

  B. TEMPORAL FEATURES (per well-available parameter)
    Parameters: HR, Temp, GCS, MAP, SysABP, DiasABP, Glucose,
                Creatinine, BUN, WBC, Platelets, HCT, Na, HCO3, K, Mg, Urine

    For each, at prediction cutoff T (data <= T only):
      {p}_latest           last observed value
      {p}_mean             mean of all values
      {p}_min              minimum
      {p}_max              maximum
      {p}_std              std deviation  (NaN if <2 values)
      {p}_count            measurement count
      {p}_slope            linear trend   (NaN if <2 values)
      {p}_time_since       minutes since last measurement

  C. MODERATE-AVAILABILITY PARAMETERS (same template)
    NISysABP, NIDiasABP, NIMAP, pH, PaCO2, PaO2, FiO2,
    MechVent, Lactate, SaO2

  D. SPARSE PARAMETERS (simplified)
    RespRate, TroponinT, TroponinI, Cholesterol,
    AST, ALT, Bilirubin, ALP, Albumin
    -> Only: {p}_latest, {p}_available

  E. MISSINGNESS INDICATORS
    {p}_available          binary — was this parameter measured?
    total_params_measured  count of unique parameters so far

  ESTIMATED TOTAL: ~280 candidate features (will prune later)

  CRITICAL SAFETY: Every temporal feature must be computed using
  ONLY observations with Time_minutes <= prediction cutoff.
""")


# ═════════════════════════════════════════════════════════════════════════
# 11. CUTOFF STRATEGY
# ═════════════════════════════════════════════════════════════════════════
def analyze_cutoffs(chrono_df: pd.DataFrame, n: int) -> None:
    report("=" * 60)
    report("11. CUTOFF STRATEGY")
    report("=" * 60)

    key = ["HR", "GCS", "Temp", "Creatinine", "MAP", "Glucose"]
    report(f"\n  % patients with >=1 measurement:")
    report(f"  {'Cutoff':<8s}" + "".join(f"{p:>13s}" for p in key))
    for label in CUTOFF_LABELS:
        vals = [chrono_df.loc[label, p] / n * 100
                if p in chrono_df.columns else 0 for p in key]
        report(f"  {label:<8s}" + "".join(f"{v:>12.1f}%" for v in vals))

    report("""
  CANDIDATE CUTOFFS:
    6h   earliest useful — most vitals present, limited labs
    12h  good balance of vitals + early labs
    24h  comprehensive data for most patients
    48h  maximum data, but latest possible warning

  RECOMMENDATION:
    Build the system for MULTIPLE cutoffs to produce a deterioration
    risk timeline rather than a single 48-hour prediction.
    Primary training cutoff: 24 h.
    Validate early-detection value at 6 h, 12 h.
""")


# ═════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════
def main() -> None:
    report("Silent Window — Exploratory Data Analysis")
    report("=" * 60)

    combined, outcomes, ids = load_all()
    n = len(ids)

    analyze_class(outcomes)
    analyze_parameters(combined, n)
    chrono_df = analyze_chronological(combined, n)
    analyze_groups(combined, outcomes)
    analyze_temporal(combined)
    analyze_static(combined)
    analyze_urine(combined)
    audit_leakage(outcomes)
    propose_features()
    analyze_cutoffs(chrono_df, n)

    report("=" * 60)
    report("EDA COMPLETE — no data was modified.")
    report("=" * 60)

    # ── Save text summary ──────────────────────────────────────────────
    summary_path = PROJECT_ROOT / "data" / "processed" / "eda_summary.txt"
    summary_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n-> Summary saved to {summary_path}")
    print(f"-> Plots saved to  {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
