# Silent Window - project handover

Last checked: 2026-10-30. Read this first when continuing in another ChatGPT/Codex
chat or on another laptop. This is a maintained project summary, not a complete
transcript. The actual source and manifests take priority if they differ from this
file. Paths below are relative to the project root (the folder containing README.md).
No passwords, session tokens or private database URLs belong in this document.

## 1. Instructions for the next assistant

- Speak to the owner in simple English. Explain what an action achieves.
- Inspect this folder before suggesting that a feature is missing. Many features
  are already implemented. Preserve existing work and user records.
- This is a local research/portfolio project. Do not claim clinical readiness.
- Publication was explicitly authorized on 2026-10-30 for this finished version.
  Future uploads, deployments or public changes require the applicable user request.
- Keep the existing dark laptop design. The owner rejected replacement Stitch
  designs and does not currently want mobile-layout work.
- Keep professional source files, tests, documentation and GitHub checks in shares.
  Exclude credentials, local accounts, databases, backups and generated caches.
- The owner requested no application source-code license. Do not add one on your
  own. Public dataset attribution and its separate license must remain intact.
- Use the existing local MySQL server. Do not create another server on port 3307.
- Never print .env values or recover old credentials from chat logs for sharing.
  A new laptop must use its own credentials and create its own administrator.
- Never run destructive MySQL test fixtures against a database with accounts the
  owner wants to retain. Prefer SQLite fixtures or rolled-back MySQL verification.
- A new chat cannot access this laptop or database just because this file says
  they exist. Check its own available tools, folder and permissions.
- Update this file after material changes, with honest test and completion status.

Suggested first message in the new chat:

> Read docs/PROJECT_HANDOVER.md, README.md and the linked setup and workflow docs.
> Inspect the actual project files and current changes. Explain the current state
> and unfinished checks in simple English before continuing. Keep existing data
> safe, keep the laptop design, and do not upload or deploy without my approval.

## 2. Purpose and problem

Silent Window helps demonstrate how ICU staff could review recorded observations,
model risk scores, warnings and follow-up work in one place. It grew from a hackathon
project into a resume/portfolio application. Do not invent awards, clinical trials or real hospital adoption.
A family member suggested the clinical-context additions listed in the original
icu-clinical-enhancements.md in the outer workspace. That file may not travel with
this folder; the implemented scope is preserved here and in clinical-enhancements.md.

The prediction question is death during the hospital stay, using observations
available by a checkpoint after admission. It is NOT a prediction of death in the
next 6/12/24 hours, an exact deterioration time, a diagnosis or a treatment plan.
Scores are research outputs, not verified individual clinical death probabilities.
Staff notes do not feed the models. A patient who survived can still have received
appropriate care or been seriously ill; a survivor warning is a false positive
against this dataset outcome, not proof the patient did not need attention.

There is no connected hospital device or live clinical feed. Recorded replay and
live website synchronization are different features. Real hospital integration,
prospective validation, new deterioration labels and production deployment remain
future projects, not completed work.

## 3. Implemented features

### Accounts and five roles

- First-admin setup, sign-in/out, revocable cookie sessions and hashed passwords.
- Worker signup submits a request to the permission table. Pending/rejected
  applicants are not active users. Approval creates the actual user account.
- Administrators review requests, manage accounts, roles and active access.
- Usernames are unique, lowercase alphanumeric, start with a letter; numbers are
  optional. Alphabetic content is required. Duplicate names get a warning.
- Password visibility controls, confirmation, password changes and assisted recovery.
- Normal password forms retain the existing 15-character policy. Do not assume
  shorter operator-seeded local demonstration passwords change the public policy.
- Per-account preferences include model, queue page size and replay step.
- Administrator account-request notifications and compact reviewed-request history.

Roles and limits:

- Administrator: unit patient visibility, account approvals/management and team
  assignment. Can edit admission context; cannot perform doctor-only review actions.
- Doctor: only assigned patients, visits/assessments/recommendations, follow-ups,
  warning acknowledgement, doctor-entered vital limits and assigned review responses.
- Nurse: only assigned patients, observation/follow-up/handover/escalation work and
  warning acknowledgement; cannot acknowledge/resolve a routed doctor review.
