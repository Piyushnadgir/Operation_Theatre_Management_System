"""Service-level tests for the Equipment and Resource Service.

Test names start with the Test Plan case they trace to:
TC-Eq-01 (OT-F-040), TC-Eq-02 (OT-F-041), TC-Eq-03 (OT-F-042).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.models import (
    Allocation,
    AuditLog,
    Equipment,
    EquipmentStatusEnum,
    Surgery,
    SurgeryStatusEnum,
    Theatre,
    TheatreStatusEnum,
)
from app.services.conflict_detection import ConflictDetector
from app.services.equipment_service import (
    EquipmentService,
    InvalidRequest,
    ResourceConflict,
    ResourceNotFound,
)
from app.services.surgery_service import SurgeryService

# Times are relative to now, so "future" stays future whenever the tests run
START = datetime.now().replace(microsecond=0) + timedelta(days=7)
END = START + timedelta(hours=2)


def add_theatre(db, name="OT-1", status=TheatreStatusEnum.available):
    theatre = Theatre(name=name, status=status)
    db.add(theatre)
    db.commit()
    return theatre


def add_equipment(db, name="Ventilator", status=EquipmentStatusEnum.available):
    equipment = Equipment(name=name, category="Respiratory", status=status)
    db.add(equipment)
    db.commit()
    return equipment


def add_surgery(db, theatre, start=START, end=END, status=SurgeryStatusEnum.scheduled):
    surgery = Surgery(patient_name="Test", theatre_id=theatre.theatre_id, start_time=start, end_time=end, status=status)
    db.add(surgery)
    db.commit()
    return surgery


def add_allocation(db, surgery, equipment, released=False):
    allocation = Allocation(
        surgery_id=surgery.surgery_id,
        equipment_id=equipment.equipment_id,
        theatre_id=surgery.theatre_id,
        start_time=surgery.start_time,
        end_time=surgery.end_time,
        released=released,
    )
    db.add(allocation)
    db.commit()
    return allocation


# ---------- TC-Eq-01: add, update and retire equipment ----------


def test_tc_eq_01_create_equipment(db_session):
    equipment = EquipmentService(db_session).create_equipment("Monitor", category="Cardiac")
    assert equipment.equipment_id is not None
    assert equipment.status == EquipmentStatusEnum.available
    assert equipment.is_active is True


def test_tc_eq_01_new_equipment_cannot_start_in_use(db_session):
    with pytest.raises(InvalidRequest):
        EquipmentService(db_session).create_equipment("Monitor", status=EquipmentStatusEnum.in_use)


def test_tc_eq_01_update_equipment_fields(db_session):
    equipment = add_equipment(db_session)
    updated = EquipmentService(db_session).update_equipment(equipment.equipment_id, name="New", category="Other")
    assert updated.name == "New"
    assert updated.category == "Other"


def test_tc_eq_01_update_missing_equipment(db_session):
    with pytest.raises(ResourceNotFound):
        EquipmentService(db_session).update_equipment(999, name="New")


def test_tc_eq_01_list_filters_by_status_and_category(db_session):
    add_equipment(db_session, "A")
    add_equipment(db_session, "B", EquipmentStatusEnum.maintenance)
    service = EquipmentService(db_session)
    service.create_equipment("C", category="Cardiac")
    assert [e.name for e in service.list_equipment(status=EquipmentStatusEnum.maintenance)] == ["B"]
    assert [e.name for e in service.list_equipment(category="Cardiac")] == ["C"]


def test_tc_eq_01_retire_is_soft_delete(db_session):
    equipment = add_equipment(db_session)
    service = EquipmentService(db_session)
    service.retire_equipment(equipment.equipment_id)
    assert db_session.query(Equipment).count() == 1  # the row is kept
    assert equipment.is_active is False
    assert service.list_equipment() == []
    assert len(service.list_equipment(include_retired=True)) == 1


def test_tc_eq_01_retire_blocked_by_future_allocation(db_session):
    equipment = add_equipment(db_session)
    add_allocation(db_session, add_surgery(db_session, add_theatre(db_session)), equipment)
    with pytest.raises(ResourceConflict):
        EquipmentService(db_session).retire_equipment(equipment.equipment_id)
    assert equipment.is_active is True


def test_tc_eq_01_retire_allowed_with_past_or_released_allocation(db_session):
    equipment = add_equipment(db_session)
    theatre = add_theatre(db_session)
    past = add_surgery(db_session, theatre, START - timedelta(days=30), END - timedelta(days=30))
    add_allocation(db_session, past, equipment)
    add_allocation(db_session, add_surgery(db_session, theatre), equipment, released=True)
    EquipmentService(db_session).retire_equipment(equipment.equipment_id)
    assert equipment.is_active is False


# ---------- TC-Eq-01: equipment status rules (SAD 3.4) ----------


def test_tc_eq_01_available_to_maintenance_and_back(db_session):
    equipment = add_equipment(db_session)
    service = EquipmentService(db_session)
    service.update_equipment(equipment.equipment_id, status=EquipmentStatusEnum.maintenance)
    assert equipment.status == EquipmentStatusEnum.maintenance
    service.update_equipment(equipment.equipment_id, status=EquipmentStatusEnum.available)
    assert equipment.status == EquipmentStatusEnum.available


@pytest.mark.parametrize(
    "current, wanted",
    [
        (EquipmentStatusEnum.in_use, EquipmentStatusEnum.maintenance),  # must be released first
        (EquipmentStatusEnum.in_use, EquipmentStatusEnum.available),  # only a release does this
        (EquipmentStatusEnum.available, EquipmentStatusEnum.in_use),  # only the surgery start does this
        (EquipmentStatusEnum.maintenance, EquipmentStatusEnum.in_use),
    ],
)
def test_tc_eq_01_disallowed_status_change_rejected(db_session, current, wanted):
    equipment = add_equipment(db_session, status=current)
    with pytest.raises(InvalidRequest):
        EquipmentService(db_session).update_equipment(equipment.equipment_id, status=wanted)
    assert equipment.status == current


def test_tc_eq_01_in_use_item_can_still_be_renamed(db_session):
    equipment = add_equipment(db_session, status=EquipmentStatusEnum.in_use)
    service = EquipmentService(db_session)
    service.update_equipment(equipment.equipment_id, name="New", status=EquipmentStatusEnum.in_use)
    assert equipment.name == "New"


# ---------- TC-Eq-01: add, update and retire theatres ----------


def test_tc_eq_01_create_and_rename_theatre(db_session):
    service = EquipmentService(db_session)
    theatre = service.create_theatre("OT-1")
    assert theatre.status == TheatreStatusEnum.available
    assert theatre.is_active is True
    assert service.update_theatre(theatre.theatre_id, "OT-9").name == "OT-9"
    assert service.update_theatre(theatre.theatre_id, "OT-9").name == "OT-9"  # keeping the name is fine


def test_tc_eq_01_theatre_name_must_be_unique(db_session):
    service = EquipmentService(db_session)
    service.create_theatre("OT-1")
    other = service.create_theatre("OT-2")
    with pytest.raises(ResourceConflict):
        service.create_theatre("OT-1")
    with pytest.raises(ResourceConflict):
        service.update_theatre(other.theatre_id, "OT-1")


def test_tc_eq_01_admin_sets_cleaning_and_maintenance(db_session):
    theatre = add_theatre(db_session)
    service = EquipmentService(db_session)
    for status in (TheatreStatusEnum.cleaning, TheatreStatusEnum.maintenance, TheatreStatusEnum.available):
        service.update_theatre_status(theatre.theatre_id, status)
        assert theatre.status == status


def test_tc_eq_01_occupied_cannot_be_set_by_hand(db_session):
    theatre = add_theatre(db_session)
    service = EquipmentService(db_session)
    with pytest.raises(InvalidRequest):
        service.update_theatre_status(theatre.theatre_id, TheatreStatusEnum.occupied)
    with pytest.raises(InvalidRequest):
        service.create_theatre("OT-2", status=TheatreStatusEnum.occupied)


def test_tc_eq_01_occupied_theatre_cannot_be_changed_by_hand(db_session):
    theatre = add_theatre(db_session, status=TheatreStatusEnum.occupied)
    with pytest.raises(InvalidRequest):
        EquipmentService(db_session).update_theatre_status(theatre.theatre_id, TheatreStatusEnum.cleaning)


def test_tc_eq_01_retire_theatre_is_soft_delete(db_session):
    theatre = add_theatre(db_session)
    service = EquipmentService(db_session)
    service.retire_theatre(theatre.theatre_id)
    assert db_session.query(Theatre).count() == 1
    assert service.list_theatres() == []
    assert len(service.list_theatres(include_retired=True)) == 1


def test_tc_eq_01_retire_theatre_blocked_by_future_surgery(db_session):
    theatre = add_theatre(db_session)
    add_surgery(db_session, theatre)
    with pytest.raises(ResourceConflict):
        EquipmentService(db_session).retire_theatre(theatre.theatre_id)
    assert theatre.is_active is True


# ---------- TC-Eq-01: equipment under maintenance cannot be booked ----------


def test_tc_eq_01_detector_reports_maintenance_and_retired_equipment(db_session):
    good = add_equipment(db_session, "Good")
    broken = add_equipment(db_session, "Broken", EquipmentStatusEnum.maintenance)
    retired = add_equipment(db_session, "Retired")
    retired.is_active = False
    db_session.commit()
    ids = [good.equipment_id, broken.equipment_id, retired.equipment_id]
    assert sorted(ConflictDetector(db_session).check_equipment_status(ids)) == [
        broken.equipment_id,
        retired.equipment_id,
    ]


def test_tc_eq_01_create_surgery_rejects_maintenance_equipment(db_session):
    theatre = add_theatre(db_session)
    equipment = add_equipment(db_session, status=EquipmentStatusEnum.maintenance)
    surgery, conflicts = SurgeryService(db_session).create_surgery(
        "Test", theatre.theatre_id, START, END, equipment_ids=[equipment.equipment_id]
    )
    assert surgery is None
    assert conflicts[0]["resource_id"] == equipment.equipment_id
    assert "maintenance" in conflicts[0]["message"]
    assert db_session.query(Surgery).count() == 0


def test_tc_eq_01_reschedule_surgery_rejects_maintenance_equipment(db_session):
    theatre = add_theatre(db_session)
    equipment = add_equipment(db_session, status=EquipmentStatusEnum.maintenance)
    service = SurgeryService(db_session)
    surgery, _ = service.create_surgery("Test", theatre.theatre_id, START, END)
    moved, conflicts = service.reschedule_surgery(surgery.surgery_id, equipment_ids=[equipment.equipment_id])
    assert moved is None
    assert conflicts[0]["resource_type"] == "equipment"


# ---------- TC-Eq-02: availability for a time range ----------


def test_tc_eq_02_free_equipment_is_available(db_session):
    equipment = add_equipment(db_session)
    result = EquipmentService(db_session).equipment_availability(equipment.equipment_id, START, END)
    assert result == {"available": True, "status": "available", "reasons": []}


@pytest.mark.parametrize(
    "start_shift, end_shift, available",
    [
        (timedelta(hours=-1), timedelta(hours=-1), False),  # overlaps the first hour
        (timedelta(hours=1), timedelta(hours=1), False),  # overlaps the last hour
        (timedelta(minutes=30), timedelta(minutes=-30), False),  # inside the booking
        (timedelta(hours=-1), timedelta(hours=1), False),  # surrounds the booking
        (timedelta(0), timedelta(0), False),  # same slot
        (timedelta(hours=-2), timedelta(hours=-2), True),  # ends exactly at booking start
        (timedelta(hours=2), timedelta(hours=2), True),  # starts exactly at booking end
    ],
)
def test_tc_eq_02_overlap_rule_and_touching_boundaries(db_session, start_shift, end_shift, available):
    """Same rule as ConflictDetector: existing.start < end AND existing.end > start."""
    equipment = add_equipment(db_session)
    theatre = add_theatre(db_session)
    add_allocation(db_session, add_surgery(db_session, theatre), equipment)
    service = EquipmentService(db_session)
    start, end = START + start_shift, END + end_shift
    assert service.equipment_availability(equipment.equipment_id, start, end)["available"] is available
    assert service.theatre_availability(theatre.theatre_id, start, end)["available"] is available


def test_tc_eq_02_released_allocation_does_not_block(db_session):
    equipment = add_equipment(db_session)
    add_allocation(db_session, add_surgery(db_session, add_theatre(db_session)), equipment, released=True)
    result = EquipmentService(db_session).equipment_availability(equipment.equipment_id, START, END)
    assert result["available"] is True


def test_tc_eq_02_maintenance_equipment_is_unavailable(db_session):
    equipment = add_equipment(db_session, status=EquipmentStatusEnum.maintenance)
    result = EquipmentService(db_session).equipment_availability(equipment.equipment_id, START, END)
    assert result["available"] is False
    assert result["reasons"] == ["under maintenance"]


def test_tc_eq_02_retired_equipment_is_unavailable(db_session):
    equipment = add_equipment(db_session)
    service = EquipmentService(db_session)
    service.retire_equipment(equipment.equipment_id)
    assert service.equipment_availability(equipment.equipment_id, START, END)["reasons"] == ["retired"]


def test_tc_eq_02_in_use_status_alone_does_not_block_a_later_range(db_session):
    """in_use describes now. Next week's slot depends only on the allocations."""
    equipment = add_equipment(db_session, status=EquipmentStatusEnum.in_use)
    result = EquipmentService(db_session).equipment_availability(equipment.equipment_id, START, END)
    assert result["available"] is True
    assert result["status"] == "in_use"


