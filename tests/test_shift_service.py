"""OT-F-031: shifts and availability (TC-Staff-02)."""
from datetime import timezone

import pytest

from app.models.models import StaffTypeEnum, SurgeryStatusEnum
from app.services.shift_service import ShiftService, ShiftValidationError
from tests.helpers import dt, make_shift_for, make_staff, make_surgery_with_staff


def test_set_shifts_stores_them_in_order(db_session):
    staff = make_staff(db_session)
    shifts = ShiftService(db_session).set_shifts(
        staff.staff_id, [(dt(11, 14), dt(11, 22)), (dt(10, 8), dt(10, 16))]
    )
    assert [s.start_time for s in shifts] == [dt(10, 8), dt(11, 14)]
    assert len(ShiftService(db_session).get_shifts(staff.staff_id)) == 2


def test_set_shifts_replaces_existing(db_session):
    staff = make_staff(db_session)
    service = ShiftService(db_session)
    service.set_shifts(staff.staff_id, [(dt(10, 8), dt(10, 16))])
    service.set_shifts(staff.staff_id, [(dt(12, 8), dt(12, 16))])
    stored = service.get_shifts(staff.staff_id)
    assert len(stored) == 1 and stored[0].start_time == dt(12, 8)


def test_set_shifts_unknown_staff_returns_none(db_session):
    assert ShiftService(db_session).set_shifts(999, [(dt(10, 8), dt(10, 16))]) is None


def test_overlapping_shifts_rejected(db_session):
    staff = make_staff(db_session)
    with pytest.raises(ShiftValidationError):
        ShiftService(db_session).set_shifts(
            staff.staff_id, [(dt(10, 8), dt(10, 16)), (dt(10, 15), dt(10, 20))]
        )
    assert ShiftService(db_session).get_shifts(staff.staff_id) == []  # nothing saved


def test_back_to_back_shifts_allowed(db_session):
    staff = make_staff(db_session)
    shifts = ShiftService(db_session).set_shifts(
        staff.staff_id, [(dt(10, 8), dt(10, 16)), (dt(10, 16), dt(10, 23))]
    )
    assert len(shifts) == 2


def test_end_before_start_rejected(db_session):
    staff = make_staff(db_session)
    with pytest.raises(ShiftValidationError):
        ShiftService(db_session).set_shifts(staff.staff_id, [(dt(10, 16), dt(10, 8))])


def test_available_when_on_shift_and_free(db_session):
    staff = make_staff(db_session)
    make_shift_for(db_session, staff, dt(10, 8), dt(10, 16))
    assert ShiftService(db_session).is_available(staff.staff_id, dt(10, 9), dt(10, 11)) is True


def test_not_available_outside_shift(db_session):
    staff = make_staff(db_session)
    make_shift_for(db_session, staff, dt(10, 8), dt(10, 16))
    service = ShiftService(db_session)
    assert service.is_available(staff.staff_id, dt(10, 15), dt(10, 17)) is False  # runs past shift end
    assert service.is_available(staff.staff_id, dt(11, 9), dt(11, 11)) is False  # other day


def test_not_available_when_inactive(db_session):
    staff = make_staff(db_session, active=False)
    make_shift_for(db_session, staff, dt(10, 8), dt(10, 16))
    assert ShiftService(db_session).is_available(staff.staff_id, dt(10, 9), dt(10, 11)) is False


def test_not_available_when_already_in_a_surgery(db_session):
    staff = make_staff(db_session)
    make_shift_for(db_session, staff, dt(10, 8), dt(10, 16))
    make_surgery_with_staff(db_session, staff, dt(10, 10), dt(10, 12))
    assert ShiftService(db_session).is_available(staff.staff_id, dt(10, 11), dt(10, 13)) is False
    assert ShiftService(db_session).is_available(staff.staff_id, dt(10, 12), dt(10, 14)) is True  # touching is fine


def test_cancelled_surgery_does_not_block(db_session):
    staff = make_staff(db_session)
    make_shift_for(db_session, staff, dt(10, 8), dt(10, 16))
    make_surgery_with_staff(db_session, staff, dt(10, 10), dt(10, 12), status=SurgeryStatusEnum.cancelled)
    assert ShiftService(db_session).is_available(staff.staff_id, dt(10, 10), dt(10, 12)) is True


def test_availability_unknown_staff_returns_none(db_session):
    assert ShiftService(db_session).is_available(999, dt(10, 9), dt(10, 11)) is None


def test_availability_bad_range_rejected(db_session):
    staff = make_staff(db_session)
    with pytest.raises(ShiftValidationError):
        ShiftService(db_session).is_available(staff.staff_id, dt(10, 11), dt(10, 9))


def test_timezone_aware_input_is_converted_to_utc(db_session):
    staff = make_staff(db_session, name="Nurse Ravi", staff_type=StaffTypeEnum.nurse, specialization=None)
    make_shift_for(db_session, staff, dt(10, 8), dt(10, 16))  # naive == UTC
    start = dt(10, 9).replace(tzinfo=timezone.utc)
    end = dt(10, 11).replace(tzinfo=timezone.utc)
    assert ShiftService(db_session).is_available(staff.staff_id, start, end) is True
