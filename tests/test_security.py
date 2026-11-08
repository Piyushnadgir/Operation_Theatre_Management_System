"""Security validation, one test group per security requirement (Test Plan section 5.1).

TC-Sec-01 TLS / HTTPS only      OT-SR-001
TC-Sec-02 hashed passwords      OT-SR-002
TC-Sec-03 server-side RBAC      OT-SR-003
TC-Sec-04 account lockout       OT-SR-004
TC-Sec-05 audit log             OT-SR-005
TC-Sec-06 input validation      OT-SR-006
"""
import re

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.https import EnforceHTTPSMiddleware
from app.main import app
from app.models.models import AuditLog, RoleEnum, Staff, User
from app.services.audit_service import AuditLogImmutableError, get_audit_logs
from tests.api_fixtures import admin_headers, client, headers_for  # noqa: F401
from tests.helpers import PASSWORD

API = "/api/v1"


# ---------- TC-Sec-01 ----------
def _https_only_app():
    small = FastAPI()
    small.add_middleware(EnforceHTTPSMiddleware)

    @small.get("/ping")
    def ping():
        return {"ok": True}

    return small


def test_plain_http_is_refused():
    response = TestClient(_https_only_app(), base_url="http://testserver").get("/ping")
    assert response.status_code == 403
    assert "HTTPS" in response.text


def test_https_is_accepted_and_hsts_is_sent():
    response = TestClient(_https_only_app(), base_url="https://testserver").get("/ping")
    assert response.status_code == 200
    assert "max-age" in response.headers["strict-transport-security"]


def test_https_enforcement_is_off_by_default_for_local_development():
    from app.core.config import settings

    assert settings.enforce_https is False


# ---------- TC-Sec-02 ----------
def test_password_is_stored_as_salted_hash(client, db_session):
    for name in ("user.one", "user.two"):
        headers_for(client, db_session, name, RoleEnum.nurse)
    hashes = [row[0] for row in db_session.execute(text("SELECT password_hash FROM app_user"))]
    assert len(hashes) == 2
    assert all(PASSWORD not in h and h.startswith("$2") for h in hashes)
    assert hashes[0] != hashes[1]  # same password, different salt


def test_password_never_appears_in_responses_or_audit_log(client, db_session, admin_headers):
    login = client.post(f"{API}/auth/login", json={"username": "admin1", "password": PASSWORD})
    assert PASSWORD not in login.text
    created = client.post(
        f"{API}/auth/users", json={"username": "new.user", "password": PASSWORD, "role": "nurse"},
        headers=admin_headers,
    )
    assert PASSWORD not in created.text
    for entry in db_session.query(AuditLog).all():
        assert PASSWORD not in f"{entry.action} {entry.details or ''}"


# ---------- TC-Sec-03 ----------
PUBLIC_PATHS = {f"{API}/auth/login"}


def _api_routes():
    return [
        r for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith(API) and r.path not in PUBLIC_PATHS
    ]


def test_every_endpoint_requires_a_token(client):
    routes = _api_routes()
    assert len(routes) >= 10  # guard: the loop below really covers the API
    for route in routes:
        path = re.sub(r"\{[^}]+\}", "1", route.path)
        for method in route.methods:
            body = {} if method in {"POST", "PUT", "PATCH"} else None
            response = client.request(method, path, json=body)
            assert response.status_code == 401, f"{method} {route.path} returned {response.status_code}"


ADMIN_ONLY = [
    ("POST", f"{API}/staff"),
    ("PUT", f"{API}/staff/1"),
    ("DELETE", f"{API}/staff/1"),
    ("PUT", f"{API}/staff/1/shifts"),
    ("POST", f"{API}/auth/users"),
    ("POST", f"{API}/auth/users/1/unlock"),
]


@pytest.mark.parametrize("role", [RoleEnum.nurse, RoleEnum.doctor, RoleEnum.scheduler])
@pytest.mark.parametrize("method,path", ADMIN_ONLY)
def test_non_admin_roles_get_403_on_admin_endpoints(client, db_session, role, method, path):
    headers = headers_for(client, db_session, f"user.{role.value}", role)
    body = {} if method in {"POST", "PUT"} else None
    assert client.request(method, path, json=body, headers=headers).status_code == 403


# ---------- TC-Sec-04 ----------
def test_account_lockout_over_the_api(client, db_session):
    headers_for(client, db_session, "alice", RoleEnum.scheduler)
    codes = [
        client.post(f"{API}/auth/login", json={"username": "alice", "password": "bad"}).status_code
        for _ in range(5)
    ]
    assert codes == [401] * 5
    assert client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 423
    assert db_session.query(User).filter_by(username="alice").one().locked_until is not None


# ---------- TC-Sec-05 ----------
def test_staff_changes_are_audited_with_user_and_time(client, db_session, admin_headers):
    created = client.post(f"{API}/staff", json={"name": "Dr. Asha", "staff_type": "doctor"}, headers=admin_headers)
    staff_id = created.json()["staff_id"]
    client.put(f"{API}/staff/{staff_id}", json={"name": "Dr. A. Rao"}, headers=admin_headers)
    client.delete(f"{API}/staff/{staff_id}", headers=admin_headers)

    entries = get_audit_logs(db_session, entity_type="staff", entity_id=staff_id)
    assert [e.action for e in entries] == ["staff.create", "staff.update", "staff.deactivate"]
    admin_id = db_session.query(User).filter_by(username="admin1").one().user_id
    assert all(e.user_id == admin_id and e.timestamp is not None for e in entries)


def test_audit_log_cannot_be_edited_through_the_application(db_session):
    from app.services.audit_service import log_action

    entry = log_action(db_session, "surgery.create", entity_type="surgery", entity_id=1)
    entry.action = "something else"
    with pytest.raises(AuditLogImmutableError):
        db_session.commit()
    db_session.rollback()


# ---------- TC-Sec-06 ----------
INJECTIONS = ["' OR '1'='1", "admin'--", "'; DROP TABLE app_user; --", '" OR ""="']


@pytest.mark.parametrize("payload", INJECTIONS)
def test_sql_injection_in_login_is_rejected(client, db_session, payload):
    headers_for(client, db_session, "alice", RoleEnum.scheduler)
    response = client.post(f"{API}/auth/login", json={"username": payload, "password": payload})
    assert response.status_code == 401
    assert db_session.query(User).count() == 1  # table intact


def test_injection_string_in_staff_name_is_stored_harmlessly(client, db_session, admin_headers):
    evil = "Robert'); DROP TABLE staff;--"
    response = client.post(f"{API}/staff", json={"name": evil, "staff_type": "nurse"}, headers=admin_headers)
    assert response.status_code == 201
    assert response.json()["name"] == evil  # stored literally
    assert db_session.query(Staff).count() == 1  # table still exists


def test_oversized_and_malformed_input_is_rejected(client, admin_headers):
    huge = "A" * 5000
    assert client.post(f"{API}/auth/login", json={"username": huge, "password": huge}).status_code == 422
    assert client.post(f"{API}/staff", json={"name": huge, "staff_type": "nurse"}, headers=admin_headers).status_code == 422
    assert client.post(f"{API}/staff", json={"name": 123, "staff_type": ["x"]}, headers=admin_headers).status_code == 422
    assert client.post(
        f"{API}/staff", content="not json", headers={**admin_headers, "Content-Type": "application/json"}
    ).status_code == 422
