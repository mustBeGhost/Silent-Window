"""Read-only startup checks for dependencies, patient data, models and MySQL."""
import argparse
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def dependency_errors(root=ROOT):
    errors = []
    for line in (root / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        requirement, expected = line.split('==')
        name = requirement.split('[')[0]
        try:
            actual = version(name)
            if actual != expected:
                errors.append(f'{name}: expected {expected}, found {actual}. Install requirements.txt before loading saved models.')
        except PackageNotFoundError:
            errors.append(f'{name} is missing. Install requirements.txt.')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-database', action='store_true', help='Check files and software before first MySQL setup')
    args = parser.parse_args()
    errors = dependency_errors()
    if sys.version_info < (3, 11):
        errors.append('Python 3.11 or newer is required. Python 3.11 is the tested version.')
    node = shutil.which('node')
    if not node:
        errors.append('Node.js is missing. Install Node.js 22 or newer.')
    else:
        try:
            result = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=10, check=True)
            if int(result.stdout.strip().lstrip('v').split('.')[0]) < 22:
                errors.append('Use Node.js 22 or newer for the tested frontend setup.')
        except (subprocess.SubprocessError, ValueError, OSError):
            errors.append('Node.js could not be checked.')
    if not (ROOT / 'frontend/node_modules/vite/package.json').is_file():
        errors.append('Frontend packages are missing. Run npm ci inside frontend.')
    patients = ROOT / 'data/raw/dataset_2/train/set-a'
    if not patients.is_dir() or not any(patients.glob('*.txt')):
        errors.append('Patient files are missing from data/raw/dataset_2/train/set-a. See docs/setup-guide.md.')
    if not (patients.parent / 'Outcomes-train.txt').is_file():
        errors.append('Outcomes-train.txt is missing. See docs/setup-guide.md.')
    if not errors:
        try:
            from backend.services.patient_service import get_patient_inference_service
            for profile in ('original', 'calibrated', 'expanded'):
                get_patient_inference_service(profile)
            from scripts.train_rf_v2_artifacts import validated_training_cohorts
            validated_training_cohorts()
            print('Saved models: all three versions passed the existing integrity and loading checks.')
        except Exception:
            errors.append('Saved models could not be verified. Restore trusted model files and matching requirements; see docs/setup-guide.md.')
    if not errors and not args.skip_database:
        try:
            from scripts.check_database import main as check_database
            check_database()
        except (Exception, SystemExit):
            errors.append('MySQL is not ready. Check the service, .env and schema migration; see docs/setup-guide.md.')
    if errors:
        for error in errors:
            print(f'- {error}', file=sys.stderr)
        return 1
    print('Installation checks passed. Starting the website will not train models or create a database server.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