@pytest.mark.parametrize("status", [SurgeryStatusEnum.scheduled, SurgeryStatusEnum.in_progress])
def test_tc_eq_02_live_surgery_blocks_theatre(db_session, status):
    theatre = add_theatre(db_session)
    add_surgery(db_session, theatre, status=status)
    result = EquipmentService(db_session).theatre_availability(theatre.theatre_id, START, END)
    assert result["available"] is False
    assert result["reasons"] == ["already booked in this time range"]


@pytest.mark.parametrize("status", [SurgeryStatusEnum.completed, SurgeryStatusEnum.cancelled])
def test_tc_eq_02_finished_surgery_does_not_block_theatre(db_session, status):
    theatre = add_theatre(db_session)
    add_surgery(db_session, theatre, status=status)
    assert EquipmentService(db_session).theatre_availability(theatre.theatre_id, START, END)["available"] is True


def test_tc_eq_02_unreleased_allocation_blocks_theatre(db_session):
    """Blocks even if the surgery row no longer holds the slot."""
    theatre = add_theatre(db_session)
    surgery = add_surgery(db_session, theatre)
    add_allocation(db_session, surgery, add_equipment(db_session))
    surgery.status = SurgeryStatusEnum.completed
    db_session.commit()
    assert EquipmentService(db_session).theatre_availability(theatre.theatre_id, START, END)["available"] is False


