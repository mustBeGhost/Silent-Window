# Focused forest and threshold-resolution experiment

The primary assessment is 12 hours after ICU admission. The outcome remains
death during the hospital stay. This experiment does not predict death within
the next 12 hours, and it does not establish clinically valid probabilities.

## Protocol fixed before the run

Five calibrated Random Forest settings were declared in `ml/forest_tuning.py`:

- Current 132 inputs: depth 12, minimum leaf size 10 (earlier control).
- Recent 228 inputs: depth 12, minimum leaf size 10 (earlier recent-input reference).
- Recent inputs: depth 8, minimum leaf size 10.
- Recent inputs: depth 12, minimum leaf size 20.
- Recent inputs: unrestricted depth, minimum leaf size 10.

All use 200 trees, balanced class weights, seed 42, sigmoid calibration with
three training folds and `ensemble=False`. Model and numerical-library workers
are limited to one. Preprocessing and calibration are fitted inside training.

Both threshold grids, steps 0.01 and 0.001 from 0 to 1, reuse identical model
predictions. Medium boundaries minimize survivor false positives subject to
85% recall on inner out-of-fold training predictions. Precision and the higher
threshold break ties. The high boundary must exceed medium and seeks 30%
training recall; an infeasible high target is explicitly recorded. Only medium
warning eligibility is evaluated in this study. Repeated HIGH_ALERT, 6h, and
24h behavior are not retuned.

Five outer patient folds and three inner selection folds use seed 42. Patients
are assigned before checking measurement coverage. The fine grid is the
predeclared model-selection procedure. Within each outer training group, choose
the candidate with the fewest inner survivor warnings meeting 85% recall; more
true positives, higher average precision, then name break ties. Outer validation
labels never select the model, settings, or grid. The selected candidate is also
reported under its coarse-grid threshold to separate grid and model effects.

The research promotion check requires the fine-grid training-selected procedure
to detect no fewer death labels and warn on at least 10% fewer survivors than
the current-input control under **both** grids. This is an engineering choice,
not a clinical safety standard. Fixed candidate rows are descriptive; they are
not grounds to choose a global winner after viewing outer validation results.

The 2,560 development patients are known from earlier experiments; this is
exploratory evidence, not an untouched final test. The separated 640 patients
are excluded. Missing supported readings remain unassessed, not zero risk.
Source, input, cohort, earlier report, and model fingerprints are checked. No
individual predictions are saved. Saved queue models and thresholds are protected.

## Reproduce

From the project root:

```powershell
.venv\Scripts\python.exe -m scripts.evaluate_forest_tuning
```

Aggregate evidence is written to
`data/processed/evaluation_v3/forest_tuning_metrics.json`, and the website gets
an aggregate export at `frontend/src/data/forestTuning.json`.

## Completed results and decision

All 2,560 development patients received exactly one outer validation assignment.
At 12h, 2,554 had usable readings, including all 354 death labels and 2,200
survivor labels. Six patients remained unassessed. Both earlier coarse-grid
controls reproduced their entire metric records exactly.

The following pairs list detected death labels / survivor warnings, first with
the coarse grid and then with the fine grid:

- Current inputs, depth 12 / leaf 10: 311 / 1,225 → 303 / 1,146.
- Recent inputs, depth 12 / leaf 10: 310 / 1,153 → 306 / 1,125.
- Recent inputs, depth 8 / leaf 10: 312 / 1,193 → 304 / 1,130.
- Recent inputs, depth 12 / leaf 20: 312 / 1,213 → 302 / 1,140.
- Recent inputs, unrestricted depth / leaf 10: 306 / 1,146 → 297 / 1,091.

Inner training selected unrestricted depth in two outer groups, depth 12 / leaf
10 in one, and depth 8 / leaf 10 in two. The predeclared selected procedure with
the **fine grid** detected 302 of 354 (85.3%), missed 52, and warned on 1,101
survivors. Compared with the earlier control, that saves 124 survivor warnings
(10.1%) but misses nine additional death labels. Compared with the same-input
fine-grid control, it saves 45 survivor warnings (3.9%) but misses one more.

The same training-selected models with their **coarse** thresholds detected
312 (88.1%), missed 42, and warned on 1,171 survivors. This is a paired descriptive
comparison, not a separately chosen procedure after seeing validation results.
It is a small gain over the earlier control: one more detected and 54 fewer
survivor warnings (4.4%). It does not reach the declared 10% reduction.

ROC-AUC, average precision, and Brier score are identical between grids for each
candidate, as required: no predictions changed. Finer threshold steps reduce
rounding overshoot; they do not improve ranking. Validation detection fell for
every fixed candidate when moving to the finer grid.

The promotion check failed. No saved model or patient-queue threshold was changed.
The website shows both grids, the training-selected result, missing-data counts,
and the limits of this development evidence. Further small changes on these
same patients should not be presented as a major or independently proven gain.

## Next stage

Keep these comparisons as the model research record. Add controlled automatic
replay of historical observations using the existing time-cutoff API, showing
new readings and assessments as their recorded time arrives. This is a demo of
data flow and warning behavior; it does not itself improve model accuracy or
create a live hospital connection. Better evidence for a clinical warning task
requires suitable event-time labels and new validation data.

## Verification

361 Python tests and 27 frontend checks passed. The production frontend build
passed. Source hashes, protected saved-model/report hashes, identical ranking
metrics across grids, cohort exclusion, and exact website export were checked.
The running API still exposes the original and calibrated profiles at their
saved boundaries. The browser displayed all ten candidate/grid rows with the
saved counts; the summary and page layout were visually inspected. At the
observed 1280px viewport the page stayed within the available width.

Five existing Python dependency/fixture warnings and the existing large frontend
bundle warning remain. This stage adds no new deployment or clinical claims.
