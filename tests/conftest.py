"""Existing inference tests use an explicit principal; auth tests use real sessions.

Only the tests override these dependencies. The running application has no
anonymous/demo bypass. This keeps the model tests focused on their subject.
"""
import pytest
from backend.main import app
from backend.auth import current_user, require_write
from backend.services.auth_service import Principal
from backend.permissions import capabilities


def pytest_configure(config):
    config.addinivalue_line("markers", "real_auth: exercise real cookie authentication and authorization")


@pytest.fixture(scope="module", autouse=True)
def authenticated_inference_tests(request):
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    prior = dict(app.dependency_overrides)
    principal = Principal({"id": 1, "username": "inference-test", "display_name": "Inference test",
                           "role": "admin", "active": True, "capabilities": capabilities("admin"),
                           "preferences": {"preferred_model": "original", "page_size": 25, "replay_step": 60}}, "0" * 64)
    app.dependency_overrides[current_user] = lambda: principal
    app.dependency_overrides[require_write] = lambda: principal
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(prior)
