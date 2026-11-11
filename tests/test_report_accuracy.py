"""TC-Rpt-03 (OT-NF-005): report totals equal manually computed totals.

A fixed, hand-made dataset is loaded. Every expected figure below was worked out by hand
(the arithmetic is in the comments) and is compared with the API output for exact equality.
The booked minutes are also cross-checked against an independent SQL sum over the raw tables.

Report range: 2026-05-04 08:00 to 20:00 = 12 hours = 720 minutes.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.models import Allocation, Equipment, Surgery, SurgeryStatusEnum, Theatre

URL = "/api/v1/reports/utilization"
FROM = "2026-05-04T08:00:00"
TO = "2026-05-04T20:00:00"
RANGE_MINUTES = 720
ADMIN = {"Authorization": f"Bearer {create_access_token({'sub': '1', 'role': 'admin'})}"}


def at(hour, minute=0, day=4):
    return datetime(2026, 5, day, hour, minute)


@pytest.fixture
def client(db_session):
    def use_test_db():
        yield db_session

    app.dependency_overrides[get_db] = use_test_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def dataset(db_session):
    """Theatres OT-A, OT-B, OT-C (idle) and OT-R (retired, idle, so not shown).
    Equipment E1 Ventilator, E2 Monitor, E3 Anaesthesia (only on a cancelled surgery),
    E4 Old Pump (retired, but booked in range, so shown) and E5 Old Scope (retired, idle, not shown).
    """
    ot_a, ot_b, ot_c, ot_r = (
        Theatre(name="OT-A"),
        Theatre(name="OT-B"),
        Theatre(name="OT-C"),
        Theatre(name="OT-R", is_active=False),
    )
    e1, e2, e3, e4, e5 = (
        Equipment(name="Ventilator"),
        Equipment(name="Monitor"),
        Equipment(name="Anaesthesia"),
        Equipment(name="Old Pump", is_active=False),
        Equipment(name="Old Scope", is_active=False),
    )
    db_session.add_all([ot_a, ot_b, ot_c, ot_r, e1, e2, e3, e4, e5])
    db_session.commit()

    def book(theatre, start, end, status, equipment):
        surgery = Surgery(patient_name="P", theatre_id=theatre.theatre_id, start_time=start, end_time=end, status=status)
        db_session.add(surgery)
        db_session.commit()
        for item in equipment:
            db_session.add(
                Allocation(
                    surgery_id=surgery.surgery_id,
                    equipment_id=item.equipment_id,
                    theatre_id=theatre.theatre_id,
                    start_time=start,
                    end_time=end,
                    released=status != SurgeryStatusEnum.scheduled,
                )
            )
        db_session.commit()

    done, booked, running, cancelled = (
        SurgeryStatusEnum.completed,
        SurgeryStatusEnum.scheduled,
        SurgeryStatusEnum.in_progress,
        SurgeryStatusEnum.cancelled,
    )
    book(ot_a, at(8, 30), at(10, 45), done, [e1, e2])  # S1: inside, 135 min
    book(ot_a, at(13), at(15, 20), booked, [e1])  # S2: inside, 140 min
    book(ot_a, at(11), at(12), cancelled, [e3])  # S3: cancelled, 0 min
    book(ot_a, at(5), at(8), done, [])  # S4: ends exactly at 08:00, 0 min
    book(ot_b, at(6), at(9, 15), done, [e4])  # S5: crosses the start, 08:00-09:15 = 75 min
    book(ot_b, at(18, 40), at(22), running, [e2])  # S6: crosses the end, 18:40-20:00 = 80 min
    book(ot_b, at(9, day=5), at(11, day=5), booked, [e1])  # S7: next day, outside, 0 min
    return {"OT-A": ot_a, "OT-B": ot_b, "OT-C": ot_c, "E1": e1, "E2": e2, "E3": e3, "E4": e4}


def rows(body, key):
    return {row["name"]: (row["bookedMinutes"], row["availableMinutes"], row["usagePercent"]) for row in body[key]}


def test_tc_rpt_03_report_matches_hand_computed_totals(client, dataset):
    response = client.get(URL, params={"from": FROM, "to": TO}, headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["rangeMinutes"] == RANGE_MINUTES

    assert rows(body, "theatres") == {
        "OT-A": (275, 720, 38.19),  # S1 135 + S2 140 = 275; 275 / 720 x 100 = 38.194.. -> 38.19
        "OT-B": (155, 720, 21.53),  # S5 75 + S6 80 = 155; 155 / 720 x 100 = 21.527.. -> 21.53
        "OT-C": (0, 720, 0.0),  # idle
    }  # OT-R is retired and idle, so it is not listed
    assert rows(body, "equipment") == {
        "Ventilator": (275, 720, 38.19),  # S1 135 + S2 140 = 275 (S7 is outside) -> 38.19
        "Monitor": (215, 720, 29.86),  # S1 135 + S6 80 = 215; 215 / 720 x 100 = 29.861.. -> 29.86
        "Anaesthesia": (0, 720, 0.0),  # only on cancelled S3
        "Old Pump": (75, 720, 10.42),  # S5 75; 75 / 720 x 100 = 10.416.. -> 10.42
    }  # Old Scope is retired and idle, so it is not listed

    assert body["totals"] == {
        # 275 + 155 + 0 = 430 of 3 x 720 = 2160; 430 / 2160 x 100 = 19.907.. -> 19.91
        "theatres": {"bookedMinutes": 430, "availableMinutes": 2160, "usagePercent": 19.91},
        # 275 + 215 + 0 + 75 = 565 of 4 x 720 = 2880; 565 / 2880 x 100 = 19.618.. -> 19.62
        "equipment": {"bookedMinutes": 565, "availableMinutes": 2880, "usagePercent": 19.62},
    }


def test_tc_rpt_03_theatre_filter_matches_hand_computed_totals(client, dataset):
    params = {"from": FROM, "to": TO, "theatreId": dataset["OT-B"].theatre_id}
    body = client.get(URL, params=params, headers=ADMIN).json()

    assert rows(body, "theatres") == {"OT-B": (155, 720, 21.53)}  # 75 + 80, as above
    assert rows(body, "equipment") == {
        "Ventilator": (0, 720, 0.0),  # its OT-B booking (S7) is outside the range
        "Monitor": (80, 720, 11.11),  # S6 only; 80 / 720 x 100 = 11.111.. -> 11.11
        "Anaesthesia": (0, 720, 0.0),
        "Old Pump": (75, 720, 10.42),  # S5
    }
    # 0 + 80 + 0 + 75 = 155 of 2880; 155 / 2880 x 100 = 5.381.. -> 5.38
    assert body["totals"]["equipment"] == {"bookedMinutes": 155, "availableMinutes": 2880, "usagePercent": 5.38}


# Independent check: clip and sum in SQL straight from the raw tables, without the report code.
# MAX/MIN clip each row to the range; strftime('%s') turns times into seconds.
CLIPPED_MINUTES = (
    "(strftime('%s', MIN({t}.end_time, :to)) - strftime('%s', MAX({t}.start_time, :from))) / 60"
)
THEATRE_SQL = f"""
    SELECT theatre_id, SUM({CLIPPED_MINUTES.format(t='surgery')})
    FROM surgery
    WHERE status != 'cancelled' AND start_time < :to AND end_time > :from
    GROUP BY theatre_id
