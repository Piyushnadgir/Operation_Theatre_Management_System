"""OT-SR-005: append-only audit log."""
import pytest

from app.models.models import AuditLog
from app.services.audit_service import AuditLogImmutableError, get_audit_logs, log_action
import tests.helpers  # noqa: F401


def test_log_action_creates_entry(db_session):
    entry = log_action(db_session, "surgery.create", user_id=7, entity_type="surgery", entity_id=3)
    assert entry.log_id is not None
    assert entry.user_id == 7
    assert entry.action == "surgery.create"
    assert entry.entity_type == "surgery"
    assert entry.entity_id == 3
    assert entry.timestamp is not None


def test_user_id_from_token_subject_string_is_converted(db_session):
    entry = log_action(db_session, "staff.create", user_id="12")
    assert entry.user_id == 12


def test_non_numeric_user_id_is_stored_as_none(db_session):
    entry = log_action(db_session, "staff.create", user_id="not-a-number")
    assert entry.user_id is None


def test_audit_entry_cannot_be_modified(db_session):
    entry = log_action(db_session, "surgery.cancel", entity_type="surgery", entity_id=1)
    entry.action = "tampered"
    with pytest.raises(AuditLogImmutableError):
        db_session.commit()
    db_session.rollback()
    assert db_session.query(AuditLog).one().action == "surgery.cancel"


def test_audit_entry_cannot_be_deleted(db_session):
    entry = log_action(db_session, "surgery.cancel")
    db_session.delete(entry)
    with pytest.raises(AuditLogImmutableError):
        db_session.commit()
    db_session.rollback()
    assert db_session.query(AuditLog).count() == 1


def test_get_audit_logs_filters(db_session):
    log_action(db_session, "surgery.create", user_id=1, entity_type="surgery", entity_id=1)
    log_action(db_session, "surgery.cancel", user_id=2, entity_type="surgery", entity_id=1)
    log_action(db_session, "staff.create", user_id=1, entity_type="staff", entity_id=5)

    assert len(get_audit_logs(db_session)) == 3
    assert len(get_audit_logs(db_session, entity_type="surgery", entity_id=1)) == 2
    assert [e.action for e in get_audit_logs(db_session, user_id=2)] == ["surgery.cancel"]
    assert len(get_audit_logs(db_session, action="staff.create")) == 1
