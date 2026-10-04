# Five-checkpoint research timeline

The new option assesses recorded ICU data at **6h, 9h, 12h, 18h and 24h** after admission. There is no 3h assessment. The main patient queue and large patient score remain the 12h assessment.

Choose **Five-checkpoint research candidate** in the model selector. Original Random Forest and the earlier calibrated V3 remain available with their original three checkpoints and thresholds. The new option is a separate calibrated Random Forest V4 research bundle, not a claim that it is the best model or ready for hospital use.

## What changed

- Separate prefix-only models for all five times, trained on the frozen development cohort only.
- New 9h and 18h assessments in the patient trajectory, API, model information, header and sidebar.
- The main 12h alert checks the immediately preceding 9h score. Elevated 6h followed by low 9h and elevated 12h gives WATCH at 12h, not HIGH ALERT. Two consecutive elevated checkpoints are required. A missing assessment breaks the sequence.
- The first assessment is 6h: an elevated score can give WATCH there. The earliest possible persistent HIGH ALERT in this option is 9h.
- Replay and manual recorded-time selection include the new checkpoints. Playback cannot skip a checkpoint even when resuming between assessment times.
- The performance page shows the comparison and distinguishes warnings at one time from patients warned at least once so far.
- Each time uses readings up to that time only. Future assessments remain unavailable; missing measurements do not become fake zero scores.

## Evaluation and results

The fixed comparison used 2,560 development patients with 354 in-hospital-death labels, five outer patient folds and three inner threshold folds. The separate 640-patient cohort stayed out of fitting and evaluation. Validation patients never entered the fitting or threshold selection for their own fold.

The same V2 input features, calibrated Random Forest settings and shared-time predictions were used for both timelines. Warning thresholds were selected from inner training predictions at 12h for an 85% recall target, then applied at every checkpoint. The earlier three-time 85% control reproduced exactly.

At 12h, both timelines warned on **311 of 354 death labels (87.9%)**, missed 43, and warned on **1,225 survivor labels**. Extra checkpoints do not change that individual 12h score or any-warning decision. They change which previous score the persistence rule uses: five-time HIGH ALERT at 12h warned on 298 death labels and 1,116 survivor labels, compared with 296 and 1,085 under the three-time sequence.

Counting patients warned at least once through 12h, five checkpoints warned on **337 death labels and 1,522 survivor labels**, compared with **333 and 1,484** under three checkpoints.

Counting patients warned at least once through 24h, five checkpoints warned on **345 death labels and 1,612 survivor labels**, compared with **342 and 1,559** under three checkpoints. That is **three additional death-labelled patients warned, alongside 53 additional survivor-labelled patients warned**. This is a small detection gain with more warnings, not proof of better overall accuracy.

Coverage excludes patients with no usable model-supported temporal reading at that time: 54 at 6h, 19 at 9h, 6 at 12h, 3 at 18h and 1 at 24h. At 9h, four death-labelled patients were unassessed; at 6h, seven were unassessed. Missing patients are counted separately from assessed misses. One reading is only a minimum technical guard, not evidence of sufficient clinical coverage.

## Saved bundle and boundaries

`ml/artifacts/expanded_rf_v4/` contains five separately fitted models and a manifest. Final boundaries were selected from development training predictions only: medium **0.08**, high **0.28**. These are research settings and differ from V3's 0.12/0.28. HIGH ALERT depends on consecutive elevated scores, not simply on exceeding the high risk-category boundary.

The final saved models were fitted using eligible development patients at each cutoff. The reported validation numbers describe the evaluation procedure, not an independent test of those final saved models. No individual validation predictions are saved. Earlier model bundles and research evidence are protected by file hashes.

The aggregate evidence is `data/processed/evaluation_v3/checkpoint_expansion_metrics.json`; its website export is `frontend/src/data/checkpointExpansion.json`. Reproduction commands are `python -m scripts.evaluate_checkpoint_expansion` and `python -m scripts.train_expanded_candidate`; both refuse to overwrite their existing evidence or bundle.

## Limits

The target is death during the hospital stay. These times are assessment cutoffs, not predictions of death within the next 6, 9, 12, 18 or 24 hours. Exact death and ICU exit times are unavailable. We cannot verify that a warning preceded death, that each patient was still alive in ICU at every cutoff, or that these alerts help patients clinically.

Survivor warnings are false positives against the death label; they are not proof that those patients needed no clinical attention. Development data has been examined repeatedly. These results are exploratory, and the scores are not verified clinical probabilities.

## Verification

The Python checks cover training/validation separation, missing-data counts, protected evidence, bundle integrity, exact cutoff boundaries, future-score blocking, unchanged earlier scores after modifying future readings, cache isolation, and queue/detail agreement with the new 9h/12h persistence rule.

Frontend checks cover five-point response validation, the 12h primary result, future-data rejection, profile identity and replay visits to 9h and 18h. Browser checks verify the new selector, the 9h and 18h recorded views, replay completion, and the visible comparison report.

Completed checks: **381 Python checks**, **45 frontend checks**, and the production build passed. Existing dependency deprecation warnings and the existing large frontend bundle warning remain.
