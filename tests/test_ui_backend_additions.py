"""Small read-side additions the Web UI needs (SAD 4.5 and Figure 4.3).

- POST /staff accepts an optional user_id, linking a doctor or nurse to their login
- GET /me/surgeries: a doctor or nurse sees their own upcoming surgeries
- GET /allocations: the board and the reschedule form need allocation ids
"""
from datetime import datetime, timedelta

import pytest

from app.models.models import (
    Allocation,
    Equipment,
    RoleEnum,
    StaffTypeEnum,
    Surgery,
    SurgeryStaff,
    SurgeryStatusEnum,
    Theatre,
    User,
)
from tests.api_fixtures import admin_headers, client, headers_for  # noqa: F401
from tests.helpers import make_staff

SOON = datetime.now().replace(microsecond=0) + timedelta(days=2)


def user_id(db, username):
    return db.query(User).filter(User.username == username).one().user_id


def add_surgery(db, theatre, start, status=SurgeryStatusEnum.scheduled, staff=()):
    surgery = Surgery(patient_name="P", theatre_id=theatre.theatre_id, start_time=start,
                      end_time=start + timedelta(hours=2), status=status)
    db.add(surgery)
    db.commit()
    for person in staff:
        db.add(SurgeryStaff(surgery_id=surgery.surgery_id, staff_id=person.staff_id))
    db.commit()
    return surgery


# ---------- POST /staff with user_id ----------


def test_staff_can_be_linked_to_a_login(client, db_session, admin_headers):
    headers_for(client, db_session, "drlee", RoleEnum.doctor)
    body = {"name": "Dr. Lee", "staff_type": "doctor", "user_id": user_id(db_session, "drlee")}
    response = client.post("/api/v1/staff", json=body, headers=admin_headers)
    assert response.status_code == 201
    assert response.json()["user_id"] == user_id(db_session, "drlee")


def test_staff_without_login_still_works(client, admin_headers):
    response = client.post("/api/v1/staff", json={"name": "Nurse Ann", "staff_type": "nurse"}, headers=admin_headers)
    assert response.status_code == 201
    assert response.json()["user_id"] is None


def test_staff_with_unknown_login_is_rejected(client, admin_headers):
    body = {"name": "Dr. X", "staff_type": "doctor", "user_id": 999}
    response = client.post("/api/v1/staff", json=body, headers=admin_headers)
    assert response.status_code == 400
    assert response.json()["detail"]["message"] == "User 999 not found"


# ---------- GET /me/surgeries ----------


@pytest.fixture
def linked_doctor(client, db_session):
    headers = headers_for(client, db_session, "drlee", RoleEnum.doctor)
    doctor = make_staff(db_session, name="Dr. Lee")
    doctor.user_id = user_id(db_session, "drlee")
    db_session.commit()
    return headers, doctor


def test_doctor_sees_own_upcoming_surgeries_in_time_order(client, db_session, linked_doctor):
    headers, doctor = linked_doctor
    other = make_staff(db_session, name="Dr. Other")
    theatre = Theatre(name="OT-1")
    db_session.add(theatre)
    db_session.commit()
    later = add_surgery(db_session, theatre, SOON + timedelta(days=1), staff=[doctor])
    first = add_surgery(db_session, theatre, SOON, staff=[doctor])
    add_surgery(db_session, theatre, SOON + timedelta(hours=3), staff=[other])  # not theirs
    add_surgery(db_session, theatre, SOON - timedelta(days=10), staff=[doctor])  # already over
    add_surgery(db_session, theatre, SOON + timedelta(days=2), SurgeryStatusEnum.cancelled, staff=[doctor])

    response = client.get("/api/v1/me/surgeries", headers=headers)

    assert response.status_code == 200
    assert [s["surgery_id"] for s in response.json()] == [first.surgery_id, later.surgery_id]


def test_nurse_without_staff_record_gets_empty_list(client, db_session):
    headers = headers_for(client, db_session, "nurse1", RoleEnum.nurse)
    assert client.get("/api/v1/me/surgeries", headers=headers).json() == []


def test_my_surgeries_needs_login(client):
    assert client.get("/api/v1/me/surgeries").status_code == 401


# ---------- GET /allocations ----------


@pytest.fixture
def allocations(db_session):
    theatre, monitor, pump = Theatre(name="OT-1"), Equipment(name="Monitor"), Equipment(name="Pump")
    db_session.add_all([theatre, monitor, pump])
    db_session.commit()
    surgery = add_surgery(db_session, theatre, SOON)
    other = add_surgery(db_session, theatre, SOON + timedelta(hours=3))

    def allocate(surgery_row, item, released=False, replaced=False):
        row = Allocation(surgery_id=surgery_row.surgery_id, equipment_id=item.equipment_id,
                         theatre_id=theatre.theatre_id, start_time=surgery_row.start_time,
                         end_time=surgery_row.end_time, released=released, replaced=replaced)
        db_session.add(row)
        db_session.commit()
        return row.allocation_id

    return {
        "surgery": surgery.surgery_id,
        "monitor": monitor.equipment_id,
        "current": allocate(surgery, monitor),
        "released": allocate(surgery, pump, released=True),
        "replaced": allocate(surgery, monitor, released=True, replaced=True),
        "other": allocate(other, monitor),
    }


def test_list_allocations_by_surgery(client, admin_headers, allocations):
    response = client.get("/api/v1/allocations", params={"surgeryId": allocations["surgery"]}, headers=admin_headers)
    assert response.status_code == 200
    assert [a["allocationId"] for a in response.json()] == [allocations["current"]]


def test_list_allocations_including_released_never_shows_replaced(client, admin_headers, allocations):
    params = {"surgeryId": allocations["surgery"], "includeReleased": True}
    ids = [a["allocationId"] for a in client.get("/api/v1/allocations", params=params, headers=admin_headers).json()]
    assert ids == [allocations["current"], allocations["released"]]


def test_list_allocations_by_equipment(client, admin_headers, allocations):
    params = {"equipmentId": allocations["monitor"]}
    ids = [a["allocationId"] for a in client.get("/api/v1/allocations", params=params, headers=admin_headers).json()]
    assert ids == [allocations["current"], allocations["other"]]


def test_scheduler_can_list_allocations(client, db_session, allocations):
    headers = headers_for(client, db_session, "sched", RoleEnum.scheduler)
    assert client.get("/api/v1/allocations", headers=headers).status_code == 200


@pytest.mark.parametrize("role", [RoleEnum.doctor, RoleEnum.nurse])
def test_doctors_and_nurses_cannot_list_allocations(client, db_session, role):
    headers = headers_for(client, db_session, f"user_{role.value}", role)
    assert client.get("/api/v1/allocations", headers=headers).status_code == 403