@pytest.mark.parametrize("status", [TheatreStatusEnum.occupied, TheatreStatusEnum.cleaning])
def test_tc_eq_02_occupied_or_cleaning_alone_does_not_block_a_later_range(db_session, status):
    theatre = add_theatre(db_session, status=status)
    result = EquipmentService(db_session).theatre_availability(theatre.theatre_id, START, END)
    assert result["available"] is True
    assert result["status"] == status.value


def test_tc_eq_02_maintenance_or_retired_theatre_is_unavailable(db_session):
    theatre = add_theatre(db_session, status=TheatreStatusEnum.maintenance)
    theatre.is_active = False
    db_session.commit()
    result = EquipmentService(db_session).theatre_availability(theatre.theatre_id, START, END)
    assert result["available"] is False
    assert result["reasons"] == ["retired", "under maintenance"]


@pytest.mark.parametrize("end", [START, START - timedelta(hours=1)])
def test_tc_eq_02_end_must_be_after_start(db_session, end):
    equipment = add_equipment(db_session)
    theatre = add_theatre(db_session)
    service = EquipmentService(db_session)
    with pytest.raises(InvalidRequest):
        service.equipment_availability(equipment.equipment_id, START, end)
    with pytest.raises(InvalidRequest):
        service.theatre_availability(theatre.theatre_id, START, end)


