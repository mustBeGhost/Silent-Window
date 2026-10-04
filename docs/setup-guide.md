# Install and run Silent Window

This guide is for the local research website. Setup uses your existing MySQL
server. It does not install another database server, create default website
passwords, retrain models, or publish the project.

## Required software and project files

- Python 3.11 is the tested version; Python 3.11 or newer is required.
- Node.js 22 or newer, with npm. The tested local version is 22.11.0.
- MySQL 8, running on `127.0.0.1:3306`. MySQL Workbench is optional.
- All recorded patient files in `data/raw/dataset_2/train/set-a/` and
  `data/raw/dataset_2/train/Outcomes-train.txt`.
- The original models and `rf_v2_manifest.json` in `ml/artifacts/`.
- V3 models and manifest in `ml/artifacts/calibrated_rf_v3/`.
- V4 models and manifest in `ml/artifacts/expanded_rf_v4/`.
- The saved processed metadata and frontend result JSON files supplied with
  this project. Do not substitute another patient dataset with the same filenames.

The project download includes the extracted frozen cohort and saved models.
There is no separate dataset ZIP to extract. If files are missing, restore them
from the same trusted project download. A fresh download of all 4,000 source
records is not an interchangeable replacement for this 3,200-record cohort.
See [dataset attribution](../data/raw/DATASET.md). Never load model files from
an untrusted source: saved Python models are executable artifacts.

## Guided Windows installation

1. Open PowerShell inside the project folder.
2. Stop any running Silent Window backend/frontend servers. The installer refuses
   to replace packages while ports 8001 or 5173 are listening.
3. Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_silent_window.ps1 -WithTests
```

The execution-policy option applies only to this invocation. It does not change
your permanent PowerShell policy. The script creates `.venv` only when missing,
installs the pinned requirements, runs `npm ci`, checks data/model files, and
checks the database. Fresh MySQL setup prompts for the MySQL administrator
password locally. If a database already contains tables, setup stops instead of
overwriting them. Use the migration below for an existing older database.

The installer needs package-registry access. If your terminal has offline pip
mode enabled, run it from a normal terminal with access to your approved package
registry, or supply an approved wheel folder. Do not change model package pins
just to work around an offline installation.

## Manual installation

From the project folder:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -c requirements-lock.txt
cd frontend
npm ci
cd ..
.venv\Scripts\python.exe -m scripts.check_installation --skip-database
```

`requirements.txt` is sufficient to run the website. `requirements-dev.txt`
adds testing tools. `requirements-research.txt` adds plotting tools for the
existing analysis scripts. The website does not require Jupyter or Windows-only
notebook packages. Use the same pinned package versions as the saved models.

The constraints in `requirements-lock.txt` capture the transitive versions from
the tested fresh Python 3.11 installation. Use that file with the chosen
requirements file for repeatable installation. Node dependencies are installed
from the existing `frontend/package-lock.json` with `npm ci`.

## MySQL: fresh setup versus existing setup

On a fresh installation, start MySQL and run once:

```powershell
.venv\Scripts\python.exe -m scripts.configure_mysql --host 127.0.0.1 --port 3306 --username root
```

The command creates `silent_window`, the isolated `silent_window_auth_test`
schema, and restricted database accounts. It saves only restricted account
connection URLs in an ignored `.env` file. The website does not run as root.
Other schemas on the server are untouched. Do not copy `.env` into GitHub.

For an existing version-1 or version-2 database, stop the backend, then run:

```powershell
.venv\Scripts\python.exe -m scripts.migrate_accounts --host 127.0.0.1 --port 3306 --username root
```

This adds missing approval/recovery tables and advances to schema 3. Existing
accounts, passwords, sessions, assignments and notes are preserved. Restart the
backend afterward. Fresh installations already use the current schema.

If restoring an existing database, restore its restricted account configuration
too. A missing `.env` is not a reason to rerun fresh setup over existing tables.
Use `.env.example` for the expected configuration keys and ask the MySQL operator
to supply the matching restricted account credentials.

## Start and check

```powershell
.venv\Scripts\python.exe -m scripts.check_installation
.\run_silent_window.bat
```

The preflight verifies pinned dependencies, frontend installation, model integrity
and the configured database before the launcher starts either server. The
backend runs on 8001; open `http://127.0.0.1:5173/` for the website. The launcher
opens separate server windows; Ctrl+C stops each server.

The frontend requests `/api` on the same website origin. Keep
`frontend/.env.example`'s API override blank for this local setup. Vite forwards
those requests to 8001. Avoid mixing `localhost` and `127.0.0.1` while testing a
session; they have separate cookies.

For first use, create your own administrator in the browser. On an existing
installation, sign in normally; setup never replaces your account. Workers
request accounts, administrators approve them, and clinicians receive patient
assignments. See [accounts and recovery](accounts-and-roles.md).

## Verify the installation

```powershell
.venv\Scripts\python.exe -m pytest tests -q
cd frontend
npm test
npm run build
```

Tests do not change the deployed model files. MySQL integration tests use only
`SILENT_WINDOW_TEST_DATABASE_URL`, whose schema must end in `_auth_test`. They
clear sample rows in that isolated schema. Never point it at `silent_window`.
Without that test URL, MySQL integration cases are skipped and SQLite cases
still run. The running website itself requires MySQL and has no SQLite fallback.

## Common problems

- Missing packages or version mismatch: install the appropriate requirements
  using `.venv\Scripts\python.exe`, then rerun the preflight.
- Missing models or integrity failure: restore the trusted model bundle and its
  matching manifest. Starting the app never retrains a replacement.
- Missing or wrong patient files: restore this project's recorded cohort into
  the exact layout above. The app does not accept arbitrary uploads.
- MySQL unavailable: check your MySQL service, port 3306, schema version and
  restricted credentials in `.env`.
- Existing database rejected by fresh setup: use the migration or restore the
  correct restricted connection, rather than deleting tables.
- Ports in use: stop the old project servers before starting another copy.
- Forgotten website password: use administrator-assisted recovery; the website
  password is separate from the MySQL administrator password.

An online deployment is a later stage. The Vite preview server and this local
launcher are not a production hospital hosting setup.

## Manual setup on macOS or Linux

The guided launcher is for Windows. On macOS/Linux, install Python 3.11,
Node.js 22+ and MySQL 8, start MySQL, then run from the extracted project folder:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -c requirements-lock.txt
cd frontend
npm ci
cd ..
.venv/bin/python -m scripts.check_installation --skip-database
.venv/bin/python -m scripts.configure_mysql --host 127.0.0.1 --port 3306 --username root
.venv/bin/python -m scripts.check_installation
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

In a second terminal, from the project folder:

```sh
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173/` and create your own administrator. Stop each server
with Ctrl+C. These manual commands use the same Python source and pinned
dependencies; the full installation verification was performed on Windows.
