"""OT-F-033: assign staff only if active, on shift and (doctors) suitably specialized (TC-Staff-03)."""
from app.models.models import StaffTypeEnum
from app.services.assignment_service import AssignmentService
from tests.helpers import dt, make_shift_for, make_staff

START, END = dt(10, 9), dt(10, 11)


def _on_shift(db, **kwargs):
    staff = make_staff(db, **kwargs)
    make_shift_for(db, staff, dt(10, 8), dt(10, 16))
    return staff


def test_valid_doctor_can_be_assigned(db_session):
    doctor = _on_shift(db_session)
    assert AssignmentService(db_session).validate_assignment(
        doctor.staff_id, START, END, StaffTypeEnum.doctor, "Cardiology"
    ) is None


def test_unknown_staff_rejected(db_session):
    reason = AssignmentService(db_session).validate_assignment(999, START, END)
    assert reason is not None and "does not exist" in reason


def test_inactive_staff_rejected(db_session):
    doctor = _on_shift(db_session, active=False)
    reason = AssignmentService(db_session).validate_assignment(doctor.staff_id, START, END)
    assert reason is not None and "deactivated" in reason


def test_staff_not_on_shift_rejected(db_session):
    doctor = make_staff(db_session)  # no shifts at all
    reason = AssignmentService(db_session).validate_assignment(doctor.staff_id, START, END)
    assert reason is not None and "not on shift" in reason


def test_shift_must_cover_whole_surgery(db_session):
    doctor = _on_shift(db_session)
    reason = AssignmentService(db_session).validate_assignment(doctor.staff_id, dt(10, 15), dt(10, 18))
    assert reason is not None and "not on shift" in reason


def test_wrong_staff_type_rejected(db_session):
    nurse = _on_shift(db_session, name="Nurse Ravi", staff_type=StaffTypeEnum.nurse, specialization=None)
    reason = AssignmentService(db_session).validate_assignment(
        nurse.staff_id, START, END, expected_type=StaffTypeEnum.doctor
    )
    assert reason is not None and "not a doctor" in reason


def test_doctor_with_wrong_specialization_rejected(db_session):
    doctor = _on_shift(db_session, specialization="Neurology")
    reason = AssignmentService(db_session).validate_assignment(
        doctor.staff_id, START, END, StaffTypeEnum.doctor, "Cardiology"
    )
    assert reason is not None and "not specialized" in reason


def test_specialization_match_ignores_case(db_session):
    doctor = _on_shift(db_session, specialization="Cardiology")
    assert AssignmentService(db_session).validate_assignment(
        doctor.staff_id, START, END, StaffTypeEnum.doctor, "  cardiology "
    ) is None


def test_specialization_not_required_means_any_doctor(db_session):
    doctor = _on_shift(db_session, specialization=None)
    assert AssignmentService(db_session).validate_assignment(
        doctor.staff_id, START, END, StaffTypeEnum.doctor
    ) is None


def test_nurse_is_not_checked_for_specialization(db_session):
    nurse = _on_shift(db_session, name="Nurse Ravi", staff_type=StaffTypeEnum.nurse, specialization=None)
    assert AssignmentService(db_session).validate_assignments(
        [], [nurse.staff_id], START, END, required_specialization="Cardiology"
    ) == []


def test_validate_assignments_returns_conflict_dicts(db_session):
    good_doctor = _on_shift(db_session)
    bad_doctor = make_staff(db_session, name="Dr. Off")  # not on shift
    nurse = _on_shift(db_session, name="Nurse Ravi", staff_type=StaffTypeEnum.nurse, specialization=None)

    issues = AssignmentService(db_session).validate_assignments(
        [good_doctor.staff_id, bad_doctor.staff_id], [nurse.staff_id, 999], START, END
    )
    assert {(i["resource_type"], i["resource_id"]) for i in issues} == {
        ("doctor", bad_doctor.staff_id),
        ("nurse", 999),
    }
    assert all(set(i) == {"resource_type", "resource_id", "message"} for i in issues)


def test_validate_assignments_all_valid_returns_empty_list(db_session):
    doctor = _on_shift(db_session)
    assert AssignmentService(db_session).validate_assignments([doctor.staff_id], [], START, END) == []
