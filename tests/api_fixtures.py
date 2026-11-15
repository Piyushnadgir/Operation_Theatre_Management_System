"""Fixtures for tests that call the real FastAPI app.

Import them in a test module with:
    from tests.api_fixtures import admin_headers, client, headers_for  # noqa: F401
"""
import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app
from app.models.models import RoleEnum
from app.services.auth_service import AuthService
from tests.helpers import PASSWORD


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def headers_for(client, db, username, role):
    """Create a user directly in the database, log in through the API, return auth headers."""
    AuthService(db).create_user(username, PASSWORD, role)
    response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture
def admin_headers(client, db_session):
    return headers_for(client, db_session, "admin1", RoleEnum.admin)