def test_tc_eq_02_time_with_offset_is_compared_like_stored_surgeries(db_session):
    """A mix of offset and no offset must not crash, and must match the stored clock time."""
    theatre = add_theatre(db_session)
    add_surgery(db_session, theatre, start=START.replace(tzinfo=timezone.utc), end=END.replace(tzinfo=timezone.utc))
    result = EquipmentService(db_session).theatre_availability(theatre.theatre_id, START.replace(tzinfo=timezone.utc), END)
    assert result["available"] is False


def test_tc_eq_02_missing_records(db_session):
    service = EquipmentService(db_session)
    with pytest.raises(ResourceNotFound):
        service.equipment_availability(999, START, END)
    with pytest.raises(ResourceNotFound):
        service.theatre_availability(999, START, END)


# ---------- TC-Eq-03: allocate ----------


def test_tc_eq_03_allocate_shows_resources_as_allocated(db_session):
    theatre = add_theatre(db_session)
    first = add_equipment(db_session, "A")
    second = add_equipment(db_session, "B")
    surgery = add_surgery(db_session, theatre)
    service = EquipmentService(db_session)

    allocations = service.allocate(surgery.surgery_id, theatre.theatre_id, [first.equipment_id, second.equipment_id])

    assert len(allocations) == 2
    assert allocations[0].start_time == START
    assert allocations[0].end_time == END
    assert allocations[0].released is False
    assert service.equipment_availability(first.equipment_id, START, END)["available"] is False
    assert service.equipment_availability(second.equipment_id, START, END)["available"] is False


