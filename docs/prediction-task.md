# Prediction task and assessment rules

## Current question

Using information recorded by 6, 12, or 24 hours after ICU admission, produce a
model score for death during the hospital stay. The training label is
`In-hospital_death`: 1 for death during the stay and 0 otherwise.

The score does not predict an exact deterioration event, an event time, or a
specific disease. It is not a verified probability of death. Retraining for
deterioration within a future time window would require suitable event labels
and timestamps, along with a new evaluation design.

## Inputs and checkpoints

The saved models use 132 V2 input features: admission demographics and summaries
of 16 supported vital/lab parameters, including latest values, averages,
extremes, counts, time since the last measurement, and slopes.

Outcome labels and identifiers are excluded from model inputs. Features at a
checkpoint use only measurements at or before that checkpoint. The primary
queue assessment remains 12 hours, with score change measured from 6 to 12 hours.
Score change describes two model outputs; it is not proof of patient improvement
or deterioration.

## Recorded-data availability

Patient detail accepts `as_of_minutes` from 0 to 1440 (default 1440):

`GET /api/patients/ICU-1001?as_of_minutes=480`

At this 8-hour view, the 6-hour checkpoint can be assessed; 12 and 24 hours are
not yet available. All vital histories are limited to minute 480. Earlier views
do not reuse a full-record detail from the cache.

This explicit view time is needed because the timestamp of the last measurement
does not tell us whether the patient is still being observed. The default is a
historical 24-hour view, not a claim that every patient remained in the ICU for
24 hours. Survival and ICU eligibility at each checkpoint remain open questions.

## Missing-data policy, version 1

Every assessment includes a status:

- `READY`: the checkpoint has been reached and at least one usable supported
  vital/lab observation exists by that checkpoint.
- `INSUFFICIENT_DATA`: the checkpoint has been reached, but no such observation
  exists. Basic details such as age and ICU type do not qualify alone.
- `NOT_YET_AVAILABLE`: the checkpoint is later than the selected view time.

Unavailable assessments have null score, risk category, and alert fields. They
are never represented by a zero score, LOW risk, or NO_ALERT. They explain why
they are unavailable. Score change is null if either comparison is unavailable.

`temporal_observation_count` counts non-missing supported temporal observations
after preprocessing, at or before the checkpoint. Unknown and excluded
parameters do not count. A future checkpoint returns zero because no assessment
has been made. Infinite feature values cause a controlled inference error.

This is a minimum technical guard. It does not establish an adequate amount or
mix of data, correct units, plausible values, recent measurements, or clinical
reliability. Other missing inputs still use the imputer saved during training.
More demanding coverage rules need measured evidence rather than invented
clinical thresholds.

## Scores and alerts

The original model's boundaries are unchanged: LOW below 0.40, MEDIUM from 0.40
to below 0.55, and HIGH from 0.55. The separate calibrated research candidate
uses training-selected boundaries of 0.12 and 0.28. The website shows the
selected version and its boundaries; caches and index files are separate.
Both versions display scores on a 0–1 scale, not verified clinical percentages.

The demonstration alert policy is unchanged for available assessments:

- Current LOW: NO_ALERT.
- One elevated assessment: WATCH.
- Two consecutive available MEDIUM/HIGH assessments: HIGH_ALERT.

An unavailable assessment breaks the sequence. A later elevated assessment
starts at WATCH; it cannot inherit persistence across the gap. Unavailable
patients are counted separately and excluded from risk and alert totals.

These rules have not been validated for clinical usefulness. Repeated elevated
scores are not proof that the patient is getting worse. NO_ALERT is not proof
that the patient is safe.

## Evaluation limits and next work

The 640-patient development holdout has already been examined. It is not a fresh
final test set. Making a new split of previously examined data does not erase
earlier exposure. Saved cross-validation results are historical development
evidence and predate the new assessment guard.

Coverage, calibration, and nested threshold/alert experiments have been completed
on development data. A separately fitted research candidate is now available
without replacing the original model. Exact checkpoint clinical eligibility is
still unknown; the new bundle does not resolve that limitation or establish
improved warning accuracy. See [candidate details](calibrated-research-candidate.md).
A streaming demonstration must replay measurements in time order and stay
clearly labelled.
