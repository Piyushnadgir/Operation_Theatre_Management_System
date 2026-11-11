"""API tests for login, RBAC (TC-Auth-01/02) and the staff / shift endpoints (TC-Staff-01..03)."""
from app.models.models import RoleEnum
from app.services.auth_service import MAX_FAILED_ATTEMPTS
from tests.api_fixtures import admin_headers, client, headers_for  # noqa: F401
from tests.helpers import PASSWORD

API = "/api/v1"


# ---------- login (TC-Auth-01) ----------
def test_login_success(client, db_session):
    headers_for(client, db_session, "alice", RoleEnum.scheduler)  # creates user + logs in
    response = client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "scheduler" and body["token"]


def test_login_wrong_password_is_401(client, db_session):
    headers_for(client, db_session, "alice", RoleEnum.scheduler)
    response = client.post(f"{API}/auth/login", json={"username": "alice", "password": "nope"})
    assert response.status_code == 401


def test_login_unknown_user_is_401(client):
    response = client.post(f"{API}/auth/login", json={"username": "ghost", "password": PASSWORD})
    assert response.status_code == 401


def test_login_missing_fields_is_422(client):
    assert client.post(f"{API}/auth/login", json={"username": "alice"}).status_code == 422


def test_login_locks_after_five_failures_is_423(client, db_session):
    headers_for(client, db_session, "alice", RoleEnum.scheduler)
    for _ in range(MAX_FAILED_ATTEMPTS):
        assert client.post(f"{API}/auth/login", json={"username": "alice", "password": "bad"}).status_code == 401
    right = client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD})
    assert right.status_code == 423


def test_admin_can_unlock_account(client, db_session, admin_headers):
    headers_for(client, db_session, "alice", RoleEnum.scheduler)
    for _ in range(MAX_FAILED_ATTEMPTS):
        client.post(f"{API}/auth/login", json={"username": "alice", "password": "bad"})
    from app.models.models import User

    alice_id = db_session.query(User).filter_by(username="alice").one().user_id
    assert client.post(f"{API}/auth/users/{alice_id}/unlock", headers=admin_headers).status_code == 200
    assert client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 200


def test_unlock_unknown_user_is_404(client, admin_headers):
    assert client.post(f"{API}/auth/users/999/unlock", headers=admin_headers).status_code == 404


# ---------- user management ----------
def test_admin_creates_user(client, admin_headers):
    response = client.post(
        f"{API}/auth/users",
        json={"username": "nurse.ravi", "password": PASSWORD, "role": "nurse"},
        headers=admin_headers,
    )
    assert response.status_code == 201
    assert response.json()["role"] == "nurse"
    assert "password" not in response.text and "hash" not in response.text


def test_duplicate_user_is_409(client, admin_headers):
    payload = {"username": "nurse.ravi", "password": PASSWORD, "role": "nurse"}
    assert client.post(f"{API}/auth/users", json=payload, headers=admin_headers).status_code == 201
    assert client.post(f"{API}/auth/users", json=payload, headers=admin_headers).status_code == 409


def test_weak_or_invalid_user_input_is_422(client, admin_headers):
    for payload in (
        {"username": "ab", "password": PASSWORD, "role": "nurse"},  # too short
        {"username": "bad name!", "password": PASSWORD, "role": "nurse"},  # bad characters
        {"username": "okname", "password": "short", "role": "nurse"},  # weak password
        {"username": "okname", "password": PASSWORD, "role": "emperor"},  # unknown role
    ):
        assert client.post(f"{API}/auth/users", json=payload, headers=admin_headers).status_code == 422


def test_only_admin_can_create_users(client, db_session):
    scheduler = headers_for(client, db_session, "sam", RoleEnum.scheduler)
    response = client.post(
        f"{API}/auth/users", json={"username": "newbie", "password": PASSWORD, "role": "nurse"}, headers=scheduler
    )
    assert response.status_code == 403


