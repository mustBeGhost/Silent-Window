"""Public source releases must be complete and exclude local secrets and accounts."""
import hashlib
import json
import zipfile
from pathlib import Path

from scripts.prepare_release import collect_files, export, included, local_secrets, secret_findings


def test_selection_excludes_private_and_generated_files():
    for path in (
        '.env', '.env.production', 'frontend/.env.local', 'frontend/.npmrc',
        'data/processed/runtime/accounts.sqlite3', 'data/processed/runtime/index.json',
        'backend/credentials.json', 'backend/signing.key', 'frontend/node_modules/a.js',
        'frontend/dist/assets/app.js', '.git/config', 'data/raw/Dataset 2.zip',
        'docs/images/old-real-account.jpg', 'ml/artifacts/unused_old_model.joblib',
    ):
        assert not included(Path(path)), path
    for path in (
        '.env.example', 'frontend/.env.example', 'frontend/package-lock.json',
        'frontend/src/App.jsx', 'tests/test_password_recovery.py',
        'data/raw/dataset_2/train/set-a/132539.txt',
        'ml/artifacts/expanded_rf_v4/rf_v4_9h.joblib',
        'ml/artifacts/logistic_12h.joblib',
    ):
        assert included(Path(path)), path


def test_local_connection_secret_is_detected_without_printing_it(tmp_path):
    password = 'fictional-' + 'release-test-secret'
    (tmp_path / '.env').write_text('DATABASE_URL=mysql+pymysql://app:' + password + '@localhost/db\n')
    secrets = local_secrets(tmp_path)
    findings = secret_findings('leaked: ' + password, 'README.md', secrets)
    assert findings
    assert all(password not in finding for finding in findings)
    assert secret_findings('leaked: ' + password, 'tests/example.py', secrets)


def test_credential_patterns_and_examples_are_distinguished():
    value = 'mysql+pymysql://app:' + 'real-password-value' + '@localhost/db'
    assert secret_findings(value, 'backend/settings.py', set())
    example = 'mysql+pymysql://YOUR_APP_USER:URL_ENCODED_PASSWORD@localhost/db'
    assert secret_findings(example, '.env.example', set()) == []
    assert secret_findings('-----BEGIN ' + 'PRIVATE KEY-----', 'README.md', set())
    assert secret_findings('ghp_' + 'a' * 36, 'README.md', set())
    assert secret_findings('password = ' + repr('real-value'), 'backend/settings.py', set())
    assert secret_findings("auth.setupRequired ? 'new-password' : 'current-password'", 'frontend/src/Login.jsx', set()) == []


def test_export_contains_only_selected_files_and_verified_manifest(tmp_path):
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'backend/main.py').write_text('value = 1\n')
    (tmp_path / 'README.md').write_text('Sample release\n')
    (tmp_path / '.env').write_text('secret=local-only\n')
    runtime = tmp_path / 'data/processed/runtime'
    runtime.mkdir(parents=True)
    (runtime / 'accounts.sqlite3').write_bytes(b'private accounts')
    files = collect_files(tmp_path)
    output = tmp_path / 'release.zip'
    export(tmp_path, files, output)
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert names == {'silent-window/README.md', 'silent-window/backend/main.py',
                         'silent-window/RELEASE_MANIFEST.json'}
        manifest = json.loads(archive.read('silent-window/RELEASE_MANIFEST.json'))
        for path, digest in manifest.items():
            assert hashlib.sha256(archive.read('silent-window/' + path)).hexdigest() == digest


def test_project_release_has_no_missing_models_or_private_paths():
    from scripts.prepare_release import ROOT, check
    files = collect_files(ROOT)
    assert check(ROOT, files) == []