"""
EQUIPMENT_SQL = f"""
    SELECT allocation.equipment_id, SUM({CLIPPED_MINUTES.format(t='allocation')})
    FROM allocation JOIN surgery ON surgery.surgery_id = allocation.surgery_id
    WHERE surgery.status != 'cancelled' AND allocation.replaced = 0
      AND allocation.start_time < :to AND allocation.end_time > :from
    GROUP BY allocation.equipment_id
"""


def test_tc_rpt_03_report_matches_independent_sql_sum(client, db_session, dataset):
    # Same text format as SQLAlchemy stores, so MIN/MAX compare like with like
    params = {"from": "2026-05-04 08:00:00.000000", "to": "2026-05-04 20:00:00.000000"}
    sql_theatres = dict(db_session.execute(text(THEATRE_SQL), params).all())
    sql_equipment = dict(db_session.execute(text(EQUIPMENT_SQL), params).all())

    body = client.get(URL, params={"from": FROM, "to": TO}, headers=ADMIN).json()
    report_theatres = {row["theatreId"]: row["bookedMinutes"] for row in body["theatres"] if row["bookedMinutes"]}
    report_equipment = {row["equipmentId"]: row["bookedMinutes"] for row in body["equipment"] if row["bookedMinutes"]}

    assert report_theatres == sql_theatres
    assert report_equipment == sql_equipment
    assert body["totals"]["theatres"]["bookedMinutes"] == sum(sql_theatres.values())
    assert body["totals"]["equipment"]["bookedMinutes"] == sum(sql_equipment.values())
