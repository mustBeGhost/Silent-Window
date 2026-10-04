# Accounts, roles and MySQL storage

Silent Window has sign-in and five server-enforced roles. Its account and
workflow data use the installer's MySQL 8 server, normally at
`127.0.0.1:3306`. The project schema is `silent_window`. Recorded patient files
and saved prediction models stay in their existing folders.

## The five roles

- **Administrator:** approves or rejects worker requests, changes or disables access, sees
  the full patient queue, and assigns doctors and nurses to patients.
- **Doctor:** sees assigned patients, writes doctor review notes and acknowledges
  warnings. Cannot change assignments or manage accounts.
- **Nurse:** sees assigned patients, writes observation notes and acknowledges
  warnings. Cannot submit a doctor review or manage accounts.
- **ICU Coordinator / Head Nurse:** sees the full queue, manages assignments,
  writes handover notes and acknowledges warnings. Cannot create accounts.
- **Researcher / Reviewer:** sees aggregate model comparisons and their own
  account preferences. Cannot access individual patient endpoints or notes.

Every role can save a display name, preferred model, patients per page and
default replay speed. The original model remains the default until a user saves
a different preference. Preferences apply only to that user's account.

## First use

1. Start your MySQL service, complete setup and run `run_silent_window.bat`.
2. Open the website and create your first administrator account. Choose your
   own passphrase with at least 15 characters. There is no default website login.
3. Workers open **Request an account** on the sign-in page, choose a requested
   role and submit their details. Open **Account Requests** to review them.
4. Open a patient page and assign the responsible doctor and nurse. A coordinator
   can also manage those assignments after signing in.
5. Doctors and nurses then see only their assigned patient records. An empty
   queue explains that an administrator or coordinator must assign patients.

The MySQL database password and a user's website password are different credentials.
The setup command uses MySQL administrator access once to create the project
schema and restricted database accounts. It does not save the MySQL administrator
password or run the application as root.

## Connect with MySQL Workbench

Use the Workbench connection for your MySQL server. Refresh **SCHEMAS** and
expand `silent_window`, then **Tables**. No extra server connection is required.

```sql
USE silent_window;
SHOW TABLES;
SELECT id, username, display_name, role, active FROM users;
```

The ten tables are `users`, `permission`, `password_resets`, `sessions`, `attempts`,
`account_events`, `assignments`, `patient_events`, `schema_version` and `auth_write_lock`.
The separate `silent_window_auth_test` schema is used only for integration tests.

## Notes and acknowledgements

Entries are saved with their author, role, time, model version, checkpoint,
score and alert state. They do not alter readings, model inputs or alert rules.
An acknowledgement records that someone saw a warning. It does not clear that
warning or prove that care was given. Notes from later checkpoints are hidden
when viewing an earlier recorded time, and histories are separate by model.
The visible history shows the latest 200 entries for that model and time.

## Database setup on a fresh installation

Install the requirements and provision an existing MySQL server. On a fresh
server, run the following once from the repository folder:

```powershell
.venv\Scripts\python.exe -m scripts.configure_mysql --host 127.0.0.1 --port 3306 --username root
```

Enter the administrator password in the local terminal prompt. Setup refuses
to overwrite schemas that already have tables or change a pre-existing account
with the same name. It creates the project and isolated test schemas, initializes
schema version 3, and gives the app/test accounts only SELECT, INSERT, UPDATE
and DELETE privileges on their respective schemas. They cannot create tables.

The generated connection URLs are stored in an ignored `.env` file. Use
`.env.example` as a template for other environments. Startup checks the
configured MySQL server; it does not create or start a separate MySQL instance.
Future schema changes require an explicit migration rather than app DDL access.

```powershell
.venv\Scripts\python.exe -m scripts.check_database
```

## Authentication and storage checks

Passwords use Argon2id hashes; sessions use random HttpOnly, SameSite=Strict
cookies, with only token hashes stored in MySQL. Writes need a session-derived
CSRF token and a trusted local origin. Sessions expire after 30 minutes without
API activity or eight hours total. Changing a role or disabling an account
revokes existing sessions. The last active administrator is protected.

SQL values are bound parameters. Connections use SQLAlchemy pooling and short
transactions. Access-changing transactions use an InnoDB row lock, including
first setup and last-administrator checks. Database connection errors return
a safe service-unavailable message without SQL or credentials.

New tests cover actual cookie sign-in, all five roles, direct endpoint denial,
assignment changes, saved preferences, note snapshots, historical filters,
session limits, expiry, login rate limits, setup races, MySQL privileges and safe
connection failure. The role tests run against both isolated SQLite stores and
the dedicated MySQL test schema; the website uses MySQL.

```powershell
.venv\Scripts\python.exe -m pytest tests\test_auth.py tests\test_mysql_storage.py tests\test_assigned_patients.py -q
```

The MySQL test URL must end in `_auth_test`; tests refuse to clear other schemas.
Local credentials, databases and session data are excluded from Git. They should
not appear in screenshots, portfolio uploads or source control.

This is local research access control. Public hosting still needs its own HTTPS,
trusted hosts/origins, secret management, backups and a reviewed identity-verification
and notification process for account recovery.
Login and roles do not establish clinical readiness.

