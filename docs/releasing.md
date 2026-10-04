# Preparing a GitHub release

The repository is a runnable source project. A download contains source code,
tests, saved models, the attributed public research cohort, pinned dependencies
and setup instructions. Each user supplies their own MySQL server and creates
their own administrator; there are no shared credentials or preloaded workers.

## Before publishing

Run from the project root:

```powershell
python -m scripts.prepare_release --history
.venv\Scripts\python.exe -m scripts.check_installation
cd frontend
npm test
npm run build
cd ..
python -m scripts.prepare_release --zip dist/silent-window-source.zip
```

The release checker selects project files explicitly, checks local secret
values and common credential patterns without printing them, checks required
files and saved-model hashes, and verifies the completed ZIP. `--history` also
checks reachable Git text objects and private filenames. These checks reduce
accidental exposure; they do not prove the absence of every possible secret.
If a check finds a real leaked credential, remove it and revoke it before
publishing. Ignoring a tracked file alone does not remove it from Git history.

The ZIP excludes `.git`, `.env`, database dumps, account databases, runtime
files, caches, installed dependencies and build outputs. It also omits old design
exports. It preserves the 11 saved runtime models, their three manifests, and
three historical Logistic Regression models required by the research checks.
`RELEASE_MANIFEST.json` records SHA-256 hashes
for every selected source file. Existing ZIPs are never overwritten.

For a fresh GitHub repository, extract this clean archive and upload the
contents of its `silent-window` folder. Do not upload the outer local workspace,
virtual environment or a database backup. The tool does not create a repository,
commit, push or change the existing Git history.
The included Windows GitHub Actions workflow runs on pushes and pull requests
with read-only repository access. It has no deployment or database credentials.
Its remote run can be verified only after the project is published.

Use `Silent Window` as the project name and describe it as an ICU mortality-risk
research dashboard. Retain dataset attribution and model limitations.
No application software license is included,
at the project owner's request. A public GitHub repository alone does not grant
general permission to reuse or redistribute the application code. The dataset
retains its existing ODC attribution license; dependencies retain their own
licenses.

## Verify a download

Extract the ZIP into a new folder. Follow README.md rather than copying the
developer's `.env`. Install packages, provision fresh MySQL storage and create
your own admin account. Run the installation checker. The first launch should
show workspace setup, with no accounts, assignments or staff notes copied from
another installation. The dataset and models are bundled; no model training or
paid API access is needed to open the demonstration.

The supported, verified installation is Windows with Python 3.11, Node.js 22+
and MySQL 8. Manual macOS/Linux commands are included in the setup guide.