def test_tc_eq_03_allocate_does_not_conflict_with_own_theatre_booking(db_session):
    """The surgery itself holds the theatre, so that booking must be ignored."""
    theatre = add_theatre(db_session)
    surgery = add_surgery(db_session, theatre)
    equipment = add_equipment(db_session)
    allocations = EquipmentService(db_session).allocate(surgery.surgery_id, theatre.theatre_id, [equipment.equipment_id])
    assert len(allocations) == 1


def test_tc_eq_03_all_or_nothing_when_one_item_is_in_maintenance(db_session):
    theatre = add_theatre(db_session)
    good = add_equipment(db_session, "Good")
    broken = add_equipment(db_session, "Broken", EquipmentStatusEnum.maintenance)
    surgery = add_surgery(db_session, theatre)
    with pytest.raises(ResourceConflict) as error:
        EquipmentService(db_session).allocate(surgery.surgery_id, theatre.theatre_id, [good.equipment_id, broken.equipment_id])
    assert [c["resource_id"] for c in error.value.conflicts] == [broken.equipment_id]
    assert db_session.query(Allocation).count() == 0


def test_tc_eq_03_all_or_nothing_when_one_item_overlaps(db_session):
    theatre = add_theatre(db_session)
    other_theatre = add_theatre(db_session, "OT-2")
    busy = add_equipment(db_session, "Busy")
    free = add_equipment(db_session, "Free")
    add_allocation(db_session, add_surgery(db_session, other_theatre), busy)
    surgery = add_surgery(db_session, theatre)
    with pytest.raises(ResourceConflict) as error:
        EquipmentService(db_session).allocate(surgery.surgery_id, theatre.theatre_id, [free.equipment_id, busy.equipment_id])
    assert error.value.conflicts[0]["resource_id"] == busy.equipment_id
    assert db_session.query(Allocation).count() == 1  # only the existing row


