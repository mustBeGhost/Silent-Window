# Demo guide and resume notes

## A short demonstration (about three minutes)

Use an isolated demonstration installation with fictional staff notes. Do not show
.env, SQL passwords, recovery codes, real staff accounts or browser saved passwords.

1. Explain the goal: review recorded ICU observations, experimental mortality-risk
   scores and staff follow-up work. State that this is a research demonstration.
2. Open the patient queue and select a patient. Explain that 6/12/24h are observation
   cutoffs after admission, not future prediction windows. Show risk and alert rules.
3. Show clinical context, separate invasive/cuff vital readings and staff notes.
4. Open My Shift: pending follow-ups, due reviews, current availability and warnings.
5. Demonstrate a doctor-review request, acknowledgement and resolution. Explain that
   acknowledging does not clear the model warning or prove treatment was given.
6. Show a same-role shift handover. The receiving staff member confirms before the
   assignment transfers. Demonstrate using fictional staff in a separate demo copy.
7. Search older staff history and show Download research PDF.
8. Open Model Performance. Show both detected death labels and survivor warnings.
   Explain same-source Set B testing and that prospective hospital validation is absent.

## A plain-English project explanation

Silent Window is a full-stack research dashboard built with React, FastAPI, MySQL
and scikit-learn. It uses recorded public ICU observations to calculate hospital-stay
mortality-risk scores at fixed checkpoints. It combines those research outputs with
role-based patient access, structured staff notes, follow-up tracking, confirmed
shift handovers and PDF summaries. Live website updates synchronize staff actions;
they are not a hospital feed. The project measures missed cases and survivor warnings
and clearly separates demonstration workflow from clinical validation.

## Resume wording to adapt

Project: Silent Window - ICU Mortality-Risk Research Dashboard
Stack: Python, scikit-learn, FastAPI, React, MySQL, SQLAlchemy, Vite, Recharts.

- Built a role-based ICU research dashboard with patient assignments, structured
  notes, follow-up reminders, doctor-review requests and confirmed shift handovers.
- Implemented chronology-safe checkpoint inference, authenticated website updates,
  searchable audit history and access-controlled PDF exports.
- Evaluated frozen mortality-risk policies on 4,000 additional, patient-disjoint
  PhysioNet records, reporting detection, missed death labels and survivor warnings.

Adapt the wording to accurately describe your own contribution and understanding.
Do not describe this as a deployed hospital system, a certified medical device,
real-time clinical mortality prediction, or 92.6% overall accuracy. The 92.6% figure
is recall among scored death-labelled Set B patients under the expanded warning
policy, with substantial survivor warnings. Avoid one-number resume claims.

## What the owner must do

- Practise explaining data -> preprocessing -> model -> score -> warning -> staff
  workflow, and explain the difference between recall and overall accuracy.
- Record personal narration if a video with your voice is wanted. Screenshots and
  this walkthrough are ready; a personal spoken demonstration is not recorded here.
- Add the GitHub URL to your resume, adapt the bullets and verify dates/team credits.
- Choose any later public hosting. GitHub source publication does not host this
  React/FastAPI/MySQL application as a live service.

No database credentials, shared website passwords or API keys are required in the
public repository. Each downloader configures their own database and accounts.