Design references: [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
[OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[SQLAlchemy engines](https://docs.sqlalchemy.org/en/20/core/engines.html).

## Username and password fields

New usernames use 3–32 characters, start with a lowercase letter, and contain lowercase letters and optional numbers only. `admin` and `admin12` are valid; `1admin`, uppercase letters, spaces, and symbols are rejected in both the form and the API. Existing usernames still work at sign-in.

The worker request form warns next to a username that already exists, including inactive accounts, or already has a pending request. The server checks both tables inside a serialized transaction so concurrent submissions cannot reserve the same username. Failed submissions keep the entered form values. Successful submissions remove the password fields from the page.

Setup, sign-in, and worker signup have separate eye buttons for each password field. Passwords start hidden; the buttons show or hide what the user typed without submitting the form. The existing 15-character minimum for new passwords remains.

## Worker requests and approval

Workers use `/register` without signing in, after the first administrator has set up the workspace. They choose doctor, nurse, coordinator or researcher; public requests cannot ask for administrator access. Name, username, requested role, optional staff details and an Argon2id password hash are stored in `permission`, with status `pending`. No user or session is created at signup.

Only an active administrator can list requests or review them. The review page has pending, approved and rejected views, 50 requests per page, and refresh controls. The administrator verifies staff details outside the software, chooses the final granted role and approves or rejects. The website does not itself verify employment or professional qualifications.

Approval inserts a user with the worker's chosen password hash and administrator-granted role, then marks the request approved in the same transaction. Rejection marks the request rejected without inserting a user. Both decisions record the administrator, time and optional review note. The password hash is cleared from the permission row after either decision; it is never returned by request APIs. Simultaneous decisions have one winner; repeat decisions return a conflict.

Rejected workers can submit a new request, preserving the previous decision in history. Existing user accounts, including disabled ones, continue to reserve their usernames. Pending and rejected workers cannot sign in or access protected data. Approved doctors and nurses still require patient assignments. **Team Accounts** manages approved accounts; the old direct-creation API is closed.

For an existing version-1 or version-2 database, run this additive migration with MySQL administrator access:

```powershell
.venv\Scripts\python.exe -m scripts.migrate_accounts --host 127.0.0.1 --port 3306 --username root
```

It adds missing `permission` and `password_resets` tables to the project and
isolated test schemas, then advances the schema version to 3. Existing users,
passwords, sessions, assignments and patient notes are preserved. It can be run
again safely and never saves the administrator password.

## Request notifications and patient team editing

Administrators receive an in-app popup for pending requests they have not yet seen.
It offers **View requests** and **Dismiss**. A count appears beside **Account Requests**.
The website checks every 30 seconds while visible and when brought back into focus.
Approving or rejecting refreshes the count immediately. A dismissed popup does not
repeat for the same request in that browser tab's session; a newer request does.
Notifications require the website to be open and the administrator signed in.
They are account-request notifications, separate from patient model warnings.

Approved and rejected histories use compact rows, showing name, username,
requested role, granted role and decision date. Extra details stay closed until
**View details** is clicked.

Each patient has separate **Doctors** and **Nurses** sections, with assigned
counts. Open a section to see its team. Administrators and coordinators can
**Edit**, search approved active staff, select multiple people, and **Save** or
**Cancel**. Up to 20 people can be selected per group. Doctors and nurses can
view their assigned patient's team but cannot edit it. Inactive assignments
remain visible with a label; inactive staff cannot be newly selected.

Group saves use a role-specific transaction. Updating doctors preserves nurses,
including simultaneous edits, and vice versa. Clearing a group removes only that
group's assignments. Removing a clinician's assignment removes their access to
that patient. These controls do not alter recorded measurements or model scores.

## Password change and administrator-assisted recovery

To change your own password, open **My Account**, enter the current password,
then a different new password twice. New passwords still need 15–128 characters.
All sessions for that account end after a successful change, including the
current session. Sign in again. A wrong current password leaves the session and
existing password intact.

If a worker forgets their password:

1. Verify the person's identity outside the app. A username alone is not proof.
2. In **Team Accounts**, open **Password recovery for [username]**.
3. Confirm the identity check and enter your own administrator password.
4. Give the generated code privately to the verified account owner. Do not put
   it in a patient note, screenshot, shared document or public message.
5. The account owner signs out if needed, opens **Forgot your password?** on
   the sign-in page, and enters their username, code and a new password twice.
6. The owner signs in normally with the new password. Existing sessions and
   recovery codes for the account have ended.

Codes are random, valid for 15 minutes and usable once. Only their SHA-256 hashes
are stored in `password_resets`. Issuing a replacement invalidates the old code;
issuing a code does not change the password or end sessions by itself. Disabled
accounts cannot receive or redeem codes. Role/access changes invalidate outstanding
codes. Admin recovery writes require CSRF, a trusted origin and current-password
confirmation. Reset attempts are rate limited. Audit events store the action,
actor, target and time, never the code or password. Codes stay in page memory,
not browser storage or URLs. There is no email service; private delivery and
identity verification are the administrator's responsibility.

If the only website administrator cannot sign in, the person managing the local
MySQL server can issue a code using MySQL administrator access:

```powershell
.venv\Scripts\python.exe -m scripts.recover_account --account YOUR_WEBSITE_USERNAME
```

This asks for identity confirmation and the MySQL administrator password in the
local terminal. It requires permission to read `mysql.user`; the restricted app
account cannot use it. It issues a code for an existing active account, without
changing its role, enabling it, creating a replacement administrator or storing
the MySQL administrator password. Enter the code at `/recover`. The server stays
on port 3306. This recovery command is never run automatically during setup.

The token lifecycle follows [OWASP recovery guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).