def test_tc_eq_03_retired_item_is_rejected(db_session):
    theatre = add_theatre(db_session)
    equipment = add_equipment(db_session)
    surgery = add_surgery(db_session, theatre)
    service = EquipmentService(db_session)
    service.retire_equipment(equipment.equipment_id)
    with pytest.raises(ResourceConflict):
        service.allocate(surgery.surgery_id, theatre.theatre_id, [equipment.equipment_id])


def test_tc_eq_03_theatre_in_maintenance_is_rejected(db_session):
    theatre = add_theatre(db_session, status=TheatreStatusEnum.maintenance)
    surgery = add_surgery(db_session, theatre)
    with pytest.raises(ResourceConflict) as error:
        EquipmentService(db_session).allocate(surgery.surgery_id, theatre.theatre_id, [add_equipment(db_session).equipment_id])
    assert error.value.conflicts[0]["resource_type"] == "theatre"


def test_tc_eq_03_item_cannot_be_allocated_twice_to_one_surgery(db_session):
    theatre = add_theatre(db_session)
    equipment = add_equipment(db_session)
    surgery = add_surgery(db_session, theatre)
    service = EquipmentService(db_session)
    service.allocate(surgery.surgery_id, theatre.theatre_id, [equipment.equipment_id])
    with pytest.raises(ResourceConflict):
        service.allocate(surgery.surgery_id, theatre.theatre_id, [equipment.equipment_id])
    assert db_session.query(Allocation).count() == 1


def test_tc_eq_03_touching_surgeries_can_share_an_item(db_session):
    theatre = add_theatre(db_session)
    equipment = add_equipment(db_session)
    first = add_surgery(db_session, theatre)
    second = add_surgery(db_session, theatre, start=END, end=END + timedelta(hours=1))
    service = EquipmentService(db_session)
    service.allocate(first.surgery_id, theatre.theatre_id, [equipment.equipment_id])
    service.allocate(second.surgery_id, theatre.theatre_id, [equipment.equipment_id])
    assert db_session.query(Allocation).count() == 2


def test_tc_eq_03_theatre_must_match_the_surgery(db_session):
    theatre = add_theatre(db_session)
    other = add_theatre(db_session, "OT-2")
    surgery = add_surgery(db_session, theatre)
    with pytest.raises(InvalidRequest):
        EquipmentService(db_session).allocate(surgery.surgery_id, other.theatre_id, [add_equipment(db_session).equipment_id])


@pytest.mark.parametrize("status", [SurgeryStatusEnum.completed, SurgeryStatusEnum.cancelled])
def test_tc_eq_03_finished_surgery_cannot_be_allocated(db_session, status):
    theatre = add_theatre(db_session)
    surgery = add_surgery(db_session, theatre, status=status)
    with pytest.raises(InvalidRequest):
        EquipmentService(db_session).allocate(surgery.surgery_id, theatre.theatre_id, [add_equipment(db_session).equipment_id])


def test_tc_eq_03_allocate_missing_records(db_session):
    theatre = add_theatre(db_session)
    surgery = add_surgery(db_session, theatre)
    equipment = add_equipment(db_session)
    service = EquipmentService(db_session)
    with pytest.raises(ResourceNotFound):
        service.allocate(999, theatre.theatre_id, [equipment.equipment_id])
    with pytest.raises(ResourceNotFound):
        service.allocate(surgery.surgery_id, 999, [equipment.equipment_id])
    with pytest.raises(ResourceNotFound):
        service.allocate(surgery.surgery_id, theatre.theatre_id, [999])


