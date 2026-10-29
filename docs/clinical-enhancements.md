# Clinical context enhancements

These changes implement the ideas in the owner's `icu-clinical-enhancements.md`.
This remains a research demonstration with recorded public observations. There is
no hospital feed and no automatically generated diagnosis, prescription or care plan.

## Patient page

- Separate invasive systolic / diastolic / MAP and cuff systolic / diastolic / MAP.
- Other recorded readings: heart rate, respiratory rate, arterial oxygen saturation,
  temperature, GCS and creatinine. Every latest value shows its recorded time and age
  relative to the selected view. Gaps remain missing; negative sentinel values are
  excluded from this display without changing the frozen model preprocessing.
- Admission diagnosis, admission reason, current condition, admission severity,
  specialty and a responsible physician. Missing fields say "Not provided".
- Doctor visits, assessments and recommendations; follow-up, handover and escalation
  records. Each stores the author, role, save date, recorded minute, assessment,
  plan, follow-up, escalation context and optional next-review minute.
- A combined timeline of recorded measurements, model checkpoints, existing reviews,
  acknowledgements and the new staff records. Filters separate recorded and staff
  entries. It shows at most 100 events from the loaded history; the API explicitly
  reports truncation after 200 entries per staff record type.

Staff additions are labelled demonstration records, because the public dataset does
not contain these diagnoses or visit notes. They are not inputs to any saved model.
The timestamp on a staff note is its actual save date. The recorded minute is the
demonstration event's position after ICU admission. They are deliberately separate.

## Permissions

Individual patient access still requires an assigned doctor/nurse, or unit-management
access for an administrator/coordinator. Researchers cannot access these records.
Doctors, coordinators and administrators can add context revisions. The responsible
physician must be an active doctor already assigned to that patient. A removed,
disabled or role-changed doctor remains in historical context with a warning to update
the selection; it never grants patient access.

Only doctors can record visits, assessments, recommendations or vital warning limits.
Assigned nurses and coordinators can record follow-up, handover and escalation requests.
All writes use the existing CSRF and transaction-time role/assignment rechecks.

## Two different warnings

Existing mortality model scores, checkpoints and alert rules are unchanged.
Model-warning acknowledgement is shown per visible checkpoint and selected model.
Acknowledging does not clear the model alert or prove treatment occurred.

Vital warnings compare the latest available reading against doctor-entered demo
limits. No clinical default limits are provided. A missing rule means "not configured",
not "normal". A rule does not assess readings made before the rule's recorded start
time. An outside-limit result is not a mortality estimate or a verified critical alarm.
Limit edits and disabling rules append versions rather than deleting prior records.

Plain escalation notes remain notes. Dedicated doctor review requests provide in-app
notifications; My Shift adds recorded-time reminders and confirmed shift handovers.
There is no hospital paging integration, medication ordering or confirmation of care.

## Database and setup

Schema 4 added `patient_contexts`, `clinical_entries` and `vital_rule_versions`.
Schema 5 added `follow_up_events`; schema 6 added routed doctor review requests.
The current schema 7 also adds availability and confirmed shift handover history.
See `workflow-upgrades.md` for the latest staff instructions.
New installations create them during normal setup. Existing installations run:

```powershell
.venv\Scripts\python.exe -m scripts.migrate_accounts
```

The migration prompts privately for a MySQL administrator password, adds tables and
preserves existing users, passwords, sessions, assignments and notes. It is repeatable.
Application accounts retain their existing restricted permissions. No clinical sample
records are inserted into a real installation automatically.

## Where changes are saved

- `backend/routes/clinical.py`: data reads, validation, permissions and new writes.
- `backend/services/account_database.py`: new table definitions and schema version.
- `scripts/migrate_accounts.py`: additive upgrade for existing installations.
- `frontend/src/components/ClinicalWorkspace.jsx`: patient context, forms and timeline.
- `frontend/src/utils/clinical.js`: recorded-view validation and timeline preparation.
- `frontend/src/components/VitalChart.jsx`: extra readings and observation timestamps.
- `frontend/src/components/PatientWorkflow.jsx`: refresh after assignment/review changes.
- `frontend/src/pages/PatientDetails.jsx` and `frontend/src/index.css`: integration/layout.
- `tests/test_clinical.py`, `tests/test_account_migration.py` and
  `frontend/tests/clinical.test.mjs`: permissions, chronology and migration checks.

This document describes implementation, not a copy of the chat. The calibrated
research candidate document continues to describe only that model's methodology.

## Verification on 2026-10-15

- Full backend/model suite: 519 passed, including isolated MySQL integration tests.
- Final focused clinical and migration checks after the acknowledgement-history
  refinement: 33 passed across SQLite and MySQL test storage.
- Frontend suite: 75 passed. Production frontend build passed.
- Source-release checks passed with the saved research models and cohort intact.
- Browser checks used a separate, disposable database with fictional accounts:
  visit submission, staff timeline, separate vital warnings and replay cutoff hiding.
