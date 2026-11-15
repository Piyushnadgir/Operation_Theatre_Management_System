"""TC-UX-01 (OT-NF-003), automated PROXY only.

The real requirement is a usability test with 5 trained schedulers using the UI
(see docs/usability_test_protocol.md). There is no frontend yet, so these tests can only show
that the API does not stand in the way: a UI could schedule a surgery with at most 8 requests,
and the server's part takes far less than 2 minutes.

They do NOT measure human interactions (clicks, typing) or human time.
"""
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.models import Equipment, Staff, StaffTypeEnum, Surgery, Theatre

MAX_INTERACTIONS = 8  # OT-NF-003 and SAD 4.5
MAX_SECONDS = 120  # OT-NF-003: at most 2 minutes
START = (datetime.now() + timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0)
END = START + timedelta(hours=2)
SCHEDULER = {"Authorization": f"Bearer {create_access_token({'sub': '1', 'role': 'scheduler'})}"}


class CountingClient:
    """Wraps TestClient and counts every request, the way a UI would make them."""

    def __init__(self, client):
        self.client = client
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append(f"GET {url}")
        return self.client.get(url, headers=SCHEDULER, **kwargs)

    def post(self, url, **kwargs):
        self.requests.append(f"POST {url}")
        return self.client.post(url, headers=SCHEDULER, **kwargs)


@pytest.fixture
def ui(db_session):
    def use_test_db():
        yield db_session

    app.dependency_overrides[get_db] = use_test_db
    yield CountingClient(TestClient(app))
    app.dependency_overrides.clear()


@pytest.fixture
def hospital(db_session):
    """Two theatres, two equipment items and one doctor and nurse, created by an admin beforehand."""
    rows = [
        Theatre(name="OT-1"),
        Theatre(name="OT-2"),
        Equipment(name="Ventilator", category="Respiratory"),
        Equipment(name="Monitor", category="Cardiac"),
        Staff(name="Dr. Rao", staff_type=StaffTypeEnum.doctor),
        Staff(name="Nurse Mary", staff_type=StaffTypeEnum.nurse),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return {"doctor": rows[4].staff_id, "nurse": rows[5].staff_id}


def slot():
    return {"start": START.isoformat(), "end": END.isoformat()}


def surgery_body(theatre_id, equipment_id, hospital):
    return {
        "patient_name": "Test Patient",
        "theatre_id": theatre_id,
        "start_time": START.isoformat(),
        "end_time": END.isoformat(),
        "doctor_ids": [hospital["doctor"]],
        "nurse_ids": [hospital["nurse"]],
        "equipment_ids": [equipment_id],
    }


def test_tc_ux_01_proxy_schedule_surgery_within_8_requests(ui, hospital, db_session):
    """Happy path: the screens a scheduling form needs, then one save."""
    started = time.perf_counter()

    theatres = ui.get("/api/v1/theatres").json()  # 1: fill the theatre drop-down
    theatre_id = theatres[0]["theatreId"]
    assert ui.get(f"/api/v1/theatres/{theatre_id}/availability", params=slot()).json()["available"]  # 2
    equipment = ui.get("/api/v1/equipment", params={"status": "available"}).json()  # 3: equipment list
    equipment_id = equipment[0]["equipmentId"]
    assert ui.get(f"/api/v1/equipment/{equipment_id}/availability", params=slot()).json()["available"]  # 4
    response = ui.post("/api/v1/surgeries", json=surgery_body(theatre_id, equipment_id, hospital))  # 5: save

    elapsed = time.perf_counter() - started
    assert response.status_code == 201
    assert db_session.query(Surgery).count() == 1
    # No /staff endpoint on main yet (Poorvi's branch), so a UI would need 1 more request
    # to fill the doctor and nurse lists: 5 + 1 = 6.
    assert len(ui.requests) + 1 <= MAX_INTERACTIONS, ui.requests
    assert elapsed < MAX_SECONDS / 10, f"server part took {elapsed:.2f}s"


def test_tc_ux_01_proxy_recovering_from_a_conflict_stays_within_8_requests(ui, hospital, db_session):
    """The first theatre is taken: the 409 names it, and the scheduler picks the other one."""
    ot1 = db_session.query(Theatre).filter(Theatre.name == "OT-1").one()
    db_session.add(Surgery(patient_name="Earlier", theatre_id=ot1.theatre_id, start_time=START, end_time=END))
    db_session.commit()
    started = time.perf_counter()

    theatres = ui.get("/api/v1/theatres").json()  # 1
    equipment_id = ui.get("/api/v1/equipment", params={"status": "available"}).json()[0]["equipmentId"]  # 2
    first = ui.post("/api/v1/surgeries", json=surgery_body(theatres[0]["theatreId"], equipment_id, hospital))  # 3
    assert first.status_code == 409
    assert first.json()["detail"]["conflicts"][0]["resource_type"] == "theatre"  # the message names the resource
    second_id = theatres[1]["theatreId"]
    assert ui.get(f"/api/v1/theatres/{second_id}/availability", params=slot()).json()["available"]  # 4
    second = ui.post("/api/v1/surgeries", json=surgery_body(second_id, equipment_id, hospital))  # 5

    elapsed = time.perf_counter() - started
    assert second.status_code == 201
    assert len(ui.requests) + 1 <= MAX_INTERACTIONS, ui.requests  # + 1 for the staff list, as above
    assert elapsed < MAX_SECONDS / 10