# ---------- staff CRUD (TC-Staff-01) ----------
def _create_staff(client, headers, name="Dr. Asha", staff_type="doctor", specialization="Cardiology"):
    response = client.post(
        f"{API}/staff",
        json={"name": name, "staff_type": staff_type, "specialization": specialization},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_staff_crud_flow(client, admin_headers):
    created = _create_staff(client, admin_headers)
    staff_id = created["staff_id"]
    assert created["is_active"] is True and created["staff_type"] == "doctor"

    updated = client.put(f"{API}/staff/{staff_id}", json={"specialization": "Neurology"}, headers=admin_headers)
    assert updated.status_code == 200 and updated.json()["specialization"] == "Neurology"
    assert updated.json()["name"] == "Dr. Asha"

    listed = client.get(f"{API}/staff", headers=admin_headers).json()
    assert [s["staff_id"] for s in listed] == [staff_id]

    deactivated = client.delete(f"{API}/staff/{staff_id}", headers=admin_headers)
    assert deactivated.status_code == 200 and deactivated.json() == {"status": "deactivated"}
    assert client.get(f"{API}/staff", headers=admin_headers).json() == []
    still_there = client.get(f"{API}/staff", params={"include_inactive": True}, headers=admin_headers).json()
    assert still_there[0]["is_active"] is False


def test_staff_list_filters(client, admin_headers):
    _create_staff(client, admin_headers, "Dr. Asha", "doctor", "Cardiology")
    _create_staff(client, admin_headers, "Nurse Ravi", "nurse", None)
    doctors = client.get(f"{API}/staff", params={"staff_type": "doctor"}, headers=admin_headers).json()
    assert [s["name"] for s in doctors] == ["Dr. Asha"]
    cardio = client.get(f"{API}/staff", params={"specialization": "cardiology"}, headers=admin_headers).json()
    assert len(cardio) == 1


def test_staff_not_found_is_404(client, admin_headers):
    assert client.put(f"{API}/staff/999", json={"name": "X"}, headers=admin_headers).status_code == 404
    assert client.delete(f"{API}/staff/999", headers=admin_headers).status_code == 404


def test_staff_invalid_input_is_422(client, admin_headers):
    for payload in (
        {"name": "", "staff_type": "doctor"},
        {"name": "   ", "staff_type": "doctor"},
        {"name": "Dr. X", "staff_type": "janitor"},
        {"name": "x" * 101, "staff_type": "doctor"},
    ):
        assert client.post(f"{API}/staff", json=payload, headers=admin_headers).status_code == 422
    assert client.put(f"{API}/staff/1", json={}, headers=admin_headers).status_code == 422


# ---------- RBAC (TC-Auth-02) ----------
def test_scheduler_can_list_but_not_change_staff(client, db_session, admin_headers):
    _create_staff(client, admin_headers)
    scheduler = headers_for(client, db_session, "sam", RoleEnum.scheduler)
    assert client.get(f"{API}/staff", headers=scheduler).status_code == 200
    assert client.post(f"{API}/staff", json={"name": "X", "staff_type": "nurse"}, headers=scheduler).status_code == 403
    assert client.delete(f"{API}/staff/1", headers=scheduler).status_code == 403


def test_doctor_and_nurse_cannot_manage_staff(client, db_session):
    for username, role in (("dr.who", RoleEnum.doctor), ("nurse.joy", RoleEnum.nurse)):
        headers = headers_for(client, db_session, username, role)
        assert client.get(f"{API}/staff", headers=headers).status_code == 403
        assert client.post(f"{API}/staff", json={"name": "X", "staff_type": "nurse"}, headers=headers).status_code == 403
        assert client.put(f"{API}/staff/1/shifts", json={"shifts": []}, headers=headers).status_code == 403


def test_missing_and_bad_tokens_are_401(client):
    assert client.get(f"{API}/staff").status_code == 401
    assert client.get(f"{API}/staff", headers={"Authorization": "Bearer not.a.token"}).status_code == 401


# ---------- shifts and availability (TC-Staff-02) ----------
SHIFT = {"start_time": "2026-11-10T08:00:00", "end_time": "2026-11-10T16:00:00"}


def test_set_and_read_shifts(client, admin_headers):
    staff_id = _create_staff(client, admin_headers)["staff_id"]
    response = client.put(f"{API}/staff/{staff_id}/shifts", json={"shifts": [SHIFT]}, headers=admin_headers)
    assert response.status_code == 200
    assert len(response.json()["shifts"]) == 1
    read_back = client.get(f"{API}/staff/{staff_id}/shifts", headers=admin_headers).json()
    assert read_back["shifts"][0]["start_time"].startswith("2026-11-10T08:00:00")


def test_overlapping_or_invalid_shifts_are_400_or_422(client, admin_headers):
    staff_id = _create_staff(client, admin_headers)["staff_id"]
    overlap = [SHIFT, {"start_time": "2026-11-10T15:00:00", "end_time": "2026-11-10T20:00:00"}]
    assert client.put(f"{API}/staff/{staff_id}/shifts", json={"shifts": overlap}, headers=admin_headers).status_code == 400
    backwards = {"start_time": "2026-11-10T16:00:00", "end_time": "2026-11-10T08:00:00"}
    assert client.put(f"{API}/staff/{staff_id}/shifts", json={"shifts": [backwards]}, headers=admin_headers).status_code == 422


def test_shifts_for_unknown_staff_is_404(client, admin_headers):
    assert client.put(f"{API}/staff/999/shifts", json={"shifts": [SHIFT]}, headers=admin_headers).status_code == 404
    assert client.get(f"{API}/staff/999/shifts", headers=admin_headers).status_code == 404


def test_availability_endpoint(client, admin_headers):
    staff_id = _create_staff(client, admin_headers)["staff_id"]
    client.put(f"{API}/staff/{staff_id}/shifts", json={"shifts": [SHIFT]}, headers=admin_headers)

    def available(start, end):
        response = client.get(
            f"{API}/staff/{staff_id}/availability",
            params={"start_time": start, "end_time": end},
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        return response.json()["available"]

    assert available("2026-11-10T09:00:00", "2026-11-10T11:00:00") is True
    assert available("2026-11-10T15:00:00", "2026-11-10T18:00:00") is False
    assert available("2026-11-11T09:00:00", "2026-11-11T11:00:00") is False


def test_availability_errors(client, admin_headers):
    staff_id = _create_staff(client, admin_headers)["staff_id"]
    bad_range = client.get(
        f"{API}/staff/{staff_id}/availability",
        params={"start_time": "2026-11-10T11:00:00", "end_time": "2026-11-10T09:00:00"},
        headers=admin_headers,
    )
    assert bad_range.status_code == 400
    unknown = client.get(
        f"{API}/staff/999/availability",
        params={"start_time": "2026-11-10T09:00:00", "end_time": "2026-11-10T11:00:00"},
        headers=admin_headers,
    )
    assert unknown.status_code == 404
    missing_params = client.get(f"{API}/staff/{staff_id}/availability", headers=admin_headers)
    assert missing_params.status_code == 422


# ---------- assignment rule (TC-Staff-03) ----------
def test_validate_assignment_endpoint(client, admin_headers):
    ok_doctor = _create_staff(client, admin_headers, "Dr. Asha", "doctor", "Cardiology")["staff_id"]
    off_shift = _create_staff(client, admin_headers, "Dr. Off", "doctor", "Cardiology")["staff_id"]
    wrong_spec = _create_staff(client, admin_headers, "Dr. Neuro", "doctor", "Neurology")["staff_id"]
    for staff_id in (ok_doctor, wrong_spec):
        client.put(f"{API}/staff/{staff_id}/shifts", json={"shifts": [SHIFT]}, headers=admin_headers)

    window = {"start_time": "2026-11-10T09:00:00", "end_time": "2026-11-10T11:00:00"}
    good = client.post(
        f"{API}/staff/validate-assignment",
        json={"doctor_ids": [ok_doctor], "required_specialization": "Cardiology", **window},
        headers=admin_headers,
    )
    assert good.status_code == 200 and good.json() == {"valid": True, "conflicts": []}

    bad = client.post(
        f"{API}/staff/validate-assignment",
        json={"doctor_ids": [ok_doctor, off_shift, wrong_spec], "required_specialization": "Cardiology", **window},
        headers=admin_headers,
    )
    body = bad.json()
    assert bad.status_code == 200 and body["valid"] is False
    assert {c["resource_id"] for c in body["conflicts"]} == {off_shift, wrong_spec}


def test_validate_assignment_rejects_bad_range(client, admin_headers):
    response = client.post(
        f"{API}/staff/validate-assignment",
        json={"doctor_ids": [1], "start_time": "2026-11-10T11:00:00", "end_time": "2026-11-10T09:00:00"},
        headers=admin_headers,
    )
    assert response.status_code == 422
