# Final portfolio release verification

Release date: 2026-10-30. The owner explicitly authorized updating the existing
mustBeGhost/Silent-Window GitHub repository. This release keeps the application
as a recorded-data research demonstration and does not deploy a hospital service.

## Verification

- Clean temporary Python runtime: pip check reported no broken requirements.
- Clean runtime installation checker loaded all three saved model versions and
  confirmed the existing MySQL schema on port 3306 without modifying user records.
- Frontend: 86 tests passed; production build passed. Compatible dependency fixes
  updated Vite to 6.4.5 and source-map-js to 1.2.2; npm audit reported zero advisories.
- Final backend/model regression: 485 passed, 84 MySQL-parametrized cases excluded
  to preserve the owner's existing test accounts. Five existing deprecation warnings.
- Publication uses explicitly selected source files, saved models and attributed
  public data. Source/secret scans and archive hash verification are run before push.
- README screenshots use fictional staff in isolated SQLite preview storage.
- Normal MySQL app/test accounts, local notes, .env and private backups are excluded.
- No source-code license was added, following the owner's choice. Public data keeps
  its existing separate attribution/license.

- Extracted-source installation: saved models and source checks passed using the
  clean runtime; npm ci and frontend build passed in a separate extracted copy.
- This checks clean source/dependencies, not a second physical laptop or a newly
  provisioned MySQL server. Existing schema connectivity was checked separately.

## Handoff

Follow README.md and docs/setup-guide.md on a new laptop. No default shared website
credentials or paid API key is required. Database setup uses that laptop's MySQL.
For project continuity read docs/PROJECT_HANDOVER.md. For personal narration and
resume preparation read docs/demo-and-resume.md. These are the owner's remaining
portfolio tasks; no additional product features are required for this release.