- ICU coordinator/head nurse: unit patient visibility, doctor/nurse assignments,
  admission context and coordination/follow-up/handover work.
- Researcher/reviewer: aggregate research results; no individual patient records.

backend/permissions.py and backend/auth.py are authoritative. UI hiding alone is
not permission enforcement. Roles/active status/assignments are rechecked on writes.

### Patient queue and model views

- Search, sort, pagination, risk/alert filters and assigned-patient scoping.
- Complete-cohort assessment index for supported unit-wide filtering; report index
  readiness explicitly rather than pretending a loaded page is the whole cohort.
- Three selectable saved model profiles; model notices explain each policy.
- Patient score, category, alert explanation, checkpoint trajectory and change.
- Recorded replay: play/pause, speed, reset and selected time through minute 1440.
- Future checkpoints remain unavailable and future observations are hidden.
- Missing/insufficient data is distinct from a zero score or NO ALERT.
- Performance page includes development studies and separate Set B results.

### Clinical context and staff workflow

- Invasive systolic/diastolic/MAP and cuff systolic/diastolic/MAP stay separate.
- Other readings: heart rate, respiratory rate, arterial oxygen saturation,
  temperature, GCS and creatinine. Latest reading times/ages and missingness shown.
- Admission diagnosis/reason/severity, condition summary, specialty and responsible
  doctor. Unavailable dataset facts say Not provided. Staff additions are labelled
  demonstration entries, not original patient facts.
- Multiple assigned doctors and nurses, separate expandable lists and editors.
- Responsible physician must already be active and assigned; historical selections
  remain labelled if the assignment later changes.
- Doctor visits, assessments, recommendations, plans, follow-ups, handover and
  escalation notes, with actual save date and recorded patient minute kept separate.
- Combined patient timeline with recorded/staff filters and explicit display limits.
- Doctor-entered demonstration vital limits, version history and separate warnings.
  No default clinical thresholds, automatic diagnosis or prescriptions are supplied.
- Model warning acknowledgement records who saw it. It never clears model alerts
  or confirms care. Vital warnings, model alerts and staff requests remain separate.

### Follow-ups and routed doctor review requests

- Follow-ups start pending; authorized staff can complete/reopen with a reason.
- Planned review times are compared with recorded view time, not today's clock.
- Status history is append-only; stale or backdated changes are rejected.
- Explicit doctor review requests: pending -> acknowledged -> resolved. Only a
  currently assigned doctor can acknowledge/resolve. Staff can reopen with a reason.
- Plain legacy escalation notes are not silently turned into routed requests.
- Requests without an active assigned doctor remain visibly waiting for assignment.
- Review inbox with status filters/pagination and assigned-patient scope.
- Doctor popup and sidebar count; per-account dismissal, newly assigned older
  requests and reopened requests handled separately. No email/SMS/paging integration.

### Latest eight requested improvements

All eight now have implementation in the working source:

1. My Shift: assigned work (unit overview for managers), patients, pending follow-ups,
   recorded-time reminders, doctor requests, warning review and shift handovers.
2. Confirmed shift handover: same-role active doctor/nurse recipient; task snapshot;
   recipient accepts before assignment transfers. Recipient can decline; sender or
   coordinator can cancel. Acceptance changes only the sending assignment. The
   receiving person must be On duty. Concurrency and changed assignments checked.
3. Follow-up reminders: due exactly at planned recorded minute, overdue afterward.
   They are in-app highlights, not a background real-hospital alarm scheduler.
4. Staff availability: self-reported On duty/Off duty/Unavailable, default Not set,
   notes/history and actual save time. Off-duty/unavailable doctors get no new
   review popups; existing access and inbox records stay. Patient coverage flags
   missing confirmed on-duty doctor coverage. No automatic staff reassignment.
5. Research PDF: selected model and recorded cutoff, admission/team/vitals with
   units/time/age, assessments, warnings, acknowledgements, follow-ups, requests
   and recent notes. Generated in memory, access checked, no server-side PDF store.
   Staff lists capped at 30 and limits printed. Research label on every document.
6. Staff-history search: text, author, kind, recorded start minute and actual saved
   date range; pagination reaches beyond the short timeline's 200-record caps.
   Correct labels distinguish admission diagnosis, plans and status actions.
