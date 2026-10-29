"""The additive approval migration preserves existing accounts and is repeatable."""
import pytest
from sqlalchemy import create_engine, text, inspect
from backend.services.account_database import metadata, SCHEMA_VERSION
from scripts.migrate_accounts import migrate


@pytest.mark.parametrize('version', [1, 2, 3, 4, 5, 6])
def test_migration_preserves_users_and_sessions_and_is_idempotent(tmp_path, version):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite3'}")
    missing = {'handovers', 'handover_events', 'availability_events'}
    if version < 6:
        missing |= {'doctor_review_requests', 'doctor_review_events'}
    if version < 5:
        missing.add('follow_up_events')
    if version < 4:
        missing |= {'patient_contexts', 'clinical_entries', 'vital_rule_versions'}
    if version == 1:
        missing |= {'permission', 'password_resets'}
    elif version == 2:
        missing |= {'password_resets'}
    metadata.create_all(engine, tables=[table for table in metadata.sorted_tables if table.name not in missing])
    with engine.begin() as connection:
        connection.execute(text('INSERT INTO schema_version VALUES(:version)'), {'version': version})
        connection.execute(text("INSERT INTO users(id,username,display_name,password_hash,role,created_at) VALUES(1,'owner','Owner','existing-hash','admin',123)"))
        connection.execute(text("INSERT INTO sessions VALUES('existing-session',1,123,123,9999999999)"))
    assert migrate(engine) == SCHEMA_VERSION
    assert migrate(engine) == SCHEMA_VERSION
    with engine.connect() as connection:
        assert connection.execute(text('SELECT username,password_hash FROM users')).one() == ('owner', 'existing-hash')
        assert connection.execute(text('SELECT token_hash FROM sessions')).scalar_one() == 'existing-session'
        assert connection.execute(text('SELECT version FROM schema_version')).scalar_one() == SCHEMA_VERSION
        assert connection.execute(text('SELECT COUNT(*) FROM permission')).scalar_one() == 0
    assert 'permission' in inspect(engine).get_table_names()
    assert 'password_resets' in inspect(engine).get_table_names()
    assert {'patient_contexts', 'clinical_entries', 'vital_rule_versions'} <= set(inspect(engine).get_table_names())
    assert {'follow_up_events', 'doctor_review_requests', 'doctor_review_events'} <= set(inspect(engine).get_table_names())
    engine.dispose()
