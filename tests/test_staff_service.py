"""OT-F-030: add, update and deactivate doctor and nurse records (TC-Staff-01)."""
from app.models.models import Staff, StaffTypeEnum
from app.services.staff_service import StaffService
import tests.helpers  # noqa: F401


def test_add_doctor_and_nurse(db_session):
    service = StaffService(db_session)
    doctor = service.create_staff("Dr. Asha", StaffTypeEnum.doctor, "Cardiology")
    nurse = service.create_staff("Nurse Ravi", "nurse")
    assert doctor.staff_id is not None and doctor.is_active is True
    assert doctor.specialization == "Cardiology"
    assert nurse.staff_type == StaffTypeEnum.nurse
    assert nurse.specialization is None


def test_get_staff(db_session):
    service = StaffService(db_session)
    doctor = service.create_staff("Dr. Asha", StaffTypeEnum.doctor)
    assert service.get_staff(doctor.staff_id).name == "Dr. Asha"
    assert service.get_staff(999) is None


def test_update_name_and_specialization(db_session):
    service = StaffService(db_session)
    doctor = service.create_staff("Dr. Asha", StaffTypeEnum.doctor, "Cardiology")
    updated = service.update_staff(doctor.staff_id, name="Dr. Asha Rao", specialization="Neurology")
    assert updated.name == "Dr. Asha Rao"
    assert updated.specialization == "Neurology"


def test_update_only_given_fields(db_session):
    service = StaffService(db_session)
    doctor = service.create_staff("Dr. Asha", StaffTypeEnum.doctor, "Cardiology")
    updated = service.update_staff(doctor.staff_id, name="Dr. A. Rao")
    assert updated.name == "Dr. A. Rao"
    assert updated.specialization == "Cardiology"


def test_update_can_clear_specialization(db_session):
    service = StaffService(db_session)
    doctor = service.create_staff("Dr. Asha", StaffTypeEnum.doctor, "Cardiology")
    assert service.update_staff(doctor.staff_id, specialization=None).specialization is None


def test_update_unknown_staff_returns_none(db_session):
    assert StaffService(db_session).update_staff(999, name="Nobody") is None


def test_deactivate_keeps_the_record(db_session):
    service = StaffService(db_session)
    doctor = service.create_staff("Dr. Asha", StaffTypeEnum.doctor)
    result = service.deactivate_staff(doctor.staff_id)
    assert result.is_active is False
    assert db_session.query(Staff).count() == 1  # deactivated, not deleted


def test_deactivate_unknown_staff_returns_none(db_session):
    assert StaffService(db_session).deactivate_staff(999) is None


def test_list_hides_inactive_by_default(db_session):
    service = StaffService(db_session)
    active = service.create_staff("Dr. Asha", StaffTypeEnum.doctor)
    gone = service.create_staff("Dr. Gone", StaffTypeEnum.doctor)
    service.deactivate_staff(gone.staff_id)

    assert [s.staff_id for s in service.list_staff()] == [active.staff_id]
    assert len(service.list_staff(include_inactive=True)) == 2


def test_list_filters_by_type_and_specialization(db_session):
    service = StaffService(db_session)
    service.create_staff("Dr. Asha", StaffTypeEnum.doctor, "Cardiology")
    service.create_staff("Dr. Bala", StaffTypeEnum.doctor, "Neurology")
    service.create_staff("Nurse Ravi", StaffTypeEnum.nurse)

    assert len(service.list_staff(staff_type=StaffTypeEnum.doctor)) == 2
    assert len(service.list_staff(staff_type="nurse")) == 1
    assert [s.name for s in service.list_staff(specialization="cardiology")] == ["Dr. Asha"]
