# Workflow upgrades

Work requested: shift dashboard, confirmed shift handover, recorded-time follow-up
reminders, staff availability, patient PDF export, searchable history, immediate
website updates and additional model evaluation. Publication was approved by the owner on 2026-10-30.

This document records implementation and verification as work is completed. The
application continues to use recorded public ICU data and staff demonstration notes.
Availability uses actual save time; patient actions and reminders use recorded time.
Models and existing outcome labels are not changed by staff workflow additions.

## Staff instructions

Open My Shift in the sidebar. It combines your assigned patients, follow-ups,
doctor review requests, the loaded patient page's warnings and incoming/outgoing
handovers. Administrators and coordinators see a unit overview. Researchers remain
restricted to aggregate research results. Warning checks cover the displayed
25-patient page; task and request counts cover the full authorized scope.

Choose the recorded minute to review earlier work. A planned follow-up becomes due
at its scheduled minute and overdue afterward. Future plans and status changes are
hidden. Reminders are highlights inside the website, not an unattended scheduler,
email, SMS or a clinical alarm. The patient page and PDF links preserve this cutoff.

Set your own availability to On duty, Off duty or Unavailable. A note and save date
are kept. Availability is self-reported in actual time; it is not derived from patient
replay or assumed from logging in. New accounts start Not set. Off-duty/unavailable
doctors retain authorized patient access but receive no new doctor-review popups.
My Shift shows each loaded patient's assigned staff availability and highlights
patients with no doctor who has confirmed On duty. Not set is shown explicitly.

To hand over, open a patient's Shift handover section and choose another active
person in the same doctor/nurse role. Coordinators may offer on behalf of an assigned
staff member; administrators can view. The offer contains a summary and up to 200
pending follow-ups at the recorded handover minute, with an explicit truncation flag.
The receiving person sees the offer in My Shift but has no full patient access yet.
They must set On duty and accept. Acceptance atomically removes only the sending
assignment and adds the receiver; other doctors/nurses stay assigned. The recipient
can decline, and the sender/coordinator can cancel. Concurrent or stale actions
cannot overwrite a completed transfer. Existing assignments are rechecked. Current
access changes immediately; replay never restores former patient permissions.

## History and PDF

Search staff history on the patient page. It searches past the short timeline's
limits, with text/staff-name, entry-type, author, recorded-minute and actual save-date
filters. Results are paginated in groups of 25. Model checkpoint notes, clinical
entries, context revisions, warning limits, follow-up/review status changes and shift
handover records are included. Search text uses bound parameters and literal wildcard
escaping. Future actions and parent records remain hidden at earlier cutoffs.

Download research PDF exports only the current recorded view and selected model.
It contains admission context, team, latest vital values with units/times/age, model
assessments, vital warnings, model acknowledgements, follow-ups, review requests and
recent staff notes. Each staff list is limited to 30 entries and the limit is printed.
PDFs are generated in memory, permission-checked before returning and never saved
on the server. The layout supports long notes and repeated table headers/page numbers.
Unsupported font glyphs are retained as U+ codes rather than silently omitted.
The export is prominently labelled as a research demonstration. It is not a clinical
care document and does not turn staff demonstration notes into original patient facts.

## Immediate updates

Authenticated Server-Sent Events send only a scoped revision hash, not patient data.
The server checks authorized database revisions approximately once per second and
refreshes only the user's permitted views through existing APIs. Assignments,
clinical actions, handovers, availability and administrator account requests update
without a normal 30-second wait. Roles, active accounts, sessions and Origin are
checked. Streams close on hidden pages/logout and reconnect when visible. Late
frames cannot restore a closed connection. Review/account notification polling stays
as a fallback when the stream is unavailable. This is live website synchronization,
not a live hospital-data connection or a guaranteed alarm-delivery service.

## Storage, setup and verification

Schema 7 adds availability_events, handovers and handover_events. Existing installs
run python -m scripts.migrate_accounts; fresh installs create the tables normally.
Both local schemas were upgraded additively, comparing all existing table rows before
and after. Website accounts, passwords, notes and assignments were preserved.
ReportLab 4.5.1 is a pinned runtime dependency; reinstall requirements when upgrading.

The full backend/model regression run passed 478 checks with destructive MySQL
fixtures excluded. Seven additional evaluation/cohort checks passed. New workflow
checks cover simultaneous handover confirmation, stale updates, role restrictions,
recorded-time reminders, history beyond 200 entries, PDF access/cutoffs and scoped
stream revisions. Separate MySQL verification exercised the new queries in a rolled-
back transaction; all original rows were preserved. Frontend checks cover stream
cleanup, late frames, handover controls and explicit model-result denominators.
Browser checks use fictional staff and notes in isolated storage. PDF pages were
rendered and visually inspected. No new demo records were added to the user's app.
For final publication checks see release-verification.md.

See separate-patient-evaluation.md for the eighth improvement: fixed-model testing
and missed-case analysis on 4,000 additional public patients.
