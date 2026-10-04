"""Issue an account recovery code locally after verifying database administrator access.

Use this if no website administrator can sign in. It never changes a password
directly, enables a disabled account, or creates a user. Verify identity first.
"""
import argparse
import getpass
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from backend.services.auth_service import AuthStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=3306)
    parser.add_argument('--username', default='root', help='MySQL administrator username')
    parser.add_argument('--account', required=True, help='Existing website username to recover')
    args = parser.parse_args()
    if input(f'Identity verified for {args.account}? Type VERIFY to continue: ') != 'VERIFY':
        parser.exit(1, 'Recovery cancelled.\n')
    password = getpass.getpass('MySQL administrator password: ')
    url = URL.create('mysql+pymysql', username=args.username, password=password,
        host=args.host, port=args.port, database='silent_window')
    engine = create_engine(url, hide_parameters=True)
    store = None
    try:
        # The restricted application account cannot read mysql.user. Require
        # database operator access rather than trusting access to a local .env.
        with engine.connect() as connection:
            connection.execute(text('SELECT User FROM mysql.user LIMIT 1')).first()
        store = AuthStore(url.render_as_string(hide_password=False))
        result = store.issue_operator_recovery(args.account.lower())
        print('One-use recovery code (expires in 15 minutes):')
        print(result['recovery_code'])
        print('Open /recover on the website. Keep this code private; no password was changed yet.')
    except Exception:
        parser.exit(1, 'Recovery failed. Check the server, migrated schema, administrator credentials and active account.\n')
    finally:
        if store is not None:
            store.database.close()
        engine.dispose()


if __name__ == '__main__':
    main()
