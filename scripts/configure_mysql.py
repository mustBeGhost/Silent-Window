"""Set up Silent Window on an existing MySQL server. Administrator credentials
are read from the terminal and are never saved in the application configuration.
"""
import argparse
import getpass
import secrets
from pathlib import Path

import pymysql
from dotenv import set_key
from sqlalchemy.engine import URL
from backend.services.account_database import AccountDatabase

ROOT = Path(__file__).resolve().parents[1]


def database_url(host, port, database, username, password):
    return URL.create("mysql+pymysql", username=username, password=password, host=host,
                      port=port, database=database, query={"charset": "utf8mb4"}).render_as_string(hide_password=False)


def configure(host, port, username, password):
    names = ("silent_window", "silent_window_auth_test")
    credentials = {"silent_window_app": secrets.token_urlsafe(32),
                   "silent_window_test": secrets.token_urlsafe(32)}
    with pymysql.connect(host=host, port=port, user=username, password=password,
                         charset="utf8mb4", autocommit=True, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@port, VERSION(), CURRENT_USER()")
            actual_port, version, actor = cursor.fetchone()
            print(f"Connected to your existing MySQL server: port {actual_port}, version {version}, account {actor}.")
            # Validate both destinations before making any changes.
            for name in names:
                cursor.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", (name,))
                tables = {row[0] for row in cursor.fetchall()}
                if tables:
                    raise RuntimeError(f"{name} already contains tables. No existing tables were modified; inspect the destination first.")
            for user in credentials:
                cursor.execute("SELECT COUNT(*) FROM mysql.user WHERE User=%s AND Host='localhost'", (user,))
                if cursor.fetchone()[0]:
                    raise RuntimeError(f"The account {user} already exists. Its credentials were not changed.")
            for name in names:
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
            for user, secret in credentials.items():
                cursor.execute("CREATE USER %s@'localhost' IDENTIFIED BY %s", (user, secret))
            cursor.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON silent_window.* TO 'silent_window_app'@'localhost'")
            cursor.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON silent_window_auth_test.* TO 'silent_window_test'@'localhost'")
        for name in names:
            storage = AccountDatabase(database_url(host, port, name, username, password), initialize=True)
            storage.close()
    # The application uses a restricted account rather than root.
    app_url = database_url(host, port, names[0], "silent_window_app", credentials["silent_window_app"])
    test_url = database_url(host, port, names[1], "silent_window_test", credentials["silent_window_test"])
    for url in (app_url, test_url):
        storage = AccountDatabase(url)
        storage.close()
    set_key(str(ROOT / ".env"), "SILENT_WINDOW_DATABASE_URL", app_url)
    set_key(str(ROOT / ".env"), "SILENT_WINDOW_TEST_DATABASE_URL", test_url)
    print(f"Silent Window now uses your existing MySQL server at {host}:{port}.")
    print("Project schema: silent_window. Test schema: silent_window_auth_test. No unrelated schemas were changed.")
    print("The MySQL administrator password was not saved. Restricted application credentials are in the ignored .env file.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--username", default="root")
    args = parser.parse_args()
    password = getpass.getpass("MySQL administrator password: ")
    try:
        configure(args.host, args.port, args.username, password)
    except RuntimeError as error:
        parser.exit(1, str(error) + "\n")
    except Exception:
        parser.exit(1, "MySQL setup failed. Check the server, account permissions, and connection details. No credential details were printed.\n")


if __name__ == "__main__":
    main()
