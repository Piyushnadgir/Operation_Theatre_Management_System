"""API tests for /equipment, /theatres and /allocations (real JWTs, test SQLite DB).

Test names start with the Test Plan case they trace to:
TC-Eq-01 (OT-F-040), TC-Eq-02 (OT-F-041), TC-Eq-03 (OT-F-042).
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.models import Allocation, Surgery, SurgeryStatusEnum

START = datetime.now().replace(microsecond=0) + timedelta(days=7)
END = START + timedelta(hours=2)
BASE = "/api/v1"


def headers(role):
    token = create_access_token({"sub": "1", "role": role})
    return {"Authorization": f"Bearer {token}"}


ADMIN = headers("admin")
SCHEDULER = headers("scheduler")
DOCTOR = headers("doctor")
NURSE = headers("nurse")


@pytest.fixture
def client(db_session):
    def use_test_db():
        yield db_session

    app.dependency_overrides[get_db] = use_test_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def create_equipment(client, **fields):
    body = {"name": "Ventilator", "category": "Respiratory", **fields}
    response = client.post(f"{BASE}/equipment", json=body, headers=ADMIN)
    assert response.status_code == 201
    return response.json()["equipmentId"]


def create_theatre(client, name="OT-1"):
    response = client.post(f"{BASE}/theatres", json={"name": name}, headers=ADMIN)
    assert response.status_code == 201
    return response.json()["theatreId"]


def surgery_body(theatre_id, **fields):
    return {
        "patient_name": "Test",
        "theatre_id": theatre_id,
        "start_time": START.isoformat(),
        "end_time": END.isoformat(),
        **fields,
    }


def create_surgery(client, theatre_id, **fields):
    response = client.post(f"{BASE}/surgeries", json=surgery_body(theatre_id, **fields), headers=SCHEDULER)
    assert response.status_code == 201
    return response.json()["surgery_id"]


def time_range(start=START, end=END):
    return {"start": start.isoformat(), "end": end.isoformat()}


# ---------- TC-Eq-01: equipment ----------


def test_tc_eq_01_create_equipment(client):
    response = client.post(f"{BASE}/equipment", json={"name": "  Monitor ", "category": "Cardiac"}, headers=ADMIN)
    assert response.status_code == 201
    assert response.json() == {
        "equipmentId": response.json()["equipmentId"],
        "name": "Monitor",
        "category": "Cardiac",
        "status": "available",
        "isActive": True,
    }


def test_tc_eq_01_category_is_optional(client):
    response = client.post(f"{BASE}/equipment", json={"name": "Monitor"}, headers=ADMIN)
    assert response.status_code == 201
    assert response.json()["category"] is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {"name": "Monitor", "category": ""},
        {"name": "Monitor", "status": "broken"},
        {"name": "Monitor", "status": "in_use"},
    ],
)
def test_tc_eq_01_create_invalid_input_returns_400(client, body):
    response = client.post(f"{BASE}/equipment", json=body, headers=ADMIN)
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "Bad Request"


def test_tc_eq_01_malformed_json_returns_400(client):
    response = client.post(f"{BASE}/equipment", content="{not json", headers=ADMIN)
    assert response.status_code == 400


def test_tc_eq_01_injection_string_is_stored_harmlessly(client):
    """OT-SR-006: the text is kept as plain data and the table survives."""
    name = "x'; DROP TABLE equipment; --"
    create_equipment(client, name=name)
    assert client.get(f"{BASE}/equipment", headers=ADMIN).json()[0]["name"] == name


def test_tc_eq_01_list_with_filters(client):
    create_equipment(client, name="A", category="Cardiac")
    create_equipment(client, name="B", category="Respiratory", status="maintenance")

    all_items = client.get(f"{BASE}/equipment", headers=NURSE)
    assert all_items.status_code == 200
    assert len(all_items.json()) == 2

    by_status = client.get(f"{BASE}/equipment", params={"status": "maintenance"}, headers=NURSE)
    assert [item["name"] for item in by_status.json()] == ["B"]

    by_category = client.get(f"{BASE}/equipment", params={"category": "Cardiac"}, headers=NURSE)
    assert [item["name"] for item in by_category.json()] == ["A"]


def test_tc_eq_01_list_invalid_status_returns_400(client):
    response = client.get(f"{BASE}/equipment", params={"status": "broken"}, headers=ADMIN)
    assert response.status_code == 400


def test_tc_eq_01_update_equipment(client):
    equipment_id = create_equipment(client)
    response = client.put(
        f"{BASE}/equipment/{equipment_id}",
        json={"name": "New", "category": "Other", "status": "maintenance"},
        headers=ADMIN,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New"
    assert response.json()["category"] == "Other"
    assert response.json()["status"] == "maintenance"


@pytest.mark.parametrize("body", [{"name": ""}, {"status": "broken"}, {"status": "in_use"}])
def test_tc_eq_01_update_invalid_input_returns_400(client, body):
    equipment_id = create_equipment(client)
    assert client.put(f"{BASE}/equipment/{equipment_id}", json=body, headers=ADMIN).status_code == 400


def test_tc_eq_01_update_missing_returns_404(client):
    assert client.put(f"{BASE}/equipment/999", json={"name": "New"}, headers=ADMIN).status_code == 404


def test_tc_eq_01_retire_equipment_keeps_the_record(client):
    equipment_id = create_equipment(client)
    response = client.delete(f"{BASE}/equipment/{equipment_id}", headers=ADMIN)
    assert response.status_code == 200
    assert response.json() == {"status": "deactivated"}
    assert client.get(f"{BASE}/equipment", headers=ADMIN).json() == []
    retired = client.get(f"{BASE}/equipment", params={"includeRetired": True}, headers=ADMIN).json()
    assert retired[0]["isActive"] is False


def test_tc_eq_01_retire_with_future_allocation_returns_409(client):
    equipment_id = create_equipment(client)
    create_surgery(client, create_theatre(client), equipment_ids=[equipment_id])
    response = client.delete(f"{BASE}/equipment/{equipment_id}", headers=ADMIN)
    assert response.status_code == 409
    assert response.json()["detail"]["conflicts"][0]["resource_id"] == equipment_id


def test_tc_eq_01_retire_missing_returns_404(client):
    assert client.delete(f"{BASE}/equipment/999", headers=ADMIN).status_code == 404


# ---------- TC-Eq-01: theatres ----------


def test_tc_eq_01_create_list_and_rename_theatre(client):
    theatre_id = create_theatre(client)
    renamed = client.put(f"{BASE}/theatres/{theatre_id}", json={"name": "OT-9"}, headers=ADMIN)
    assert renamed.status_code == 200
    response = client.get(f"{BASE}/theatres", headers=DOCTOR)
    assert response.status_code == 200
    assert response.json() == [{"theatreId": theatre_id, "name": "OT-9", "status": "available", "isActive": True}]


def test_tc_eq_01_duplicate_theatre_name_returns_409(client):
    create_theatre(client)
    assert client.post(f"{BASE}/theatres", json={"name": "OT-1"}, headers=ADMIN).status_code == 409


@pytest.mark.parametrize("body", [{}, {"name": " "}, {"name": "OT-2", "status": "broken"}, {"name": "OT-2", "status": "occupied"}])
def test_tc_eq_01_create_theatre_invalid_returns_400(client, body):
    assert client.post(f"{BASE}/theatres", json=body, headers=ADMIN).status_code == 400


@pytest.mark.parametrize("status", ["cleaning", "maintenance", "available"])
def test_tc_eq_01_patch_theatre_status(client, status):
    theatre_id = create_theatre(client)
    response = client.patch(f"{BASE}/theatres/{theatre_id}/status", json={"status": status}, headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["status"] == status


@pytest.mark.parametrize("status", ["broken", "occupied", "in_use"])
def test_tc_eq_01_patch_invalid_theatre_status_returns_400(client, status):
    theatre_id = create_theatre(client)
    response = client.patch(f"{BASE}/theatres/{theatre_id}/status", json={"status": status}, headers=ADMIN)
    assert response.status_code == 400


def test_tc_eq_01_theatre_writes_on_missing_return_404(client):
    assert client.put(f"{BASE}/theatres/999", json={"name": "X"}, headers=ADMIN).status_code == 404
    assert client.patch(f"{BASE}/theatres/999/status", json={"status": "cleaning"}, headers=ADMIN).status_code == 404
    assert client.delete(f"{BASE}/theatres/999", headers=ADMIN).status_code == 404


def test_tc_eq_01_retire_theatre(client):
    theatre_id = create_theatre(client)
    response = client.delete(f"{BASE}/theatres/{theatre_id}", headers=ADMIN)
    assert response.status_code == 200
    assert response.json() == {"status": "deactivated"}
    assert client.get(f"{BASE}/theatres", headers=ADMIN).json() == []
    assert len(client.get(f"{BASE}/theatres", params={"includeRetired": True}, headers=ADMIN).json()) == 1


def test_tc_eq_01_retire_theatre_with_future_surgery_returns_409(client):
    theatre_id = create_theatre(client)
    create_surgery(client, theatre_id)
    assert client.delete(f"{BASE}/theatres/{theatre_id}", headers=ADMIN).status_code == 409


# ---------- TC-Eq-01: role checks (OT-SR-003) ----------

ADMIN_ONLY = [
    ("post", "/equipment", {"name": "X"}),
    ("put", "/equipment/1", {"name": "X"}),
    ("delete", "/equipment/1", None),
    ("post", "/theatres", {"name": "X"}),
    ("put", "/theatres/1", {"name": "X"}),
    ("patch", "/theatres/1/status", {"status": "cleaning"}),
    ("delete", "/theatres/1", None),
]


@pytest.mark.parametrize("method, path, body", ADMIN_ONLY)
@pytest.mark.parametrize("role", [SCHEDULER, DOCTOR, NURSE], ids=["scheduler", "doctor", "nurse"])
def test_tc_eq_01_writes_are_admin_only(client, method, path, body, role):
    response = client.request(method, f"{BASE}{path}", json=body, headers=role)
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/equipment", "/theatres"])
def test_tc_eq_01_reads_need_a_valid_token(client, path):
    assert client.get(f"{BASE}{path}", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get(f"{BASE}{path}").status_code in (401, 403)  # see the notes: deps.py gives 403 here


# ---------- TC-Eq-01: equipment under maintenance cannot be booked ----------


def test_tc_eq_01_post_surgery_with_maintenance_equipment_returns_409(client, db_session):
    equipment_id = create_equipment(client, status="maintenance")
    theatre_id = create_theatre(client)
    response = client.post(
        f"{BASE}/surgeries", json=surgery_body(theatre_id, equipment_ids=[equipment_id]), headers=SCHEDULER
    )
    assert response.status_code == 409
    conflict = response.json()["detail"]["conflicts"][0]
    assert conflict["resource_type"] == "equipment"
    assert conflict["resource_id"] == equipment_id
    assert db_session.query(Surgery).count() == 0


def test_tc_eq_01_post_surgery_with_retired_equipment_returns_409(client):
    equipment_id = create_equipment(client)
    client.delete(f"{BASE}/equipment/{equipment_id}", headers=ADMIN)
    response = client.post(
        f"{BASE}/surgeries", json=surgery_body(create_theatre(client), equipment_ids=[equipment_id]), headers=SCHEDULER
    )
    assert response.status_code == 409


def test_tc_eq_01_equipment_can_be_booked_after_maintenance_clears(client):
    equipment_id = create_equipment(client, status="maintenance")
    client.put(f"{BASE}/equipment/{equipment_id}", json={"status": "available"}, headers=ADMIN)
    create_surgery(client, create_theatre(client), equipment_ids=[equipment_id])


# ---------- TC-Eq-02: availability ----------


def test_tc_eq_02_equipment_availability_any_role(client):
    equipment_id = create_equipment(client)
    response = client.get(f"{BASE}/equipment/{equipment_id}/availability", params=time_range(), headers=NURSE)
    assert response.status_code == 200
    assert response.json() == {"available": True, "status": "available", "reasons": []}


def test_tc_eq_02_availability_follows_bookings(client):
    equipment_id = create_equipment(client)
    theatre_id = create_theatre(client)
    create_surgery(client, theatre_id, equipment_ids=[equipment_id])

    for path in (f"/equipment/{equipment_id}", f"/theatres/{theatre_id}"):
        url = f"{BASE}{path}/availability"
        assert client.get(url, params=time_range(), headers=NURSE).json()["available"] is False
        # Touching boundaries are not a conflict
        after = time_range(END, END + timedelta(hours=1))
        before = time_range(START - timedelta(hours=1), START)
        assert client.get(url, params=after, headers=NURSE).json()["available"] is True
        assert client.get(url, params=before, headers=NURSE).json()["available"] is True


def test_tc_eq_02_availability_follows_status(client):
    equipment_id = create_equipment(client, status="maintenance")
    theatre_id = create_theatre(client)
    client.patch(f"{BASE}/theatres/{theatre_id}/status", json={"status": "maintenance"}, headers=ADMIN)
    for path in (f"/equipment/{equipment_id}", f"/theatres/{theatre_id}"):
        body = client.get(f"{BASE}{path}/availability", params=time_range(), headers=NURSE).json()
        assert body == {"available": False, "status": "maintenance", "reasons": ["under maintenance"]}


@pytest.mark.parametrize("resource", ["equipment", "theatres"])
@pytest.mark.parametrize(
    "params",
    [
        time_range(END, START),  # end before start
        time_range(START, START),  # end equal to start
        {"start": START.isoformat()},  # end missing
        {"start": "not-a-date", "end": END.isoformat()},
    ],
)
def test_tc_eq_02_bad_range_returns_400(client, resource, params):
    item_id = create_equipment(client) if resource == "equipment" else create_theatre(client)
    response = client.get(f"{BASE}/{resource}/{item_id}/availability", params=params, headers=ADMIN)
    assert response.status_code == 400


def test_tc_eq_02_mixed_timezone_range_does_not_crash(client):
    equipment_id = create_equipment(client)
    params = {"start": START.isoformat() + "+05:30", "end": END.isoformat()}
    response = client.get(f"{BASE}/equipment/{equipment_id}/availability", params=params, headers=ADMIN)
    assert response.status_code == 200


@pytest.mark.parametrize("resource", ["equipment", "theatres"])
def test_tc_eq_02_missing_item_returns_404(client, resource):
    response = client.get(f"{BASE}/{resource}/999/availability", params=time_range(), headers=ADMIN)
    assert response.status_code == 404


# ---------- TC-Eq-03: allocate and release ----------


def test_tc_eq_03_allocate_then_release_end_to_end(client, db_session):
    """AC-OT-F-042: allocated during the surgery, available again afterwards."""
    equipment_id = create_equipment(client)
    theatre_id = create_theatre(client)
    surgery_id = create_surgery(client, theatre_id)
    url = f"{BASE}/equipment/{equipment_id}/availability"
    assert client.get(url, params=time_range(), headers=SCHEDULER).json()["available"] is True

    response = client.post(
        f"{BASE}/allocations",
        json={"surgeryId": surgery_id, "theatreId": theatre_id, "equipmentIds": [equipment_id]},
        headers=SCHEDULER,
    )
    assert response.status_code == 201
    allocation = response.json()[0]
    assert allocation["surgeryId"] == surgery_id
    assert allocation["equipmentId"] == equipment_id
    assert allocation["released"] is False
    assert client.get(url, params=time_range(), headers=SCHEDULER).json()["available"] is False

    release_url = f"{BASE}/allocations/{allocation['allocationId']}/release"
    released = client.post(release_url, headers=SCHEDULER)
    assert released.status_code == 200
    assert released.json() == {"status": "released"}
    assert client.get(url, params=time_range(), headers=SCHEDULER).json()["available"] is True

    # Releasing twice has no further effect
    assert client.post(release_url, headers=SCHEDULER).json() == {"status": "released"}
    assert db_session.query(Allocation).count() == 1


def test_tc_eq_03_duplicate_ids_in_request_allocate_once(client, db_session):
    equipment_id = create_equipment(client)
    theatre_id = create_theatre(client)
    surgery_id = create_surgery(client, theatre_id)
    body = {"surgeryId": surgery_id, "theatreId": theatre_id, "equipmentIds": [equipment_id, equipment_id]}
    assert client.post(f"{BASE}/allocations", json=body, headers=ADMIN).status_code == 201
    assert db_session.query(Allocation).count() == 1


def test_tc_eq_03_conflict_returns_409_and_creates_nothing(client, db_session):
    good_id = create_equipment(client, name="Good")
    broken_id = create_equipment(client, name="Broken", status="maintenance")
    theatre_id = create_theatre(client)
    surgery_id = create_surgery(client, theatre_id)
    response = client.post(
        f"{BASE}/allocations",
        json={"surgeryId": surgery_id, "theatreId": theatre_id, "equipmentIds": [good_id, broken_id]},
        headers=SCHEDULER,
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "Conflict"
    assert detail["message"] == "Resource conflict detected"
    assert detail["conflicts"] == [
        {
            "resource_type": "equipment",
            "resource_id": broken_id,
            "message": f"Equipment {broken_id}: under maintenance",
        }
    ]
    assert db_session.query(Allocation).count() == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"surgeryId": 1, "theatreId": 1},
        {"surgeryId": 1, "theatreId": 1, "equipmentIds": []},
        {"surgeryId": "abc", "theatreId": 1, "equipmentIds": [1]},
    ],
)
def test_tc_eq_03_invalid_body_returns_400(client, body):
    assert client.post(f"{BASE}/allocations", json=body, headers=SCHEDULER).status_code == 400


def test_tc_eq_03_finished_surgery_returns_400(client, db_session):
    equipment_id = create_equipment(client)
    theatre_id = create_theatre(client)
    surgery_id = create_surgery(client, theatre_id)
    db_session.get(Surgery, surgery_id).status = SurgeryStatusEnum.completed
    db_session.commit()
    body = {"surgeryId": surgery_id, "theatreId": theatre_id, "equipmentIds": [equipment_id]}
    assert client.post(f"{BASE}/allocations", json=body, headers=SCHEDULER).status_code == 400


def test_tc_eq_03_missing_records_return_404(client):
    equipment_id = create_equipment(client)
    theatre_id = create_theatre(client)
    body = {"surgeryId": 999, "theatreId": theatre_id, "equipmentIds": [equipment_id]}
    assert client.post(f"{BASE}/allocations", json=body, headers=SCHEDULER).status_code == 404
    assert client.post(f"{BASE}/allocations/999/release", headers=SCHEDULER).status_code == 404


@pytest.mark.parametrize("role", [DOCTOR, NURSE], ids=["doctor", "nurse"])
def test_tc_eq_03_doctors_and_nurses_cannot_allocate(client, role):
    body = {"surgeryId": 1, "theatreId": 1, "equipmentIds": [1]}
    assert client.post(f"{BASE}/allocations", json=body, headers=role).status_code == 403
    assert client.post(f"{BASE}/allocations/1/release", headers=role).status_code == 403


def test_tc_eq_03_cancel_surgery_then_available_again(client):
    equipment_id = create_equipment(client)
    theatre_id = create_theatre(client)
    surgery_id = create_surgery(client, theatre_id, equipment_ids=[equipment_id])
    equipment_url = f"{BASE}/equipment/{equipment_id}/availability"
    theatre_url = f"{BASE}/theatres/{theatre_id}/availability"
    assert client.get(equipment_url, params=time_range(), headers=NURSE).json()["available"] is False
    assert client.get(theatre_url, params=time_range(), headers=NURSE).json()["available"] is False

    assert client.delete(f"{BASE}/surgeries/{surgery_id}", headers=SCHEDULER).status_code == 200

    assert client.get(equipment_url, params=time_range(), headers=NURSE).json()["available"] is True
    assert client.get(theatre_url, params=time_range(), headers=NURSE).json()["available"] is True
