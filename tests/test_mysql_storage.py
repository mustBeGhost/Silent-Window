"""Live MySQL checks for least privilege, persistence and safe failure responses."""
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from backend.main import app
from backend.services.auth_service import AuthStore
import backend.services.auth_service as auth_module

pytestmark = pytest.mark.real_auth


def test_mysql_test_account_cannot_create_tables_and_storage_is_not_sqlite():
    location = os.environ.get("SILENT_WINDOW_TEST_DATABASE_URL")
    if not location:
        pytest.skip("MySQL integration URL is not configured")
    assert make_url(location).database.endswith("_auth_test")
    store = AuthStore(location)
    try:
        assert store.database.kind == "mysql"
        with pytest.raises(OperationalError):
            with store.db() as db:
                db.execute("CREATE TABLE denied_ddl_test (id INTEGER)")
        with pytest.raises(OperationalError):
            with store.db() as db:
                db.execute("SELECT User FROM mysql.user LIMIT 1")
    finally:
        store.database.close()


def test_database_connection_failure_returns_no_sql_or_credentials(monkeypatch):
    class UnavailableStore:
        def setup_required(self):
            raise OperationalError("SELECT private_data", {}, RuntimeError("do-not-expose-password"))
    monkeypatch.setattr(auth_module, "_STORE", UnavailableStore())
    response = TestClient(app).get("/api/auth/status")
    assert response.status_code == 503
    assert "MySQL" in response.json()["detail"]
    assert "private_data" not in response.text and "do-not-expose-password" not in response.text