# ---------- TC-Eq-03: release ----------


def test_tc_eq_03_release_makes_item_available_again(db_session):
    equipment = add_equipment(db_session)
    allocation = add_allocation(db_session, add_surgery(db_session, add_theatre(db_session)), equipment)
    service = EquipmentService(db_session)
    assert service.equipment_availability(equipment.equipment_id, START, END)["available"] is False
    service.release_allocation(allocation.allocation_id)
    assert allocation.released is True
    assert service.equipment_availability(equipment.equipment_id, START, END)["available"] is True


def test_tc_eq_03_double_release_has_no_further_effect(db_session):
    equipment = add_equipment(db_session)
    allocation = add_allocation(db_session, add_surgery(db_session, add_theatre(db_session)), equipment)
    service = EquipmentService(db_session)
    service.release_allocation(allocation.allocation_id)
    service.release_allocation(allocation.allocation_id)
    assert allocation.released is True
    assert db_session.query(AuditLog).filter(AuditLog.action == "release").count() == 1


def test_tc_eq_03_release_missing_allocation(db_session):
    with pytest.raises(ResourceNotFound):
        EquipmentService(db_session).release_allocation(999)


def test_tc_eq_03_allocate_and_release_are_audited(db_session):
    """OT-SR-005: one audit entry per allocation change, with the user."""
    theatre = add_theatre(db_session)
    surgery = add_surgery(db_session, theatre)
    service = EquipmentService(db_session)
    allocation = service.allocate(
        surgery.surgery_id, theatre.theatre_id, [add_equipment(db_session).equipment_id], user_id=7
    )[0]
    service.release_allocation(allocation.allocation_id, user_id=7)
    entries = db_session.query(AuditLog).order_by(AuditLog.log_id).all()
    assert [entry.action for entry in entries] == ["allocate", "release"]
    assert entries[0].user_id == 7
    assert entries[0].entity_type == "allocation"
    assert entries[0].entity_id == allocation.allocation_id


# ---------- TC-Eq-03: cancelling a surgery ----------


def test_tc_eq_03_cancel_surgery_makes_resources_available_again(db_session):
    """AC-OT-F-042: allocated during the surgery, available again afterwards."""
    theatre = add_theatre(db_session)
    equipment = add_equipment(db_session)
    surgery_service = SurgeryService(db_session)
    service = EquipmentService(db_session)
    surgery, _ = surgery_service.create_surgery(
        "Test", theatre.theatre_id, START, END, equipment_ids=[equipment.equipment_id]
    )
    assert service.equipment_availability(equipment.equipment_id, START, END)["available"] is False
    assert service.theatre_availability(theatre.theatre_id, START, END)["available"] is False

    surgery_service.cancel_surgery(surgery.surgery_id)

    assert db_session.query(Allocation).one().released is True
    assert service.equipment_availability(equipment.equipment_id, START, END)["available"] is True
    assert service.theatre_availability(theatre.theatre_id, START, END)["available"] is True


def test_tc_eq_03_cancel_surgery_with_unknown_equipment_id_still_works(db_session):
    """POST /surgeries does not check that ids exist, so cancel must cope with such rows."""
    theatre = add_theatre(db_session)
    surgery_service = SurgeryService(db_session)
    surgery, _ = surgery_service.create_surgery("Test", theatre.theatre_id, START, END, equipment_ids=[999])
    assert surgery_service.cancel_surgery(surgery.surgery_id).status == SurgeryStatusEnum.cancelled


# ---------- TC-Eq-03: status follows the surgery (SAD 3.4) ----------


def test_tc_eq_03_allocating_a_future_surgery_leaves_status_available(db_session):
    """Available becomes In use when the surgery starts, not when it is booked."""
    theatre = add_theatre(db_session)
    equipment = add_equipment(db_session)
    surgery = add_surgery(db_session, theatre)
    EquipmentService(db_session).allocate(surgery.surgery_id, theatre.theatre_id, [equipment.equipment_id])
    assert equipment.status == EquipmentStatusEnum.available
    assert theatre.status == TheatreStatusEnum.available


