"""TC-OPS-01 (OT-NF-004): surgery, allocation and audit records are retained for at least 5 years.

Acceptance: records older than 1 year remain retrievable, and nothing deletes them automatically
before 5 years. Rows dated 2 and 6 years ago are read back through the service layer and the API.
A code scan fails if any code in app/ deletes these rows or runs a background job.
"""
import ast
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.models import (
    Allocation,
    AuditLog,
    Equipment,
    Surgery,
    SurgeryStatusEnum,
    Theatre,
)
from app.services.equipment_service import EquipmentService
from app.services.report_service import ReportService
from app.services.surgery_service import SurgeryService

APP_DIR = Path(__file__).resolve().parent.parent / "app"
TODAY = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
AGES = {"2 years": TODAY - timedelta(days=2 * 365), "6 years": TODAY - timedelta(days=6 * 365)}


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
def old_records(db_session):
    """For each age: a completed 2-hour surgery, its released allocation and an audit entry."""
    theatre, equipment = Theatre(name="OT-Old"), Equipment(name="Old Ventilator")
    db_session.add_all([theatre, equipment])
    db_session.commit()
    records = {}
    for label, start in AGES.items():
        surgery = Surgery(
            patient_name=f"Patient {label}",
            theatre_id=theatre.theatre_id,
            start_time=start,
            end_time=start + timedelta(hours=2),
            status=SurgeryStatusEnum.completed,
        )
        db_session.add(surgery)
        db_session.commit()
        allocation = Allocation(
            surgery_id=surgery.surgery_id,
            equipment_id=equipment.equipment_id,
            theatre_id=theatre.theatre_id,
            start_time=surgery.start_time,
            end_time=surgery.end_time,
            released=True,
        )
        audit = AuditLog(user_id=1, action="allocate", entity_type="allocation", timestamp=start)
        db_session.add_all([allocation, audit])
        db_session.commit()
        records[label] = {
            "start": start,
            "surgery_id": surgery.surgery_id,
            "allocation_id": allocation.allocation_id,
            "audit_id": audit.log_id,
        }
    return records


def count_rows(db):
    return (db.query(Surgery).count(), db.query(Allocation).count(), db.query(AuditLog).count())


# ---------- old records are retrievable ----------


@pytest.mark.parametrize("age", AGES)
def test_tc_ops_01_old_records_retrievable_through_service_layer(db_session, old_records, age):
    record = old_records[age]
    surgeries = SurgeryService(db_session).get_surgeries(date=record["start"].date())
    assert [s.surgery_id for s in surgeries] == [record["surgery_id"]]
    assert db_session.get(Allocation, record["allocation_id"]).surgery_id == record["surgery_id"]
    assert db_session.get(AuditLog, record["audit_id"]).timestamp == record["start"]

    report = ReportService(db_session).utilization(record["start"], record["start"] + timedelta(hours=4))
    assert report["theatres"][0]["booked_minutes"] == 120
    assert report["equipment"][0]["booked_minutes"] == 120


@pytest.mark.parametrize("age", AGES)
def test_tc_ops_01_old_surgeries_retrievable_through_api(client, old_records, age):
    record = old_records[age]
    response = client.get(
        "/api/v1/surgeries", params={"date": record["start"].date().isoformat()}, headers=headers("doctor")
    )
    assert response.status_code == 200
    assert [s["surgery_id"] for s in response.json()] == [record["surgery_id"]]


@pytest.mark.parametrize("age", AGES)
def test_tc_ops_01_report_for_an_old_range_through_api(client, old_records, age):
    start = old_records[age]["start"]
    params = {"from": start.isoformat(), "to": (start + timedelta(hours=4)).isoformat()}
    body = client.get("/api/v1/reports/utilization", params=params, headers=headers("admin")).json()
    assert body["theatres"][0]["bookedMinutes"] == 120  # half of the 240-minute range
    assert body["equipment"][0]["usagePercent"] == 50.0


