# Calibrated research candidate

Use **Model version** in the website header to switch between **Original Random
Forest** and **Calibrated research candidate**. The original is the default.
Starting the app does not train either model. Changing versions reloads the
displayed page; the two services have separate patient caches and complete-cohort
index files. Patient IDs stay the same. The website checks the model identity
returned by the API before accepting assessment results.

The candidate is for research. Earlier development experiments support its score
scale, but did not show a clear improvement in warning accuracy. Its scores are
not verified clinical probabilities. Exact ICU/event timing and a genuinely new
evaluation cohort remain unresolved.

## Saved model versions

The historical files remain under `ml/artifacts`, with unchanged file hashes
and medium/high boundaries of **0.40 / 0.55**.

The separate candidate bundle under `ml/artifacts/calibrated_rf_v3` contains:

- `rf_v3_6h.joblib`, `rf_v3_12h.joblib`, and `rf_v3_24h.joblib`.
- `calibrated_rf_v3_manifest.json`, recording hashes, training coverage,
  thresholds, library versions, source/evidence fingerprints, and limitations.

It uses the same 132 V2 input features and Random Forest settings, with sigmoid
calibration fitted through three internal folds. Final fitting uses only
scoreable development patients: 2,506 at 6 hours, 2,554 at 12 hours, and 2,559 at
24 hours. The 640 separated patients were excluded from fitting, calibration,
and threshold selection. Viewing a record in the app is inference; it is not a
new performance evaluation against outcome labels.

## Final training-selected thresholds

The candidate's medium/high boundaries are **0.12 / 0.28**, shared across all
three checkpoints. LOW is below 0.12; MEDIUM is from 0.12 to below 0.28; HIGH
starts at 0.28.

Three training folds were assigned to all development patients before applying
12-hour coverage masks. Each selection score came from a calibrated model that
did not fit that patient. Calibration stayed inside each selection model's
training data. The fixed grid and 70%/30% engineering recall floors are the same
rules used in the nested alert experiment.

After threshold choice, the three final models were fitted on their scoreable
development populations. The manifest's selection metrics describe training
tuning, **not independent performance of the final bundle**. See
[data quality and evaluation](data-quality-and-evaluation.md) for the separate
nested validation results and their limitations.

Both versions use the existing persistence rule: an isolated elevated assessment
gives WATCH; two consecutive elevated assessments give HIGH_ALERT; missing data
breaks persistence. The high risk boundary changes HIGH risk categories, not the
alert persistence requirement. Score-change labels still use the existing 0.02
presentation rule, which is not a medical deterioration test.

## Reproduce the bundle

From the project folder:

```powershell
.venv\Scripts\python.exe -m scripts.train_calibrated_candidate
```

The command refuses an existing destination. For a separate reproducibility run:

```powershell
.venv\Scripts\python.exe -m scripts.train_calibrated_candidate --output-dir ml/artifacts/calibrated_rf_v3_rerun
```

That alternate folder does not automatically become the app's candidate. The
command reads development observations only, checks the evaluation evidence,
keeps individual selection predictions in memory, writes through a staging
folder, and verifies that historical model files remain unchanged.

The loader checks file hashes before loading models, validates the fitted
calibrator/base-forest structure and feature order, and requires the scikit-learn
version recorded in the manifest. An incompatible or missing candidate is shown
as unavailable. Candidate requests never silently use the original model.

## API usage

`GET /api/models` lists both versions, availability, and loaded boundaries.
Patient, index, and health requests accept `model_profile=original` or
`model_profile=calibrated`. Omitting it uses the original.

For example:

```text
GET /api/patients/ICU-1001?model_profile=calibrated&as_of_minutes=480
```

This requests the candidate in an 8-hour historical view. The 12-hour and
24-hour assessments remain unavailable. Patient/index responses identify their
model with `X-Silent-Window-Model`, exposed to the local frontend through CORS.
The performance page stays an archive for the original model; switching versions
does not relabel its old charts as candidate results.

## Verification

- 326 Python tests passed, with five existing warnings.
- 23 frontend checks passed; the production build passed, with the existing
  large-bundle warning.
- Running HTTP checks verified both versions, return to the original,
  historical-time limits, CORS model identity, and frontend delivery.
- Training/evaluation dataset and source fingerprints matched. Historical files
  were unchanged, and all three candidate files are included among the project's
  versionable files.
- Component rendering was checked. Browser layout and interactive clicking were
  not visually verified; earlier local-browser access was blocked.

The next planned stage is automatic replay of recorded measurements, clearly
labelled as a demonstration, with assessments at the supported checkpoints.
