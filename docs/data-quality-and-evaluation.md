# Data quality and development evaluation

This work supports the current hospital-death research task. It does not establish
that Silent Window can predict a deterioration event or safely monitor live patients.

## Coverage audit

Run `python -m scripts.audit_checkpoint_coverage` from the project folder.

The command reads all 3,200 patient records, measures only the information available
by each checkpoint, and writes an aggregate report to
`data/processed/data_quality/coverage_summary.json`. The reproducible detailed CSV
is ignored by Git. It contains coverage measurements for traceability, not model
predictions, and is never exposed through the patient API.

Coverage is reported separately for development patients and the previously
examined development holdout. Holdout coverage is descriptive data-quality
reporting; it is not a performance check or input to model selection.

The current minimum guard requires one usable model-supported vital or lab
observation. In the 2,560-patient development population:

- 6 hours: 2,506 can be scored; 54 have no usable supported measurements.
- 12 hours: 2,554 can be scored; 6 have no usable supported measurements.
- 24 hours: 2,559 can be scored; 1 has no usable supported measurements.

Seven of the 54 unscored 6-hour patients have a death label. They remain visible
in the coverage accounting; they are not quietly treated as successful negative
predictions. Reported recall applies to the scored population, not automatically
to the full cohort.

The guard must be applied to training and validation rows in the new evaluation,
not just to website inference. Otherwise the reported metrics would describe a
different assessment policy from the application.

The audit also separates bedside measurements from labs. At 12 hours, 56
development patients have no recorded supported bedside measurement; 9 have
bedside readings whose newest value is more than 6 hours old. These counts do
not imply that a reading must occur every 6 hours. That age bin is descriptive,
not a medical freshness rule. Labs and bedside observations have different
recording schedules. Do not invent clinical exclusion rules from these counts.

## What we can and cannot establish about checkpoint eligibility

