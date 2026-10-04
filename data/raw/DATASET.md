# Dataset attribution and frozen cohort

Contains information from **Predicting Mortality of ICU Patients: The
PhysioNet/Computing in Cardiology Challenge 2012**, available under the
[Open Data Commons Attribution License v1.0](https://physionet.org/content/challenge-2012/view-license/1.0.0/).
The source database is available from
[PhysioNet, version 1.0.0](https://physionet.org/content/challenge-2012/1.0.0/).

Source authors: Ikaro Silva, George Moody, Roger Mark and Leo Anthony Celi.
When referencing the challenge, cite Silva I, Moody G, Scott DJ, Celi LA,
Mark RG, *Predicting In-Hospital Mortality of Patients in ICU: The
PhysioNet/Computing in Cardiology Challenge 2012*, Computing in Cardiology 2012.
The dataset license applies to the research database; it does not grant a
software license for this application's source code or its dependencies.

## What this project includes

- Exactly 3,200 supplied patient records under `dataset_2/train/set-a/`.
- The corresponding 3,200 outcome rows in `dataset_2/train/Outcomes-train.txt`.
- The project's frozen development/separated-patient mapping in
  `../processed/baseline/split_metadata.json`.

The original public set has 4,000 records. This project uses a frozen subset.
The subset-selection rationale from the original supplied archive is not
established; it must not be presented as a newly sampled independent benchmark.
The original duplicate ZIP was removed after all 3,201 extracted files were
confirmed byte-identical to its contents. No research records were removed.

Local outcome rows match the official public `Outcomes-a.txt`; the verification
report is `../processed/data_quality/outcome_source_verification.json`.
Exact event timing and checkpoint eligibility remain limitations described in
`../../docs/data-quality-and-evaluation.md`.

The released research records are separate from local website accounts,
assignments, staff details, notes and authentication data. Those local records
are not redistributed. Do not add private hospital data to the repository.

Restore missing files from the same trusted project release. Do not substitute
the complete public dataset or another cohort under these filenames: the saved
model manifests and split metadata are tied to the frozen subset.
