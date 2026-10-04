"""Check or export a clean source release, without changing Git or local accounts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    '.env.example', '.gitignore', '.gitattributes', 'README.md',
    'requirements.txt', 'requirements-dev.txt', 'requirements-lock.txt',
    'requirements-research.txt', 'run_silent_window.bat', 'setup_silent_window.ps1',
}
SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__',
             '.pytest_cache', 'dist', 'build', '.ipynb_checkpoints', '.setup-check-venv', '.release-check'}
TEXT_SUFFIXES = {'.py', '.js', '.jsx', '.mjs', '.css', '.html', '.json', '.md',
                 '.txt', '.csv', '.bat', '.ps1', '.yml'}
MODEL_FILES = {
    'ml/artifacts/rf_v2_manifest.json',
    *(f'ml/artifacts/rf_v2_{h}h.joblib' for h in (6, 12, 24)),
    'ml/artifacts/calibrated_rf_v3/calibrated_rf_v3_manifest.json',
    *(f'ml/artifacts/calibrated_rf_v3/rf_v3_{h}h.joblib' for h in (6, 12, 24)),
    'ml/artifacts/expanded_rf_v4/expanded_rf_v4_manifest.json',
    *(f'ml/artifacts/expanded_rf_v4/rf_v4_{h}h.joblib' for h in (6, 9, 12, 18, 24)),
}
RESEARCH_MODEL_FILES = {f'ml/artifacts/logistic_{h}h.joblib' for h in (6, 12, 24)}
REQUIRED = ROOT_FILES - {'.gitattributes'} | MODEL_FILES | RESEARCH_MODEL_FILES | {
    'backend/main.py', 'frontend/package.json', 'frontend/package-lock.json',
    'frontend/index.html', 'frontend/.env.example', 'docs/setup-guide.md',
    'data/raw/dataset_2/train/Outcomes-train.txt', 'data/raw/DATASET.md',
    'data/processed/baseline/split_metadata.json',
    '.github/workflows/checks.yml',
}
TOKEN_RULES = (
    ('private key', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')),
    ('AWS access key', re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b')),
    ('GitHub token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b')),
    ('service API key', re.compile(r'\b(?:sk-(?:proj-|live-)?[A-Za-z0-9_-]{24,}|AIza[A-Za-z0-9_-]{35}|xox[baprs]-[A-Za-z0-9-]{20,})\b')),
)
URL_CREDENTIAL = re.compile(r'\b(?:mysql(?:\+pymysql)?|postgres(?:ql)?|mongodb(?:\+srv)?|https?)://[^\s\"\'<>]+')
LITERAL_SECRET = re.compile(r'(?<![\w-])(?:password|api_key|api_secret|secret_key|access_token|client_secret)\b[\"\']?\s*[:=]\s*[\"\']([^\"\'\n]{4,})[\"\']', re.IGNORECASE)
PLACEHOLDERS = {'URL_ENCODED_PASSWORD', 'YOUR_PASSWORD', 'PASSWORD', 'example',
                'test', 'password', 'secret', 'pass', 'pw'}


def included(path: Path) -> bool:
    """Only deliberately selected project files can enter a public release."""
    name = path.as_posix()
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.name.startswith('.env'):
        return name in {'.env.example', 'frontend/.env.example'}
    if len(path.parts) == 1:
        return name in ROOT_FILES
    if name in MODEL_FILES or name in RESEARCH_MODEL_FILES:
        return True
    if name == '.github/workflows/checks.yml':
        return True
    if path.parts[0] in {'backend', 'ml', 'scripts', 'tests'}:
        return path.suffix == '.py'
    if path.parts[0] == 'frontend':
        return path.suffix in {'.js', '.jsx', '.mjs', '.css', '.html', '.json'}
    if path.parts[0] == 'docs':
        return path.suffix == '.md' or name == 'docs/images/account-security-preview.jpg'
    if name == 'data/raw/DATASET.md':
        return True
    if name.startswith('data/raw/dataset_2/train/'):
        return name == 'data/raw/dataset_2/train/Outcomes-train.txt' or (
            path.parent.as_posix() == 'data/raw/dataset_2/train/set-a'
            and re.fullmatch(r'\d+\.txt', path.name) is not None)
    if name.startswith('data/processed/'):
        return len(path.parts) >= 3 and path.parts[2] != 'runtime' and (
            path.suffix in {'.txt', '.json', '.csv', '.png'}
            and path.name != 'checkpoint_coverage.csv')
    return False


def collect_files(root: Path) -> list[Path]:
    files = []
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in names:
            path = Path(base) / name
            relative = path.relative_to(root)
            if included(relative):
                if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                    raise ValueError(f'Release cannot include a linked file: {relative.as_posix()}')
                files.append(relative)
    return sorted(files)


def local_secrets(root: Path) -> set[str]:
    """Read local values only for comparison; never return them in reports."""
    secrets = set()
    for folder in (root, root / 'frontend'):
        for path in folder.glob('.env*'):
            if not path.is_file() or path.name == '.env.example':
                continue
            for line in path.read_text(encoding='utf-8').splitlines():
                if '=' not in line or line.lstrip().startswith('#'):
                    continue
                key, value = line.split('=', 1)
                value = value.strip().strip('\"\'')
                if len(value) >= 8:
                    secrets.add(value)
                if '://' in value:
                    try:
                        password = urlsplit(value).password
                        if password and len(password) >= 8:
                            secrets.update({password, unquote(password)})
                    except ValueError:
                        pass
                elif any(word in key.lower() for word in ('password', 'secret', 'token', 'api_key')) and value:
                    secrets.add(value)
    return secrets


def secret_findings(content: str, path: str, secrets: set[str]) -> list[str]:
    findings = []
    if any(secret in content for secret in secrets):
        findings.append(f'{path}: contains a local secret value')
    for label, pattern in TOKEN_RULES:
        if pattern.search(content):
            findings.append(f'{path}: possible {label}')
    # Test URLs are fictional fixtures; actual local secrets above are still checked.
    if not path.startswith(('tests/', 'frontend/tests/')):
        for match in LITERAL_SECRET.finditer(content):
            if match.group(1) not in PLACEHOLDERS and not match.group(1).startswith(('YOUR_', 'EXAMPLE_', 'PLACEHOLDER')):
                findings.append(f'{path}: possible hardcoded credential')
                break
        for match in URL_CREDENTIAL.finditer(content):
            try:
                password = urlsplit(match.group()).password
                if password and unquote(password) not in PLACEHOLDERS:
                    findings.append(f'{path}: embedded connection credentials')
                    break
            except ValueError:
                findings.append(f'{path}: malformed credential URL needs review')
                break
    return findings


def check(root: Path, files: list[Path]) -> list[str]:
    names = {p.as_posix() for p in files}
    findings = [f'Missing required file: {p}' for p in sorted(REQUIRED - names)]
    if sum(p.parent.as_posix() == 'data/raw/dataset_2/train/set-a' for p in files) != 3200:
        findings.append('The release must contain the frozen 3,200-record cohort.')
    secrets = local_secrets(root)
    for path in files:
        content = (root / path).read_bytes()
        if len(content) >= 95 * 1024 * 1024:
            findings.append(f'{path.as_posix()}: file too large for the source release')
        if path.suffix in TEXT_SUFFIXES or path.name in {'.env.example', '.gitignore', '.gitattributes'}:
            try:
                text = content.decode('utf-8')
            except UnicodeDecodeError:
                findings.append(f'{path.as_posix()}: text must use UTF-8')
                continue
            findings.extend(secret_findings(text, path.as_posix(), secrets))
    # The runtime's artifact loader performs the deeper model checks.
    for manifest_name in sorted(p for p in MODEL_FILES if p.endswith('.json')):
        if manifest_name not in names:
            continue
        manifest = json.loads((root / manifest_name).read_text(encoding='utf-8'))
        for artifact in manifest['artifacts'].values():
            path = Path(manifest_name).parent / artifact['filename']
            if path.as_posix() not in names or hashlib.sha256((root / path).read_bytes()).hexdigest() != artifact['sha256']:
                findings.append(f'{path.as_posix()}: saved model integrity mismatch')
        for group in ('source_sha256', 'evaluation_evidence_sha256', 'protected_file_sha256'):
            for name, digest in manifest.get(group, {}).items():
                if group == 'evaluation_evidence_sha256' and manifest.get('model_profile') == 'calibrated':
                    name = {'score_comparison': 'data/processed/evaluation_v3/development_metrics.json',
                            'nested_alert_evaluation': 'data/processed/evaluation_v3/nested_alert_metrics.json'}.get(name, name)
                path = Path(name.replace('\\', '/'))
                if path.as_posix() not in names or hashlib.sha256((root / path).read_bytes()).hexdigest() != digest:
                    findings.append(f'{path.as_posix()}: frozen provenance file missing or changed')
    return findings


def check_history(root: Path) -> tuple[int, list[str]]:
    """Inspect reachable Git text blobs without exposing matched values."""
    if not (root / '.git').exists():
        return 0, []
    result = subprocess.run(['git', 'rev-list', '--objects', '--all'], cwd=root,
                            check=True, capture_output=True, text=True)
    blobs = {}
    findings = []
    for line in result.stdout.splitlines():
        oid, separator, name = line.partition(' ')
        if not separator:
            continue
        path = Path(name)
        if (path.name.startswith('.env') and path.name != '.env.example') or path.suffix in {'.sqlite3', '.sql', '.pem', '.key', '.p12', '.pfx'}:
            findings.append(f'Git history contains a private file: {name}')
        if path.suffix in TEXT_SUFFIXES and not name.startswith('data/raw/') or path.name == '.env.example':
            blobs[oid] = name
    if not blobs:
        return 0, findings
    result = subprocess.run(['git', 'cat-file', '--batch'], cwd=root, check=True,
                            input=''.join(oid + '\n' for oid in blobs).encode(), capture_output=True)
    offset = 0
    secrets = local_secrets(root)
    for _ in blobs:
        end = result.stdout.index(b'\n', offset)
        oid, kind, size = result.stdout[offset:end].split()
        size = int(size)
        start = end + 1
        content = result.stdout[start:start + size]
        offset = start + size + 1
        if kind == b'blob':
            findings.extend(secret_findings(content.decode('utf-8', errors='replace'),
                                             blobs[oid.decode()], secrets))
    return len(blobs), sorted(set(findings))


def export(root: Path, files: list[Path], output: Path) -> None:
    """Export selected bytes, then verify the archive against its own manifest."""
    manifest = {path.as_posix(): hashlib.sha256((root / path).read_bytes()).hexdigest() for path in files}
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.release-', suffix='.zip', dir=output.parent)
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in files:
                archive.write(root / path, 'silent-window/' + path.as_posix())
            archive.writestr('silent-window/RELEASE_MANIFEST.json', json.dumps(manifest, indent=2) + '\n')
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError('Release archive verification failed.')
            for name, expected in manifest.items():
                if hashlib.sha256(archive.read('silent-window/' + name)).hexdigest() != expected:
                    raise ValueError(f'Release file changed during export: {name}')
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, help='Write the checked source archive to a new path')
    parser.add_argument('--history', action='store_true', help='Also scan reachable Git history')
    args = parser.parse_args()
    try:
        files = collect_files(ROOT)
        findings = check(ROOT, files)
        if args.history:
            count, historical_findings = check_history(ROOT)
            findings.extend(historical_findings)
            print(f'Git history checked: {count} text objects.')
        if findings:
            for finding in sorted(set(findings)):
                print(f'- {finding}')
            return 1
        print(f'Release checks passed: {len(files)} files; required cohort and all saved models included.')
        print('Local secrets, account databases, runtime files, dependencies and Git history are excluded from the archive.')
        if args.zip:
            output = args.zip.resolve()
            if output.exists():
                raise ValueError('Choose a new archive filename; existing files are not overwritten.')
            if output.suffix != '.zip' or output.parent != ROOT / 'dist':
                raise ValueError('Release output must be a .zip inside the project dist folder.')
            export(ROOT, files, output)
            print(f'Checked archive: dist/{output.name} ({output.stat().st_size / 1024 / 1024:.2f} MB)')
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, KeyError):
        print('Release preparation failed. Check required files and Git access; no credentials were printed.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
