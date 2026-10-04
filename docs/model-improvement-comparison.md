# Model and recent-input comparison

This stage asks whether a different model or a better description of recent
measurements can retain high death-label detection with fewer survivor warnings.
The comparison target is 85% training recall at the 12-hour assessment.

## Changes to the inputs

The current inputs already contain overall slopes, averages, latest readings,
minimum/maximum readings, counts, and the age of the latest measurement.
The research input set keeps those 132 inputs and adds six inputs for each of
the 16 supported measurement types, for a total of 228:

- Change from the first reading to the latest reading, when at least two exist.
- Mean measurement during the most recent four hours.
- Number of readings during those four hours.
- Slope during those four hours, when timestamps allow it.
- Difference between the recent mean and the earlier recorded mean.
- Whether that measurement type is absent from the entire assessment prefix.

The recent window includes times greater than `checkpoint - 240 minutes` and
up to the checkpoint. A reading exactly at the lower boundary belongs to the
earlier window. Missing means, changes, and slopes stay missing. There is no
future filling or assumption that an old reading is a current reading.

The original feature generators and saved model files are preserved. The new
inputs are in a separate research module. Observation coverage stays identical
between feature sets, so different candidates cannot improve their numbers by
quietly scoring a different patient group.

## Fixed candidates

Six candidates were declared before the run:

- Current Random Forest with current inputs, as a reproducibility control.
- The same Random Forest with recent inputs.
- Extra Trees with recent inputs.
- Histogram gradient boosting with current inputs.
- Histogram gradient boosting with recent inputs.
- Logistic Regression with recent inputs.

All use sigmoid calibration fitted inside training only. Random Forest keeps
its existing 200 trees, maximum depth 12, and minimum leaf size 10. Extra Trees
uses 300 trees and minimum leaf size 5. Gradient boosting uses 200 iterations,
15 maximum leaf nodes, learning rate 0.05, minimum leaf size 20, L2 penalty 1,
and no early stopping. Class weighting is balanced for all candidates. These
are fixed comparisons, not a parameter search using validation outcomes.

The installed gradient-boosting library failed on completely empty training
columns. A preprocessing step learns which numeric columns have at least one
recorded training value and drops the empty ones. This happens inside every
fit. Partly missing columns retain their missing values. Validation readings
cannot change which columns were retained.

## Evaluation and model choice

Five outer patient folds are assigned before checking measurement availability,
with the same fold at every checkpoint. Three inner folds produce 12h training
predictions for each candidate. Each of these fits contains its own three-fold
calibration. Imputation and categorical encoding stay inside each training fit.

Thresholds use the earlier fixed grid and selection rule. The medium boundary
aims for at least 85% training detection, preferring fewer survivor warnings.
The high category boundary keeps the existing 30% training recall floor.
These boundaries are not clinical acceptance criteria.

The model-selection procedure chooses the candidate with the fewest inner
survivor warnings while meeting the recall goal. More detected death labels,
then greater average precision, then candidate name break ties. Outer validation
outcomes do not choose the family, input set, threshold, or model settings.
Each training group's chosen family is also fitted at 6h and 24h to evaluate
the full warning sequence. Different training groups may choose different
families; this procedure's result must not be presented as a validation score
for one family chosen after looking at all outer results.

The predeclared research promotion check requires at least as many detected
death labels as the 85% Random Forest control and at least 10% fewer survivor
warnings. This is an engineering check for this stage, not a medical standard.
Passing it alone would not establish clinical readiness.

The separate 640-patient cohort is excluded. The development data were examined
in earlier stages, so this is exploratory evidence, not an untouched final test.
Survivor warnings are false positives for the death label; their real clinical
need is unknown. Counts and missingness can reflect hospital practices, which
may limit transfer to other hospitals. Exact event timing and alive-and-in-ICU
eligibility at each checkpoint remain unknown.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_model_improvements
```

Aggregate evidence: `data/processed/evaluation_v3/model_improvement_metrics.json`.
Website summary: `frontend/src/data/modelImprovements.json`.
Individual patient scores are kept in memory only. Source, input data, prior
reports, and saved model files are fingerprinted and checked again after the run.

## Results and decision

At 12h, counting any warning (WATCH or HIGH_ALERT), all candidates assessed the
same 2,554 development patients, including 354 death labels and 2,200 survivor
labels. Six patients remained unassessed and none had death labels.

- Calibrated Random Forest control: 311 detected, 43 missed, 1,225 survivors
  warned. ROC-AUC 0.7471. Its warning counts reproduced the earlier 85% run.
- Random Forest with recent inputs: 310 detected, 44 missed, 1,153 survivors
  warned. ROC-AUC 0.7503.
- Extra Trees with recent inputs: 311 detected, 43 missed, 1,176 survivors
  warned. ROC-AUC 0.7534.
- Gradient boosting with current inputs: 305 detected, 49 missed, 1,304
  survivors warned. ROC-AUC 0.7204.
- Gradient boosting with recent inputs: 311 detected, 43 missed, 1,319
  survivors warned. ROC-AUC 0.7291.
- Logistic Regression with recent inputs: 324 detected, 30 missed, 1,804
  survivors warned. ROC-AUC 0.6673. Its higher detection came with much more
  warning burden; it did not separate cases better.

The training-only selection procedure chose Random Forest with recent inputs
in all five outer training groups. Its separate validation result therefore
matched that candidate: 310 detected (87.6%), 44 missed, and 1,153 survivor
warnings. Compared with the control, this reduced survivor warnings by 72
(5.9%) while missing one more death label. Extra Trees reduced warnings by 49
(4.0%) with the same detected count, but it was not chosen by the training-only
selection procedure. That observed comparison is exploratory, not evidence
that selecting Extra Trees after seeing validation results will generalize.

The predeclared promotion check did not pass. No candidate achieved at least
10% fewer survivor warnings with no fewer death labels detected than the
control. There is a modest signal that recent inputs help, but no large or
established improvement. No model bundle or patient-queue threshold changed.

The website shows the full comparison, measured recall rather than just the
training target, and a separate explanation of training-only model choice.
Navigation links now retain accessible names when their text is hidden on a
narrow screen.

## Next research step

Use the recent-input Random Forest as a working research reference. Before a
larger search, test a small, declared set of regularization settings and a finer
training-only threshold grid to separate model ranking gains from score-grid
rounding. Compare recent-input candidates with the existing control under the
same protocol. Keep detection and survivor warnings together, and report any
lost detection. Do not declare a clinical threshold or choose a family solely
because it looked best on these already examined validation results.

A real deployment claim will need new external data and a suitable clinical
validation design. The present outcome remains death during the hospital stay,
not a time-labelled deterioration event.

## Verification

354 Python tests and 26 frontend checks passed. The production frontend build
passed. The running website served the new page module and aggregate data, and
the browser displayed the exact report counts. The narrow-screen layout was
inspected: the page stayed within the viewport and the wide comparison table
scrolls inside its own area. Its caption and scrolling guidance remain readable.

Source/data fingerprints and protected model/report hashes matched after the
experiment, and the saved control reproduced the previous counts. Five existing
Python warnings and the existing large frontend bundle warning remain.