def test_tc_ops_01_normal_operations_never_remove_old_records(db_session, old_records):
    """Create, cancel, allocate, release and retire, then check that every old row is still there."""
    before = count_rows(db_session)
    theatre, spare = Theatre(name="OT-New"), Equipment(name="Spare")
    db_session.add_all([theatre, spare])
    db_session.commit()
    surgeries, equipment = SurgeryService(db_session), EquipmentService(db_session)
    start = TODAY + timedelta(days=3)

    first, _ = surgeries.create_surgery("New", theatre.theatre_id, start, start + timedelta(hours=1))
    allocation = equipment.allocate(first.surgery_id, theatre.theatre_id, [spare.equipment_id])[0]
    equipment.release_allocation(allocation.allocation_id)
    surgeries.reschedule_surgery(first.surgery_id, start_time=start + timedelta(days=1), end_time=start + timedelta(days=1, hours=1))
    surgeries.cancel_surgery(first.surgery_id)
    equipment.retire_equipment(spare.equipment_id)
    equipment.retire_theatre(theatre.theatre_id)

    for record in old_records.values():
        assert db_session.get(Surgery, record["surgery_id"]) is not None
        assert db_session.get(Allocation, record["allocation_id"]) is not None
        assert db_session.get(AuditLog, record["audit_id"]) is not None
    # 1 new surgery, 1 new allocation (allocate) and 2 new audit entries (allocate, release)
    assert count_rows(db_session) == (before[0] + 1, before[1] + 1, before[2] + 2)


# ---------- no purge code ----------

RETAINED_MODELS = {"Surgery", "Allocation", "AuditLog"}
RETAINED_TABLES = ("surgery", "allocation", "audit_log")
SESSION_NAMES = {"db", "self.db", "session", "self.session"}
JOB_MODULES = ("apscheduler", "celery", "schedule", "rq", "crontab", "sched")
JOB_NAMES = {"BackgroundTasks", "on_event", "lifespan", "repeat_every", "create_task", "Timer"}


def python_files():
    return sorted(APP_DIR.rglob("*.py"))


def find_deletes(path: Path):
    """Return 'file:line: code' for each delete of a retained record in one file.

    Two kinds are found:
      session.delete(row)               deletes one row of any model
      query(Surgery|Allocation|AuditLog)...delete()   bulk delete
    Route decorators such as @router.delete(...) are not deletes and are ignored.
    """
    source = path.read_text()
    found = []
    for node in ast.walk(ast.parse(source)):
        is_delete_call = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "delete"
        if not is_delete_call:
            continue
        receiver = node.func.value
        on_session = ast.unparse(receiver) in SESSION_NAMES
        names_in_chain = {n.id for n in ast.walk(receiver) if isinstance(n, ast.Name)}
        if on_session or names_in_chain & RETAINED_MODELS:
            found.append(f"{path.name}:{node.lineno}: {ast.unparse(node)}")
    for match in re.finditer(r"delete\s+from\s+(\w+)|truncate\s+(\w+)|drop\s+table", source, re.IGNORECASE):
        found.append(f"{path.name}: raw SQL: {match.group(0)}")
    return found


def test_tc_ops_01_no_code_deletes_surgery_allocation_or_audit_rows():
    deletes = [line for path in python_files() for line in find_deletes(path)]
    assert deletes == [], "Code that deletes retained records:\n" + "\n".join(deletes)


def test_tc_ops_01_no_scheduler_or_background_job():
    jobs = []
    for path in python_files():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [alias.name for alias in node.names] + [getattr(node, "module", None) or ""]
                if any(m.split(".")[0] in JOB_MODULES for m in modules):
                    jobs.append(f"{path.name}:{node.lineno}: imports {modules}")
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if name in JOB_NAMES:
                    jobs.append(f"{path.name}:{node.lineno}: uses {name}")
    assert jobs == [], "Background jobs found:\n" + "\n".join(jobs)