The official dataset defines length of stay as time from ICU admission to the
end of **hospitalization**, including time after leaving the ICU. Survival is also
reported in days. These fields do not supply exact ICU discharge or death times.
[PhysioNet dataset documentation](https://physionet.org/content/challenge-2012/1.0.0/)

The local outcome file needs clarification:

- 53 records have an unknown hospital stay, stored as -1.
- 1 record has a hospital stay of 1 day.
- 23 records labelled in-hospital death have Survival equal to 1 day.
- 1 survivor-labelled record has a recorded survival shorter than its known
  hospital stay.

These flags overlap and are diagnostics, not replacements for the supplied
target label. The official challenge description says records were selected
for at least 48 hours in the ICU and excludes Survival values of 0 or 1. The
local day-level values do not match those stated constraints. We cannot assume
an exact cause for the discrepancy or convert a day value into a known event
minute.

All 3,200 local outcome rows have now been compared with the public
[PhysioNet outcome file](https://physionet.org/files/challenge-2012/1.0.0/Outcomes-a.txt).
Every local row matches, including the timing values flagged above. This confirms
the local outcomes are an unchanged subset of that public file; it does not
prove exact checkpoint eligibility or verify the observation files. The source
file has 4,000 rows, while the local dataset has 3,200. Additional source records
must not be called an untouched final test without checking prior exposure and
fixing a separate evaluation plan first.

Run `python -m scripts.verify_outcomes_source` to repeat the comparison. It needs
internet access, writes `data/processed/data_quality/outcome_source_verification.json`,
and never replaces local data. The report records hashes for both files.

No patient is silently removed based on these outcome flags. Outcome timing is
never a feature or runtime availability check. Using an observation after a
checkpoint to decide whether to score that earlier checkpoint would also use
future information, so recording extent is kept as an audit-only diagnostic.

For now, results describe retrospective, observation-scoreable patients. We
cannot claim a confirmed population of patients alive and still in the ICU at
each checkpoint. A proper live early-warning benchmark needs that timing data.

## Fresh development comparison

Run `python -m scripts.evaluate_scoreable_models` from the project folder.
It can take several minutes because it fits models within cross-validation.

The command uses only the frozen development cohort and compares fixed candidates:

- A prevalence baseline: predicts the death rate learned from the training fold.
- The existing balanced Logistic Regression setup.
- The existing balanced Random Forest setup.
- The same Random Forest with sigmoid calibration.

All candidates use the same scoreable patients and outer folds at a given
checkpoint. Each patient is scored by a model that did not train on that patient.
Imputation and scaling are fitted within each training fold. Calibration uses
three further folds inside the outer training data, keeping outer validation
patients out of the entire fitting process.

Calibration adjusts the mapping from model output to probability. It should be
checked with reliability bins as well as prediction losses. A lower Brier score
alone does not prove better calibration, because Brier loss also reflects
discrimination. [scikit-learn calibration documentation](https://scikit-learn.org/stable/modules/calibration.html)

The report includes ROC-AUC, average precision, Brier loss, log loss, reliability
bins, mean score versus observed outcome rate, and missed cases/false alarms at
the fixed historical thresholds 0.40, 0.50, and 0.55. Those thresholds are reference
points, not freshly selected settings for a calibrated model.

Different checkpoints have different scoreable patient populations. Their
performance differences cannot be attributed entirely to having more hours of
data. Fold-mean AUC and pooled out-of-fold AUC are labelled separately.

Only aggregate results are saved to
`data/processed/evaluation_v3/development_metrics.json`. No individual predictions
are saved. The deployed model files, manifest, risk boundaries, and historical
website charts are not replaced by this command. Hashes are checked to verify
the saved production artifacts remain unchanged.

## Limits on interpretation

These are exploratory results on development data we have examined before.
Cross-validation helps measure performance but does not turn those patients into
a new untouched final test set. Model comparisons can still be optimistic after
selection, and the timing issues above remain unresolved.

Better score calibration does not automatically mean better alerts. Lowering
scores while keeping old thresholds may reduce both false alarms and detection
of deaths. A calibrated candidate needs separate threshold and alert evaluation
before replacing the current model.

## Results from this development run

The full aggregate results are saved in
[development_metrics.json](../data/processed/evaluation_v3/development_metrics.json).
The candidates used the same available inputs, patients, and outer folds at each
checkpoint.

Random Forest versus sigmoid-calibrated Random Forest:

- 6 hours: Brier loss decreased from 0.1705 to 0.1103. Pooled ROC-AUC was
  0.7245 versus 0.7244.
- 12 hours: Brier loss decreased from 0.1607 to 0.1078, about a 33% reduction
  in average squared prediction error. Pooled ROC-AUC was 0.7439 versus 0.7437.
- 24 hours: Brier loss decreased from 0.1521 to 0.1045. Pooled ROC-AUC was
  0.7780 versus 0.7778.

At 12 hours, the observed death rate was 0.1386. The original Random Forest's
mean score was 0.3587; the calibrated candidate's mean was 0.1383. The descriptive
10-bin calibration error also decreased, from 0.2201 to 0.0122. This combination
supports further calibration work. It does not establish individual clinical
probability accuracy or a reliable result for a different hospital.

The unchanged ranking is expected: the sigmoid maps scores to a new scale.
Within-fold AUC is identical for these two candidates; pooled AUC differs
slightly because each fold fits its own mapping. Calibration is improving the
score scale here, not discovering new patient information.

Using the old 0.40 threshold at 12 hours demonstrates why we did not install the
candidate automatically. The original Random Forest detected 243 of 354 death
labels in the scored population, with 779 false positives. The calibrated model
detected 46, with 45 false positives. Fewer false alarms came with many more
missed cases. Threshold selection and alert evaluation must follow calibration.

The 640 separated patients were not scored or evaluated in this comparison.
Saved deployment models and website risk boundaries remain unchanged.

## Nested threshold and alert experiment

Run `python -m scripts.evaluate_nested_alerts` from the project folder. It saves
`data/processed/evaluation_v3/nested_alert_metrics.json`, containing aggregate
results and experiment/source hashes. Individual predictions remain in memory.

Five outer validation folds are assigned on all 2,560 development patients
before applying the measurement guard. Each patient's three checkpoints belong
to the same fold. This lets us evaluate a complete warning sequence without
training a checkpoint model on another checkpoint of its validation patients.

Within each outer training group, three inner folds produce 12-hour training
predictions for selecting thresholds. Every calibrated model also has three
calibration folds inside its own training data. Validation outcomes are kept
out of threshold selection, preprocessing, model fitting, and calibration.

The threshold rules were fixed before this run: use a grid from 0 to 1 in steps
of 0.01; seek at least 70% recall for the medium boundary and 30% for the high
boundary. Among qualifying thresholds, prefer lower false-positive rate, then
precision and a higher threshold. Keep medium strictly below high. Report an
unmet floor explicitly if that constraint makes it infeasible. These are
engineering demonstration goals, not medically approved requirements.

Thresholds are selected using the primary 12-hour task and shared across all
three checkpoints, matching the application's current structure. The report
keeps the training selection diagnostics separate from validation results.
It compares four fixed strategies: raw and calibrated scores, each with either
the historical boundaries or thresholds chosen inside the training folds.
The paired raw comparator uses the final base forest of the calibrated fit.

The existing alert rule is held fixed: an isolated elevated score produces
WATCH, and two consecutive elevated checkpoints produce HIGH_ALERT. A missing
assessment breaks persistence. The high risk boundary changes the HIGH risk
category, but the medium boundary controls both warning states. A HIGH risk
category and HIGH_ALERT are therefore different results.

The report includes warnings at each checkpoint, warnings ever seen through
each checkpoint, persistent high alerts, and first-warning checkpoint counts.
Earlier cumulative results never include later scores or availability. Missing
assessments are counted separately from false negatives and true negatives;
the fraction of all death labels detected is also shown.

Here, a false positive means a warning on a record labelled survival to hospital
discharge. It does not prove the warning was clinically unnecessary. Likewise,
the first-warning checkpoint is not a measured lead time before deterioration
or death, because exact event times are unavailable.

Each validation fold uses the threshold pair selected by its own training
group. There is no single deployable threshold in this report. This experiment
did not change the website's saved models or historical boundaries. The later
[candidate stage](calibrated-research-candidate.md) chose final settings separately
using development training data and made them available as an optional version.

## Nested experiment results

The completed aggregate report is
[nested_alert_metrics.json](../data/processed/evaluation_v3/nested_alert_metrics.json).
All four strategies used the same patient groups and coverage masks. At 12 hours,
2,554 patients were assessed: 354 death labels and 2,200 survivor labels. Six
patients had no assessment, and none of those six had a death label.

Warnings at 12 hours (WATCH or HIGH_ALERT):

- Raw forest, historical boundaries: 246 of 354 death labels detected (69.5%);
  775 survivor-labelled patients warned.
- Calibrated forest, historical boundaries: 46 detected (13.0%); 61
  survivor-labelled patients warned.
- Raw forest, nested training-selected boundaries: 252 detected (71.2%);
  797 survivor-labelled patients warned.
- Calibrated forest, nested training-selected boundaries: 252 detected (71.2%);
  798 survivor-labelled patients warned.

New thresholds restore detection after calibration, but this is **not a clear
alert-performance improvement over the original forest configuration**. The
paired raw and calibrated candidates detect the same number of death labels at
12 hours, with almost identical false-positive counts. Compared with the raw
historical reference, six additional death labels were detected at the cost of
23 additional survivor-label warnings. Calibration changes the score scale;
it does not automatically improve the model's ability to separate outcomes.

The calibrated medium thresholds selected in the five training groups were
0.12 to 0.13; high thresholds were 0.26 to 0.29. Raw thresholds were 0.39 to
0.41 and 0.56 to 0.57. These ranges describe training-fold selections, not
settings to copy into the website. All training selection recall floors were
met, but that does not guarantee a recall floor on new validation patients.

With the calibrated, training-selected thresholds:

- At 6 hours, 255 of 347 assessed death labels were detected (73.5%), with 884
  survivor-label warnings. Another seven death-labelled patients were unassessed;
  detection across all 354 death labels was 72.0%.
- At 12 hours, any warning detected 252 of 354 death labels (71.2%), with 798
  survivor-label warnings. Requiring HIGH_ALERT detected 215 (60.7%), with 642
  survivor-label warnings. The persistence rule removed 156 survivor-label
  warnings and 37 death-label detections at that checkpoint.
- At 24 hours, any current warning detected 271 of 354 death labels (76.6%),
  with 774 survivor-label warnings. Current HIGH_ALERT detected 238 (67.2%),
  with 603 survivor-label warnings.
- Considering any warning ever seen through 24 hours detected 309 of 354
  death labels (87.3%), but warned on 1,140 of 2,205 assessed survivor labels
  (51.7%). Requiring a HIGH_ALERT sometime through 24 hours detected 249 death
  labels (70.3%) and warned on 739 assessed survivor labels (33.5%). These are
  patient counts, not counts of repeated notifications.

At 6 hours the persistence rule cannot produce HIGH_ALERT: there is only one
checkpoint. Its zero high-alert detection at that time is a consequence of the
rule, not a separate model-discrimination result. The warning counts above do
not establish that waiting for persistence is clinically safe.

Numbers differ slightly from the earlier fixed-candidate report because this
experiment assigns shared outer patient folds before filtering checkpoint
coverage. Compare strategies within this report; do not mix results from the
two fold definitions to claim a gain.

The saved deployment models, manifest, and existing risk boundaries were
unchanged. Zero separated-cohort patients were evaluated. All 305 Python tests
passed, including 15 new checks of nested selection, patient grouping, missing
assessments, class identity, and chronological alert evaluation. Five existing
dependency/test-fixture warnings remain.

## What this means for the next stage

Keep calibration as a research candidate because the earlier score-quality
comparison supports it. This alert experiment supports replacing its old
thresholds when preparing a separately versioned candidate; it does not justify
claiming improved warning accuracy or silently replacing the deployed model.

A separate candidate bundle has now fitted calibration and chosen its final
thresholds using development training data only, preserved the old version,
and kept evaluation evidence separate from training diagnostics. Improving
detection at an acceptable warning
burden needs further work on inputs, model discrimination, and the intended
event definition. Exact event/ICU timing and a genuinely new evaluation cohort
remain necessary for stronger early-warning claims.
