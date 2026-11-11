"""API tests for GET /api/v1/reports/utilization (OT-F-043).

TC-Rpt-01: the report covers all theatres and equipment.
TC-Rpt-02: date filtering and the 400/403/404 cases.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.models import Allocation, Equipment, Surgery, SurgeryStatusEnum, Theatre

URL = "/api/v1/reports/utilization"
RANGE = {"from": "2026-03-02T08:00:00", "to": "2026-03-02T18:00:00"}


def headers(role):
    return {"Authorization": f"Bearer {create_access_token({'sub': '1', 'role': role})}"}


@pytest.fixture
def client(db_session):
    def use_test_db():
        yield db_session

    app.dependency_overrides[get_db] = use_test_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def seeded(db_session):
    """OT-1 has a 3-hour surgery using the ventilator. OT-2 and the monitor are idle."""
    ot1, ot2 = Theatre(name="OT-1"), Theatre(name="OT-2")
    vent, monitor = Equipment(name="Ventilator"), Equipment(name="Monitor")
    db_session.add_all([ot1, ot2, vent, monitor])
    db_session.commit()
    surgery = Surgery(
        patient_name="P",
        theatre_id=ot1.theatre_id,
        start_time=datetime(2026, 3, 2, 9),
        end_time=datetime(2026, 3, 2, 12),
        status=SurgeryStatusEnum.completed,
    )
    db_session.add(surgery)
    db_session.commit()
    db_session.add(
        Allocation(
            surgery_id=surgery.surgery_id,
            equipment_id=vent.equipment_id,
            theatre_id=ot1.theatre_id,
            start_time=surgery.start_time,
            end_time=surgery.end_time,
            released=True,
        )
    )
    db_session.commit()
    return {"ot1": ot1.theatre_id, "ot2": ot2.theatre_id, "vent": vent.equipment_id, "monitor": monitor.equipment_id}


@pytest.mark.parametrize("role", ["admin", "scheduler"])
def test_tc_rpt_01_report_for_all_theatres_and_equipment(client, seeded, role):
    response = client.get(URL, params=RANGE, headers=headers(role))
    assert response.status_code == 200
    body = response.json()
    assert body["start"] == "2026-03-02T08:00:00"
    assert body["end"] == "2026-03-02T18:00:00"
    assert body["rangeMinutes"] == 600
    assert body["theatres"] == [
        {"theatreId": seeded["ot1"], "name": "OT-1", "bookedMinutes": 180, "availableMinutes": 600, "usagePercent": 30.0},
        {"theatreId": seeded["ot2"], "name": "OT-2", "bookedMinutes": 0, "availableMinutes": 600, "usagePercent": 0.0},
    ]
    assert body["equipment"] == [
        {"equipmentId": seeded["vent"], "name": "Ventilator", "bookedMinutes": 180, "availableMinutes": 600, "usagePercent": 30.0},
        {"equipmentId": seeded["monitor"], "name": "Monitor", "bookedMinutes": 0, "availableMinutes": 600, "usagePercent": 0.0},
    ]
    assert body["totals"]["theatres"] == {"bookedMinutes": 180, "availableMinutes": 1200, "usagePercent": 15.0}


def test_tc_rpt_02_date_only_values_mean_midnight(client, seeded):
    response = client.get(URL, params={"from": "2026-03-02", "to": "2026-03-03"}, headers=headers("admin"))
    assert response.status_code == 200
    assert response.json()["rangeMinutes"] == 1440
    assert response.json()["theatres"][0]["usagePercent"] == 12.5  # 180 / 1440


def test_tc_rpt_02_range_with_no_bookings(client, seeded):
    params = {"from": "2026-04-01", "to": "2026-04-02"}
    body = client.get(URL, params=params, headers=headers("admin")).json()
    assert all(row["usagePercent"] == 0.0 for row in body["theatres"] + body["equipment"])


def test_tc_rpt_02_theatre_filter(client, seeded):
    params = {**RANGE, "theatreId": seeded["ot2"]}
    body = client.get(URL, params=params, headers=headers("admin")).json()
    assert [row["name"] for row in body["theatres"]] == ["OT-2"]
    assert all(row["bookedMinutes"] == 0 for row in body["equipment"])


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-03-02T18:00:00", "to": "2026-03-02T08:00:00"},  # to before from
        {"from": "2026-03-02", "to": "2026-03-02"},  # to equal to from
        {"from": "02-03-2026", "to": "2026-03-03"},  # bad date
        {"from": "2026-03-02", "to": "tomorrow"},
        {"from": "2026-03-02"},  # to missing
        {},
        {**RANGE, "theatreId": "abc"},
    ],
)
def test_tc_rpt_02_bad_input_returns_400(client, params):
    response = client.get(URL, params=params, headers=headers("admin"))
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "Bad Request"


def test_tc_rpt_02_unknown_theatre_returns_404(client):
    assert client.get(URL, params={**RANGE, "theatreId": 999}, headers=headers("admin")).status_code == 404


@pytest.mark.parametrize("role", ["doctor", "nurse"])
def test_tc_rpt_02_doctors_and_nurses_get_403(client, role):
    assert client.get(URL, params=RANGE, headers=headers(role)).status_code == 403


def test_tc_rpt_02_invalid_token_is_rejected(client):
    assert client.get(URL, params=RANGE, headers={"Authorization": "Bearer nope"}).status_code == 401