- Both existing local MySQL schemas were upgraded additively. Existing account,
  session, assignment and note rows were compared before/after and preserved.
- No new clinical demo entries were inserted into the actual project database.
- Changes remain local for owner review; they have not been uploaded to GitHub.

## Laptop layout and follow-up tracking (2026-10-17)

The patient page now has section links for risk overview, clinical context,
follow-ups, vitals, warning review, team/notes and timeline. Model trajectory and
alert explanations remain close to the score. The clinical section includes a
compact responsible-doctor/team summary, a dedicated follow-up list, three-column
blood-pressure cards at laptop widths and separate vital/model warning panels.

A clinical entry becomes a tracked follow-up when it has follow-up actions, a next
review time, or the follow-up entry type. Existing entries are included without
rewriting them. Actions start pending. Assigned doctors/nurses and coordinators
can mark an action completed or reopen it with an explanation; administrators can
view the status. Each change records staff identity, role, recorded patient minute
and actual save date. Completing a follow-up never acknowledges or clears an alert.

In the Follow-ups panel, select Pending, Completed or All follow-ups. Open Mark
completed, enter the recorded minute and what was completed, then save. Completed
items show the staff member and both timestamps. Reopen follow-up appends another
status change with a reason. Old changes remain in the patient timeline. Conflicting
updates return a refresh message rather than overwriting another staff member.

Pending review times are compared with the selected recorded view, not today's wall
clock. Later completions/reopenings stay hidden in earlier replay views. A status
cannot be recorded before its entry or previous change. There is no reminder or
notification scheduler in this stage. The list loads up to 200 actions, pending
first, and the API reports total pending/completed/overdue counts separately.

New code: `backend/services/follow_ups.py`, `frontend/src/components/FollowUps.jsx`
and `tests/test_follow_ups.py`. Schema-1 through schema-4 installations use the
same additive migration command above to reach schema 5.

Verification: 463 backend/model checks passed with 71 MySQL-related cases excluded
to preserve the user's starter test accounts. MySQL follow-up queries were verified
with temporary transaction data and rolled back. All 76 frontend checks and the
production build passed. Browser checks used fictional accounts in isolated storage
at a 1366×900 laptop viewport, covering completion, reopening and replay chronology.
Both real schemas were upgraded with all existing table rows preserved. These
changes remain local and have not been uploaded to GitHub.


## Doctor review requests (2026-10-18)

A dedicated Doctor review requests panel now routes explicit staff requests to
currently assigned doctors. Assigned nurses/doctors and coordinators can request
review. Administrators can read requests; researchers cannot access patient details.
Legacy escalation notes stay as notes and are not automatically routed.

Requests move from Pending to Acknowledged to Resolved. Only a currently assigned,
active doctor can acknowledge or resolve them. Staff can reopen resolved requests
with an explanation. Each action appends its author, role, recorded patient minute
and actual save date. Conflicting updates ask for a refresh; changes cannot be
backdated before the request or its latest status change. Resolving a request does
not clear model alerts, vital warnings or follow-ups, and does not prove treatment.

The Review Requests inbox supports status filters and 25-row pages. Doctors and
nurses see their currently assigned patients; administrators and coordinators see
the unit. The inbox uses the complete recorded 24-hour view. Patient replay views
hide requests and status changes entered at later recorded minutes.

A sidebar badge shows open requests. Doctors receive an in-app popup for unseen
pending requests; notifications refresh every 30 seconds while the page is visible,
on focus and after local request actions. Dismissal is remembered per account in
session storage. Newly assigned older requests and reopened requests have distinct
notification identities. Notifications are not email, SMS, push or a delivery receipt.
The latest 100 pending notification identities are checked; use the inbox for all
requests. Requests without an active assigned doctor remain saved and visibly wait
for an assignment. Current assignments determine who can see and act on them.

Schema 6 adds doctor_review_requests and doctor_review_events. The additive
migration supports schema 1 through 5 and preserves existing records. Both local
project schemas were migrated with every pre-existing table row compared before
and after. No fictional clinical records were added to the user's project database.
MySQL query verification used the test schema and rolled back every inserted row.

Implementation: backend/services/doctor_reviews.py, backend/routes/clinical.py,
frontend/src/components/DoctorReviews.jsx, frontend/src/pages/ReviewRequests.jsx,
frontend/src/context/DoctorReviewNotifications.jsx and frontend/src/utils/doctorReviews.js.
The clinical timeline, patient section links, sidebar and application routes include
this workflow. tests/test_doctor_reviews.py covers permissions, unassigned/newly
assigned requests, status transitions, stale updates, replay and model independence.

Verification: 468 distinct backend/model checks passed across the full regression
run and a focused rerun with process access (three model-thread checks hit sandbox
restrictions on the first run). 75 MySQL-parametrized destructive fixture cases
were excluded to preserve the five starter test accounts. Browser verification
used isolated fictional accounts for the popup, inbox, acknowledgement and
resolution, nurse creation and reopening. All 80 frontend checks passed; the
production build passed. All changes
remain local for owner review and have not been uploaded to GitHub.
