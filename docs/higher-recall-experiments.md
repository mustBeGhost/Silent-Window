# Higher recall at the 12-hour assessment

The question was whether Silent Window could warn on roughly 300–320 of the
354 development patients labelled as dying during their hospital stay.
This experiment shows that lowering the warning threshold can reach that range.
It also shows the extra survivor warnings needed to do so.

## Results

For the calibrated Random Forest, counting WATCH and HIGH_ALERT together at 12h:

- The 70% training target detected 252 of 354 (71.2%), missed 102, and warned on
  798 of 2,200 assessed survivor-labelled patients. There were 1,050 warnings
  among 2,554 assessed patients (41.1%).
- The 85% training target detected 311 (87.9%), missed 43, and warned on 1,225
  survivors. There were 1,536 warnings (60.1% of assessed patients).
- The 90% training target detected 323 (91.2%), missed 31, and warned on 1,353
  survivors. There were 1,676 warnings (65.6% of assessed patients).

Six development patients lacked usable measurements at 12h. None had death
labels. They remain unassessed and are excluded from the confusion counts.

HIGH_ALERT alone detected 215, 296, and 308 death labels, respectively, and
warned on 642, 1,085, and 1,223 survivors. The remaining warned patients were
WATCH. Requiring persistence does not erase those WATCH warnings.

The uncalibrated reference, using the same final forests, detected 252, 307,
and 324 death labels, with 797, 1,202, and 1,374 survivor warnings. Calibration
does not show a consistent improvement in warning performance across targets.
The fixed score grid can select slightly different operating points on the
raw and calibrated score scales.

## What this means for the project

The 85% target is a useful research reference for the next model improvement
stage. Compared with the calibrated 70% setting, it caught 59 extra death
labels and warned on 427 extra survivors. Going from 85% to 90% caught another
12 death labels while warning on another 128 survivors.

The next model goal is to separate cases better: aim to retain detection near
this higher target while reducing survivor warnings. Compare new features and
model families under the same patient separation and timing rules. Lowering
the threshold alone does not improve this separation.

This is a research choice, not a clinical acceptance threshold. Survivor
warnings are false positives against the death label; the data does not prove
that those patients were healthy or did not need attention. The model does not
predict deterioration within the next 6, 12, or 24 hours. These are assessment
times, and exact event timing and clinical checkpoint eligibility remain unknown.

## How we tested it

All three targets were fixed before the run. Each target reused the same models
and patient folds. Five outer validation folds were assigned to the full 2,560
development patients before checking measurement availability. Each patient
had the same outer fold at 6h, 12h, and 24h.

Within each outer training group, three inner folds produced training-only
12h predictions for threshold selection. Calibration was fitted within each
training fit. Thresholds were selected from the fixed 0–1 grid in steps of 0.01,
preferring the lowest survivor false-positive rate that met the training recall
target. The high risk-category floor stayed at 30%; it does not determine
whether repeated warnings become HIGH_ALERT. No outer validation labels were
used for threshold selection. A training target is not a validation guarantee.

The separate 640-patient cohort was not evaluated. Development patients had
been examined in earlier work, so these results are not an untouched final test.
The 70% control reproduced the previous full alert-sequence aggregates exactly.
Source, data, original models, calibrated models, and prior report hashes were
checked. Individual patient predictions were kept in memory only.

## App changes and reproduction

Model Performance now shows three experiment cards, with a comparison selector
for calibrated and uncalibrated models. Cards show detection, misses, survivor
warnings, the share of all assessed patients warned, and separate WATCH and
HIGH_ALERT counts. Historical charts remain clearly identified below them.
The sidebar now reflects the selected model family.

The patient queue still uses its existing model boundaries. The experimental
thresholds are chosen separately inside each validation fold and are not a
deployable global setting. No model bundle or runtime threshold was replaced.

Run from the project folder:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_recall_targets
```

Aggregate evidence: `data/processed/evaluation_v3/recall_target_metrics.json`.
Website summary: `frontend/src/data/recallExperiments.json`.

## Verification

338 Python tests and 25 frontend checks passed. The production frontend build
passed. The running app served the performance page, experiment component,
and results summary successfully. Its model metadata confirmed that the
original and calibrated runtime thresholds remain 0.40/0.55 and 0.12/0.28.
Saved experiment source and protected-file hashes still match.

The first sandboxed full test run could not open Windows worker pipes used by
the existing original models. The same suite passed with worker access allowed;
no model or test was changed to hide that limitation. Five existing Python
warnings and the existing large frontend bundle warning remain. Component
rendering was tested, but the new layout was not visually inspected in a browser.
