"""HTTP API tests for Emergency endpoints and availability: OT-F-020..023, OT-NF-002 (OTMS-8..13)."""
from app.models.models import AuditLog, PriorityEnum, RoleEnum, Staff, StaffTypeEnum, Surgery, Theatre
from tests.api_fixtures import admin_headers, client, headers_for  # noqa: F401

API = "/api/v1/emergencies"


def _payload(**overrides):
    data = {
        "patient_name": "Ravi",
        "theatre_id": 1,
        "start_time": "2026-11-15T09:00:00",
        "end_time": "2026-11-15T10:00:00",
        "priority": "critical",
    }
    data.update(overrides)
    return data


def test_tc_rel_01_health_endpoint_available(client):
    for _ in range(5):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}


def test_create_emergency_no_clash(client, db_session, admin_headers):
    resp = client.post(API, json=_payload(), headers=admin_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["emergency_id"] >= 1
    assert body["slot"]["status"] == "scheduled"
    assert body["slot"]["priority"] == "critical"
    assert body["moved_surgeries"] == []
    assert db_session.query(AuditLog).filter(AuditLog.action == "emergency.create").count() == 1


def test_emergency_preempts_routine_via_api(client, db_session):
    sched_headers = headers_for(client, db_session, "sched.emg", RoleEnum.scheduler)
    theatre = Theatre(name="OT-1")
    db_session.add(theatre)
    db_session.commit()

    r1 = client.post(
        "/api/v1/surgeries",
        json={
            "patient_name": "Asha",
            "theatre_id": theatre.theatre_id,
            "start_time": "2026-11-15T09:00:00",
            "end_time": "2026-11-15T11:00:00",
            "priority": "routine",
        },
        headers=sched_headers,
    )
    assert r1.status_code == 201
    r1_id = r1.json()["surgery_id"]

    emg = client.post(API, json=_payload(theatre_id=theatre.theatre_id), headers=sched_headers)
    assert emg.status_code == 201
    data = emg.json()
    assert len(data["moved_surgeries"]) == 1
    assert data["moved_surgeries"][0]["surgery_id"] == r1_id
    assert data["moved_surgeries"][0]["new_start_time"].startswith("2026-11-15T10:00")
    assert data["notifications_created"] >= 1


def test_blocked_by_equal_priority_returns_409(client, db_session, admin_headers):
    assert client.post(API, json=_payload(), headers=admin_headers).status_code == 201
    conflict = client.post(API, json=_payload(patient_name="Second"), headers=admin_headers)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error"] == "Conflict"


def test_invalid_inputs_return_400(client, admin_headers):
    assert client.post(API, json=_payload(priority="routine"), headers=admin_headers).status_code == 400
    assert client.post(API, json=_payload(end_time="2026-11-15T08:00:00"), headers=admin_headers).status_code == 400
    assert client.post(API, json=_payload(patient_name="   "), headers=admin_headers).status_code == 400
    assert client.post(API, json={"theatre_id": 1}, headers=admin_headers).status_code == 400


def test_rbac_on_emergency_endpoints(client, db_session):
    assert client.post(API, json=_payload()).status_code == 401
    assert client.get(f"{API}/queue").status_code == 401
    assert client.get(f"{API}/notifications").status_code == 401

    nurse_headers = headers_for(client, db_session, "nurse.emg", RoleEnum.nurse)
    doctor_headers = headers_for(client, db_session, "doc.emg", RoleEnum.doctor)

    # Nurse cannot declare/preempt emergency via POST, but can read queue & notifications
    assert client.post(API, json=_payload(), headers=nurse_headers).status_code == 403
    assert client.get(f"{API}/queue", headers=nurse_headers).status_code == 200
    assert client.get(f"{API}/notifications", headers=nurse_headers).status_code == 200

    # Doctor can log emergency
    assert client.post(API, json=_payload(), headers=doctor_headers).status_code == 201


def test_queue_endpoint_orders_critical_first(client, db_session, admin_headers):
    client.post(
        API,
        json=_payload(patient_name="Urgent-1", theatre_id=1, priority="urgent"),
        headers=admin_headers,
    )
    client.post(
        API,
        json=_payload(patient_name="Critical-1", theatre_id=2, priority="critical"),
        headers=admin_headers,
    )
    client.post(
        API,
        json=_payload(patient_name="Urgent-2", theatre_id=3, priority="urgent"),
        headers=admin_headers,
    )
    resp = client.get(f"{API}/queue", headers=admin_headers)
    assert resp.status_code == 200
    assert [row["patient_name"] for row in resp.json()] == ["Critical-1", "Urgent-1", "Urgent-2"]


def test_notifications_endpoint_and_mark_read(client, db_session):
    sched_headers = headers_for(client, db_session, "sched.notif", RoleEnum.scheduler)
    doc_headers = headers_for(client, db_session, "doc.notif", RoleEnum.doctor)

    # Create routine surgery and bump it
    db_session.add(
        Surgery(
            patient_name="Routine",
            theatre_id=1,
            start_time=__import__("datetime").datetime(2026, 11, 15, 9, 0),
            end_time=__import__("datetime").datetime(2026, 11, 15, 10, 0),
            priority=PriorityEnum.routine,
        )
    )
    db_session.commit()

    client.post(API, json=_payload(), headers=sched_headers)

    notes = client.get(f"{API}/notifications", headers=sched_headers)
    assert notes.status_code == 200
    items = notes.json()
    assert len(items) == 1
    assert items[0]["is_read"] is False

    # Doctor cannot view scheduler's notifications by user_id
    assert client.get(f"{API}/notifications", params={"user_id": 1}, headers=doc_headers).status_code == 403

    # Scheduler marks notification read
    nid = items[0]["notification_id"]
    marked = client.patch(f"{API}/notifications/{nid}/read", headers=sched_headers)
    assert marked.status_code == 200
    assert marked.json()["is_read"] is True
    assert client.get(f"{API}/notifications", params={"unread_only": True}, headers=sched_headers).json() == []
    assert client.patch(f"{API}/notifications/9999/read", headers=sched_headers).status_code == 404


def test_sql_injection_string_stored_harmlessly(client, db_session, admin_headers):
    evil = "Ravi'); DROP TABLE surgery; --"
    resp = client.post(API, json=_payload(patient_name=evil), headers=admin_headers)
    assert resp.status_code == 201
    assert resp.json()["slot"]["patient_name"] == evil
    assert db_session.query(Surgery).count() == 1
