# Separate-patient evaluation and missed-case review

This evaluates the saved policies on 4,000 PhysioNet 2012 Set B records. No record ID
overlaps the project's 3,200 local records. Set B has 568 in-hospital-death labels.
The original models, calibration, feature construction, missing-data guard and alert
thresholds were frozen. No model was fitted, retuned or promoted using this cohort.
Saved artifact hashes were checked before and after evaluation.

## Results at 12 hours

3,977 patients were scoreable, including 566 death-labelled patients. Twenty-three
patients were not scored, including two with death labels. These unscored cases are
shown separately and are included in the all-death-label detection denominator.

- Original Random Forest: any warning detected 432 of 566 scored death labels
  (76.3%), missed 134, and warned on 1,216 scored survivors. Across all 568 death
  labels, detection was 76.1%. High alert alone detected 378 and alerted 994 survivors.
- Calibrated candidate: any warning detected 455 of 566 (80.4%), missed 111, and warned
  on 1,316 scored survivors. Across all death labels, detection was 80.1%. High alert
  alone detected 394 and alerted 1,080 survivors.
- Five-checkpoint candidate: any warning detected 524 of 566 (92.6%), missed 42, and
  warned on 1,990 scored survivors (58.3% of scored survivors). Across all death
  labels, detection was 92.3%. High alert alone detected 499 and alerted 1,781 survivors.

Any warning means WATCH or HIGH ALERT at this checkpoint, not whether a warning ever
occurred earlier. High alert requires persistence across the profile's supported
checkpoints. The calibrated and expanded policies share some checkpoint models;
different thresholds and assessment sequences can change warning counts without
making the underlying 12-hour model more accurate. The higher-detection policy has
a substantial survivor-warning burden. No default selection was changed.

The aggregate report also contains ROC-AUC, average precision, Brier scores and
predetermined descriptive groups by ICU type, age and observation count at every
supported checkpoint. These groups help locate missed cases, not explain their
causes. They overlap and may be small; they are not clinical or fairness conclusions.
No patient identifiers or individual prediction rows were saved.

## Reproduction

Run python -m scripts.evaluate_separate_patients --download. The default public
source files are cached inside ignored .release-check/physionet-2012-set-b. The report
is data/processed/evaluation_v3/separate_patient_metrics.json; the website uses an
aggregate copy in frontend/src/data/separatePatients.json. The command refuses to
overwrite an existing report. Use a new explicit --output path for an intentional
repeat. --website-summary can write an explicitly requested new summary file.

For another labelled cohort, supply both --archive and --outcomes plus
--source-description, and identify the source URL/license when known. The loader
requires exact matching observation/outcome membership, complete binary death labels,
unique IDs and no overlap with existing local patients. It reads validated CSV files
from a ZIP without extracting arbitrary paths. It never accepts externally supplied
model/pickle files. Different datasets require proper clinical/feature mapping before
this tool's input format can be considered scientifically compatible.

## Source and limits

Source: https://physionet.org/content/challenge-2012/1.0.0/
Observations: https://physionet.org/files/challenge-2012/1.0.0/set-b.zip
Released labels: https://physionet.org/files/challenge-2012/1.0.0/Outcomes-b.txt
License: Open Data Commons Attribution License v1.0.
Citation: Silva I, Moody G, Scott DJ, Celi LA, Mark RG. Predicting In-Hospital Mortality
of Patients in ICU: The PhysioNet/Computing in Cardiology Challenge 2012. Computing
in Cardiology 2012;39:245-248.

The introduction describes labels as withheld during the original challenge; the
current file listing provides released outcomes. The archive/outcome SHA-256 hashes
and evaluation source hashes are saved in the aggregate report. Downloads are not
included in the normal website package and are not needed to run it.

This is patient-disjoint testing from the same dataset source, not independent-
hospital, prospective or live validation. Exact ICU discharge/death timestamps do
not establish checkpoint eligibility. Scores are not verified individual clinical
probabilities. Set B has now been examined; future model selection must not call it
untouched. Further claims need a suitable new cohort and a prespecified evaluation.