def test_tc_eq_03_surgery_start_sets_in_use_and_occupied(db_session):
    theatre = add_theatre(db_session)
    equipment = add_equipment(db_session)
    surgery = add_surgery(db_session, theatre)
    add_allocation(db_session, surgery, equipment)
    surgery.status = SurgeryStatusEnum.in_progress
    EquipmentService(db_session).sync_surgery_resources(surgery.surgery_id)
    assert equipment.status == EquipmentStatusEnum.in_use
    assert theatre.status == TheatreStatusEnum.occupied


def test_tc_eq_03_allocating_a_running_surgery_sets_in_use(db_session):
    theatre = add_theatre(db_session)
    equipment = add_equipment(db_session)
    surgery = add_surgery(db_session, theatre, status=SurgeryStatusEnum.in_progress)
    EquipmentService(db_session).allocate(surgery.surgery_id, theatre.theatre_id, [equipment.equipment_id])
    assert equipment.status == EquipmentStatusEnum.in_use


def test_tc_eq_03_release_returns_in_use_item_to_available(db_session):
    theatre = add_theatre(db_session)
    equipment = add_equipment(db_session, status=EquipmentStatusEnum.in_use)
    surgery = add_surgery(db_session, theatre, status=SurgeryStatusEnum.in_progress)
    allocation = add_allocation(db_session, surgery, equipment)
    service = EquipmentService(db_session)
    service.release_allocation(allocation.allocation_id)
    assert equipment.status == EquipmentStatusEnum.available
    service.update_equipment(equipment.equipment_id, status=EquipmentStatusEnum.maintenance)  # now allowed
    assert equipment.status == EquipmentStatusEnum.maintenance


def test_tc_eq_03_cancelling_running_surgery_frees_equipment_and_theatre(db_session):
    theatre = add_theatre(db_session, status=TheatreStatusEnum.occupied)
    equipment = add_equipment(db_session, status=EquipmentStatusEnum.in_use)
    surgery = add_surgery(db_session, theatre, status=SurgeryStatusEnum.in_progress)
    add_allocation(db_session, surgery, equipment)
    SurgeryService(db_session).cancel_surgery(surgery.surgery_id)
    assert equipment.status == EquipmentStatusEnum.available
    assert theatre.status == TheatreStatusEnum.available


def test_tc_eq_03_cancelling_a_later_surgery_keeps_item_in_use(db_session):
    """The item is in use now, so cancelling next week's booking must not free it."""
    theatre = add_theatre(db_session, status=TheatreStatusEnum.occupied)
    other_theatre = add_theatre(db_session, "OT-2")
    equipment = add_equipment(db_session, status=EquipmentStatusEnum.in_use)
    running = add_surgery(db_session, theatre, status=SurgeryStatusEnum.in_progress)
    later = add_surgery(db_session, other_theatre, start=END, end=END + timedelta(hours=1))
    add_allocation(db_session, running, equipment)
    add_allocation(db_session, later, equipment)
    SurgeryService(db_session).cancel_surgery(later.surgery_id)
    assert equipment.status == EquipmentStatusEnum.in_use
    assert theatre.status == TheatreStatusEnum.occupied


def test_tc_eq_03_sync_leaves_admin_statuses_alone(db_session):
    theatre = add_theatre(db_session, status=TheatreStatusEnum.cleaning)
    equipment = add_equipment(db_session, status=EquipmentStatusEnum.maintenance)
    surgery = add_surgery(db_session, theatre, status=SurgeryStatusEnum.in_progress)
    add_allocation(db_session, surgery, equipment)
    EquipmentService(db_session).sync_surgery_resources(surgery.surgery_id)
    assert equipment.status == EquipmentStatusEnum.maintenance
    assert theatre.status == TheatreStatusEnum.cleaning