7. Immediate website updates: cookie-authenticated Server-Sent Events (SSE), scoped
   revision hash, server checks about once per second; existing authorized APIs
   refetch content. Hidden/logout cleanup and session rechecks. Thirty-second
   notification polling remains a fallback. This is not live hospital inference.
8. Further evaluation: frozen models/policies tested on 4,000 patient-ID-disjoint
   PhysioNet Set B records, with missed-case groups and coverage accounting. No
   training, threshold tuning, default-model replacement or clinical validation claim.

## 4. Design and interaction decisions

The current design is a dark laptop dashboard, not a replacement Stitch design.
frontend/src/index.css owns the common visual system. Main colors include a nearly
black canvas (#0a0e17), dark panels (#181b25), cyan accents (#7bd0ff/#38bdf8), green
low states, amber watch states and red high states. Inter/system fonts are used;
the stylesheet imports Google fonts but has local fallbacks.

Shared header: logo, model selector, checkpoint/primary context, signed-in account.
Sidebar: Patient Queue, Model Performance, My Shift, Review Requests, My Account;
admin-only Account Requests and Team Accounts. Patient page has section links,
score/trajectory, optional collapsed replay, clinical context, doctor requests,
follow-ups, vitals, warnings, shift handover, searchable history, team and timeline.
Use labelled forms, visible errors/status, keyboard focus, loading/empty states and
explicit unknown values. Avoid presenting unknown readings as normal or safe.
Mobile work was deferred by the owner. Existing wrapping styles are not a claim of
completed mobile QA. Do not reintroduce old design exports as the source of truth.

## 5. Architecture and data flow

Browser React UI -> relative /api requests -> FastAPI -> authorization/services ->
MySQL for accounts/staff records; saved scikit-learn pipelines and recorded files
for inference. Vite proxies /api to the backend during local development.

- frontend/: React + Vite, React Router, Recharts; normal website localhost:5173.
- backend/main.py: FastAPI entry point, routers, local host/origin rules, no-store
  API headers and safe database error handling; local API 127.0.0.1:8001.
- backend/auth.py: cookie session, CSRF, role and assigned-patient checks.
- backend/services/auth_service.py: Argon2id password hashes, sessions, recovery,
  approvals, preferences. Local credentials loaded privately from ignored .env.
- backend/services/account_database.py: SQLAlchemy schema and SQLite/MySQL adapter.
  MySQL is required for normal app use; SQLite is for isolated tests/previews.
- backend/services/patient_service.py: manifest verification, model loading,
  opaque patient IDs, cutoff-safe inference, caches and cohort index.
- ml/: loading, chronology-safe preprocessing/features, coverage, risk/alert policy,
  experiments and trusted saved pipelines. No automatic retraining at startup.
- data/raw/dataset_2/train/: frozen local public cohort and Outcomes-train.txt.
- data/processed/: splits, aggregate evaluation reports and ignored runtime storage.
- scripts/: setup, migration, verification, research runs and clean release export.
- tests/ and frontend/tests/: backend, model, permissions, storage and UI checks.
- .github/workflows/checks.yml: source checks/tests/build after publication; no
  production deployment or personal database credentials.

Frontend requestJson includes cookies; CSRF token stays in memory for mutations.
SSE sends only a revision, then clients refetch their permitted data. The MySQL
adapter translates application-owned ? parameters into bound SQLAlchemy parameters.
BEGIN IMMEDIATE uses SQLite locking or a MySQL auth_write_lock row for short writes.
Model artifacts and feature order are checked; do not load untrusted pickle/joblib.

### Important source navigation

- frontend/src/App.jsx: routes and auth/model/live/notification providers.
- frontend/src/context/: Auth, ModelProfile, account/review notifications, WorkspaceLive.
- frontend/src/pages/: Dashboard, PatientDetails, MyShift, ModelPerformance,
  Login/Register/Recover, Account, TeamAccounts, PermissionRequests, ReviewRequests.
- frontend/src/components/: ClinicalWorkspace, DoctorReviews, FollowUps,
  PatientTeam/Workflow/Handover/History/Pdf, HandoverCards, SeparatePatients,
  RecordedReplay, RiskTrajectory, AlertExplanation and common layout.
- frontend/src/utils/: recorded replay controller, clinical validation/timeline,
  history labels, notification identities and live-stream lifecycle.
- backend/routes/accounts.py: authentication, approvals and account management.
- backend/routes/patients.py, models.py, health.py: assessments/model options/readiness.
- backend/routes/workflow.py: team assignment and model-checkpoint review notes.
- backend/routes/clinical.py: recorded clinical snapshot and staff writes.
- backend/routes/shifts.py: My Shift, availability, handover offers/actions/warnings.
- backend/routes/history.py: scoped paginated staff history.
- backend/routes/reports.py, services/patient_pdf.py: PDF snapshot/export.
- backend/routes/live.py: authenticated scoped /workspace/events SSE stream.
- services/follow_ups.py, doctor_reviews.py, shift_workflow.py: reusable query views.

Key API examples (all under /api; protected endpoints require the appropriate role):

- /patients, /patients/{id}?as_of_minutes=600&model_profile=original
- /patients/{id}/clinical, /patients/{id}/workflow
- /patients/{id}/clinical/context, /entries, /rules, /review-requests
- /patients/{id}/clinical/entries/{entry_id}/follow-up
- /patients/{id}/clinical/review-requests/{request_id}/status
- /review-requests and /review-requests/summary
- /shift, /shift/warnings, /staff/availability, /handovers
- /patients/{id}/handovers and /handovers/{id}/status
- /patients/{id}/history, /patients/{id}/summary.pdf, /workspace/events

Read the route decorators for exact methods/body definitions. Interactive local API
schema is available at http://127.0.0.1:8001/docs when the backend is running.

## 6. Database and security

Current schema version: 7. Normal schemas: silent_window and silent_window_auth_test
on the owner's existing MySQL server, port 3306. Other unrelated databases are out
of scope; do not delete/change them. Website accounts are separate from MySQL users.
Credentials and actual local database contents are intentionally not in this file.

Tables and purposes:

- users: approved accounts/roles/preferences/password hashes; sessions: hashed
  revocable login sessions; attempts: rate-limit buckets; account_events: audit.
- permission: signup requests and review decisions; password_resets: expiring hashed
  recovery tokens; assignments: patient/staff links; patient_events: checkpoint notes.
- patient_contexts: admission/context revisions; clinical_entries: structured notes.
- vital_rule_versions: doctor-entered limits; follow_up_events: status transitions.
- doctor_review_requests + doctor_review_events: routed request identity/status history.
- availability_events: append-only current staff status; handovers + handover_events:
  offers, captured pending tasks and accepted/declined/cancelled actions.
- schema_version: migration state; auth_write_lock: serialized critical MySQL writes.

Local project and test databases were upgraded additively. Existing rows were
compared before/after and preserved. Previous local demonstration role accounts
exist on the owner's machine, but fresh installations seed no shared login.
Do not include those passwords or promise that local accounts travel with source.
Copying the folder does not copy the external MySQL server or its records. A private
account/data migration would require a separately approved backup/restore process.

## 7. Model/data details and evaluation

- Local public cohort: 3,200 records, PhysioNet/Computing in Cardiology Challenge 2012.
- Frozen development split: 2,560 patients, 354 death labels. Previously examined
  separated split: 640 patients, 89 death labels; do not call it untouched.
- Inputs: 132 ordered V2 features, four demographics and summaries of 16 vital/lab
  variables (latest, mean, min, max, std, count, time since last, slope).
- Exclude identifiers/outcome-derived columns from inputs. Features use observations
  at or before their own cutoff. Imputation/preprocessing must fit training only.
- Original Random Forest V2 and sigmoid-calibrated V3: checkpoints 6/12/24h.
  Expanded calibrated V4: 6/9/12/18/24h. Primary queue result remains 12h.
- 3 original + 3 calibrated + 5 expanded runtime models and their manifests are saved.
  Historical logistic models are kept for research checks.
- Original medium/high score boundaries: 0.40/0.55. Other profiles read their saved
  manifests. Do not invent or silently retune thresholds.
- Current LOW -> NO ALERT. First elevated score -> WATCH. Two consecutive supported
  elevated checkpoints -> HIGH ALERT. Missing assessments break persistence.
- At least one usable supported temporal measurement is required for scoring. This
  minimum guard is not proof of adequate clinical data. Missing != zero risk.
- Admission notes, recommendations and staffing do not alter model scores.
- Outcome timing/ICU eligibility cannot be established exactly from supplied rounded
  outcomes. Do not claim prediction of future deterioration or safe clinical use.

Additional Set B evaluation (completed 2026-10-28): 4,000 patients; 568 death labels;
no record-ID overlap with local data. At 12h, 3,977 scored patients include 566 death
labels; 23 unscored include two deaths. Any-warning results among scored deaths:

- Original: 432 detected / 134 missed; 1,216 survivor warnings; recall 76.3%.
- Calibrated: 455 detected / 111 missed; 1,316 survivor warnings; recall 80.4%.
- Expanded: 524 detected / 42 missed; 1,990 survivor warnings; recall 92.6%.

These are hospital-death labels, not alert percentages or overall accuracy. Two
unscored death cases are additional to scored misses. Any warning includes WATCH;
HIGH ALERT-only counts are separately available. Expanded recall trades off against
58.3% of scored survivors receiving a warning. Shared checkpoint models can give
different warnings under different thresholds and persistence sequences.

Set B comes from the same dataset source, not another hospital trial. No fitting or
threshold tuning was performed on Set B, no saved model was replaced, and it is now
an examined cohort. Descriptive age/ICU/coverage groups do not prove causation or
fairness. Individual predictions were not saved. Hashes/provenance and aggregates:

- data/processed/evaluation_v3/separate_patient_metrics.json
- frontend/src/data/separatePatients.json
- scripts/evaluate_separate_patients.py and ml/error_review.py
- docs/separate-patient-evaluation.md

Public source: https://physionet.org/content/challenge-2012/1.0.0/
Released Set B observations/labels were downloaded into ignored .release-check.
The current source listing includes labels although the historic introduction says
they were withheld during the challenge. Attribution: Silva et al., Computing in
Cardiology 2012;39:245-248; Open Data Commons Attribution License v1.0. Preserve
this attribution. Website operation needs only bundled local data and aggregates,
not the optional additional Set B download.

## 8. Setup on another laptop

Use README.md and docs/setup-guide.md for full instructions. Windows tested baseline:
Python 3.11, Node.js 22+, existing MySQL 8 on port 3306. React/Vite and Python pins
are in package-lock.json, requirements files and requirements-lock.txt.

Fresh Windows install, from project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_silent_window.ps1
.\run_silent_window.bat
```

Supply the NEW laptop's MySQL administrator password privately when prompted. Setup
creates restricted app/test database users and an ignored .env. Do not copy the old
.env. Open http://127.0.0.1:5173 and create the first website administrator. No paid
API key is needed. Existing initialized databases require migration, not fresh setup.

For an existing installation, stop only this project's servers, install dependencies,
run the additive migration, check setup and restart:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt -c requirements-lock.txt
.venv\Scripts\python.exe -m scripts.migrate_accounts
.venv\Scripts\python.exe -m scripts.check_installation
```

The migration prompts privately for MySQL administrator credentials. It supports
older versions through schema 7 and retains accounts/notes. ReportLab 4.5.1 was added
for PDFs. SQLite is not a normal production fallback. If starting servers manually:

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

In another terminal inside frontend:

```powershell
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort
```

Direct Node startup avoids a PowerShell/npm argument-forwarding issue encountered
in this session. Do not stop unrelated Python/Node programs to free ports. Verify
exact project process and port first. Do not assume old process IDs are current.

## 9. Validation evidence and remaining closeout

Recorded results from the preceding work (historical evidence, not rerun by writing
this handover):

- Full backend/model suite: 478 passed, 84 MySQL-parametrized cases deselected.
- Seven subsequent aggregate evaluation/cohort validation tests passed.
- A focused final group of workflow/evaluation/release/migration checks: 27 passed;
  final nine workflow tests rerun after history fixes also passed.
- Latest frontend suite: 86 passed. Final production build passed.
- MySQL query verification used a transaction, rolled back test inserts and compared
  existing rows. Owner's normal/test accounts were preserved.
- Browser: fictional receiving doctor accepted a handover; dashboard gained patient,
  follow-up and review request; early recorded-time reminders stayed quiet; history
  search and PDF download worked. Isolated storage kept real app records untouched.
- Final two-page fictional PDF was text checked, rendered and visually inspected;
  labels, units, warning text, footers and page breaks were checked.
- Release scan passed with 3,461 selected files before this handover was added.
  That count is historical and should increase as project files are added.

## Publication closeout (2026-10-30)

The owner approved publishing this finished version. The clean Python runtime
reported no broken dependencies and passed model loading, MySQL connectivity and
installation checks. A new full regression run (485 passed), frontend checks/build (86 passed) and source
export checks were performed; see docs/release-verification.md for exact results.
README screenshots were refreshed using fictional staff accounts in an isolated
preview. docs/demo-and-resume.md provides a short demonstration guide, accurate
resume wording and the remaining owner tasks. No new feature expansion is planned.

Do not interpret local process IDs, cached downloads, virtual environments or old
preview credentials as part of the project. Temporary QA material is excluded from
all publication packages. New machines create their own database and accounts.

Commands for safe local checks (from project root):

```powershell
.venv\Scripts\python.exe -m pytest tests -q -k 'not mysql' --tb=short
.venv\Scripts\python.exe -m scripts.check_installation
.venv\Scripts\python.exe -m scripts.prepare_release
```

Frontend: npm test and npm run build inside frontend. The MySQL test fixture in
 tests/test_auth.py clears multiple tables in a configured *_auth_test schema. That
name alone does not make its records disposable. Get a genuinely isolated database
before enabling those destructive cases. Preserve starter users in the owner's test
schema. Tests/CI are professional development files; do not remove them as junk.

## 10. Sharing and GitHub state

Original working folder on the old laptop: B:/Hackathon/Yuva. Outer B:/Hackathon also
contains older submission/export folders and archives; they are not the active app.
The old publication clone was B:/Hackathon/Silent-Window-Publish. Do not mistake it
for current source or overwrite the active folder with it.
Existing public repository: https://github.com/mustBeGhost/Silent-Window
This file does not assert the remote matches the local working tree. There are many
pre-existing modified/untracked files and intentional deleted design exports; do
not reset, discard or stage everything indiscriminately.

Share a clean project source archive, not the whole outer workspace. The supported
export performs selection and secret checks and never pushes automatically:

```powershell
.venv\Scripts\python.exe -m scripts.prepare_release --zip dist/silent-window-handover-source.zip
```

Use a new filename if that archive already exists; the exporter refuses overwrite.
The archive includes this document (docs/*.md), app source, professional tests,
docs, pinned dependencies, saved models and required attributed public observations.
It omits .env, .git, dependencies, local SQL/SQLite data, backups, runtime caches,
private notes and .release-check. Check Git history separately with --history before
pushing an existing repository. An ignored file can still exist in earlier commits.
No ZIP was created just by writing this handover.

For exact saved test evidence, method limits and detailed feature instructions,
read the documents below rather than guessing from chat history.

## 11. Documentation map

- README.md: public overview, dependencies and quick start.
- docs/setup-guide.md: installation/migration/troubleshooting on another machine.
- docs/accounts-and-roles.md: sign-in, approvals, permissions and recovery.
- docs/prediction-task.md: target, checkpoint meanings and missing-data policy.
- docs/recorded-replay.md: demonstration replay and chronology rules.
- docs/clinical-enhancements.md: clinical context, follow-ups and routed reviews.
- docs/workflow-upgrades.md: latest eight-feature workflow details and verification.
- docs/data-quality-and-evaluation.md: coverage, source/label limitations and evaluation.
- docs/calibrated-research-candidate.md: sigmoid calibration and saved candidate.
- docs/higher-recall-experiments.md: detection targets and survivor warning trade-offs.
- docs/model-improvement-comparison.md: candidate comparison/promotion criteria.
- docs/forest-tuning-experiment.md: focused Random Forest tuning study.
- docs/checkpoint-expansion.md: 9h/18h candidate and assessment policy.
- docs/separate-patient-evaluation.md: Set B provenance, results and limitations.
- docs/releasing.md: shareable source export and safe publication steps.
- data/raw/DATASET.md: public dataset attribution/provenance.

Some documents contain dated historical sections; read the latest sections and actual
source before assuming an older limitation still applies. No assistant has perfect
memory across chats. This handover plus the actual code is the continuity mechanism.
