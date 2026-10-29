"""Add account and clinical tables without replacing accounts or sessions."""
import argparse
import getpass
import sys
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from backend.services.account_database import (metadata, permission, password_resets, SCHEMA_VERSION,
    patient_contexts, clinical_entries, vital_rule_versions, follow_up_events, doctor_review_requests, doctor_review_events, availability_events, handovers, handover_events)


def migrate(engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    additions = (permission, password_resets, patient_contexts, clinical_entries, vital_rule_versions, follow_up_events, doctor_review_requests, doctor_review_events, availability_events, handovers, handover_events)
    if not (set(metadata.tables) - {table.name for table in additions}).issubset(tables):
        raise RuntimeError('This is not an initialized Silent Window account database.')
    with engine.connect() as connection:
        version = list(connection.execute(text('SELECT version FROM schema_version')).scalars())
    if version not in ([1], [2], [3], [4], [5], [6], [SCHEMA_VERSION]):
        raise RuntimeError('Unsupported account schema version.')
    for table in additions:
        table.create(engine, checkfirst=True)
        if {column['name'] for column in inspect(engine).get_columns(table.name)} != set(table.c.keys()):
            raise RuntimeError(f'The {table.name} table does not match the expected schema.')
    with engine.begin() as connection:
        connection.execute(text('UPDATE schema_version SET version=:version'), {'version': SCHEMA_VERSION})
    return SCHEMA_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=3306)
    parser.add_argument('--username', default='root')
    parser.add_argument('--password-stdin', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip('\r\n') if args.password_stdin else getpass.getpass('MySQL administrator password: ')
    try:
        for name in ('silent_window', 'silent_window_auth_test'):
            engine = create_engine(URL.create('mysql+pymysql', username=args.username, password=password,
                host=args.host, port=args.port, database=name), hide_parameters=True)
            try:
                with engine.connect() as connection:
                    before = connection.execute(text('SELECT COUNT(*) FROM users')).scalar_one()
                migrate(engine)
                with engine.connect() as connection:
                    after = connection.execute(text('SELECT COUNT(*) FROM users')).scalar_one()
                if before != after:
                    raise RuntimeError('User count changed during migration; inspect concurrent writes.')
                print(f'{name}: schema {SCHEMA_VERSION}, account and clinical tables ready, {after} existing users preserved.')
            finally:
                engine.dispose()
    except Exception:
        parser.exit(1, 'Migration could not finish. Check the server and administrator permissions; no credentials were printed.\n')


if __name__ == '__main__':
    main()