def test_tc_ops_01_scan_really_detects_deletes(tmp_path):
    """The scan itself must work, otherwise an empty result proves nothing."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "@router.delete('/x')\n"
        "def f(db):\n"
        "    db.query(Allocation).filter(Allocation.released == True).delete()\n"
        "    db.delete(row)\n"
        "    db.execute('DELETE FROM audit_log')\n"
        "    db.query(Equipment).delete()\n"
    )
    found = find_deletes(sample)
    assert len(found) == 3  # bulk delete, session delete and raw SQL; Equipment and the route are ignored


# ---------- reschedule keeps allocation history ----------


def test_tc_ops_01_reschedule_keeps_old_allocation_rows(db_session):
    theatre, ventilator = Theatre(name="OT-1"), Equipment(name="Ventilator")
    db_session.add_all([theatre, ventilator])
    db_session.commit()
    service = SurgeryService(db_session)
    start = TODAY + timedelta(days=10)
    surgery, _ = service.create_surgery(
        "P", theatre.theatre_id, start, start + timedelta(hours=2), equipment_ids=[ventilator.equipment_id]
    )
    old_row = db_session.query(Allocation).one()
    new_start = start + timedelta(hours=4)

    moved, conflicts = service.reschedule_surgery(
        surgery.surgery_id,
        start_time=new_start,
        end_time=new_start + timedelta(hours=2),
        equipment_ids=[ventilator.equipment_id],
    )

    assert conflicts is None
    rows = db_session.query(Allocation).order_by(Allocation.allocation_id).all()
    assert [row.allocation_id for row in rows][0] == old_row.allocation_id  # still there
    assert [(row.start_time, row.released, row.replaced) for row in rows] == [
        (start, True, True),  # the old slot, kept as history
        (new_start, False, False),  # the new slot
    ]


def test_tc_ops_01_reschedule_twice_keeps_every_version(db_session):
    theatre, ventilator = Theatre(name="OT-1"), Equipment(name="Ventilator")
    db_session.add_all([theatre, ventilator])
    db_session.commit()
    service = SurgeryService(db_session)
    start = TODAY + timedelta(days=10)
    surgery, _ = service.create_surgery(
        "P", theatre.theatre_id, start, start + timedelta(hours=1), equipment_ids=[ventilator.equipment_id]
    )
    for hours_later in (2, 4):
        new_start = start + timedelta(hours=hours_later)
        service.reschedule_surgery(
            surgery.surgery_id, start_time=new_start, end_time=new_start + timedelta(hours=1),
            equipment_ids=[ventilator.equipment_id],
        )
    assert [row.replaced for row in db_session.query(Allocation).order_by(Allocation.allocation_id)] == [True, True, False]


def test_tc_ops_01_rescheduled_item_is_free_at_the_old_slot(db_session):
    """The replaced row is released, so it no longer blocks the old slot."""
    theatre, ventilator = Theatre(name="OT-1"), Equipment(name="Ventilator")
    db_session.add_all([theatre, ventilator])
    db_session.commit()
    service = SurgeryService(db_session)
    start = TODAY + timedelta(days=10)
    end = start + timedelta(hours=2)
    surgery, _ = service.create_surgery("P", theatre.theatre_id, start, end, equipment_ids=[ventilator.equipment_id])
    service.reschedule_surgery(
        surgery.surgery_id, start_time=start + timedelta(days=1), end_time=end + timedelta(days=1),
        equipment_ids=[ventilator.equipment_id],
    )
    availability = EquipmentService(db_session).equipment_availability(ventilator.equipment_id, start, end)
    assert availability["available"] is True


def test_tc_ops_01_report_does_not_count_replaced_rows(db_session):
    """Before the replaced flag, a 2-hour surgery moved within the day showed 240 equipment minutes."""
    theatre, ventilator = Theatre(name="OT-1"), Equipment(name="Ventilator")
    db_session.add_all([theatre, ventilator])
    db_session.commit()
    service = SurgeryService(db_session)
    day = (TODAY + timedelta(days=10)).replace(hour=0)
    surgery, _ = service.create_surgery(
        "P", theatre.theatre_id, day + timedelta(hours=9), day + timedelta(hours=11),
        equipment_ids=[ventilator.equipment_id],
    )
    service.reschedule_surgery(
        surgery.surgery_id, start_time=day + timedelta(hours=13), end_time=day + timedelta(hours=15),
        equipment_ids=[ventilator.equipment_id],
    )
    report = ReportService(db_session).utilization(day, day + timedelta(days=1))
    assert report["theatres"][0]["booked_minutes"] == 120
    assert report["equipment"][0]["booked_minutes"] == 120
