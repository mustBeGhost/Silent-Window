"""Startup preflight detects missing/incompatible packages before serving models."""
from importlib.metadata import PackageNotFoundError
from scripts.check_installation import dependency_errors
import scripts.check_installation as checks


def test_preflight_detects_missing_and_mismatched_packages(tmp_path, monkeypatch):
    (tmp_path / 'requirements.txt').write_text('# Runtime\nexample[rsa]==1.2.3\nother==4.5.6\n', encoding='utf-8')
    def version(name):
        if name == 'example':
            return '0.9'
        raise PackageNotFoundError(name)
    monkeypatch.setattr(checks, 'version', version)
    errors = dependency_errors(tmp_path)
    assert len(errors) == 2
    assert 'example: expected 1.2.3, found 0.9' in errors[0]
    assert 'other is missing' in errors[1]
