"""Check the configured MySQL server without starting a separate server."""
import os
from pathlib import Path
from dotenv import load_dotenv
from backend.services.account_database import AccountDatabase


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    location = os.environ.get("SILENT_WINDOW_DATABASE_URL")
    if not location:
        raise SystemExit("Configure MySQL first: python -m scripts.configure_mysql")
    try:
        storage = AccountDatabase(location)
        if storage.kind != "mysql":
            raise RuntimeError("The project requires a configured MySQL server")
        with storage.db() as db:
            row = db.execute("SELECT DATABASE() AS name, @@port AS port").fetchone()
            print(f"Silent Window database ready: {row['name']} on MySQL port {row['port']}.")
        storage.close()
    except Exception:
        raise SystemExit("MySQL is unavailable. Check the configured server and .env connection details.") from None


if __name__ == "__main__":
    main()
