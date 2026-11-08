"""OT-F-032 (login), OT-SR-002 (hashed passwords), OT-SR-004 (lockout) at service level."""
from datetime import timedelta

import pytest

from app.core.security import decode_access_token
from app.models.models import RoleEnum, User
from app.services.audit_service import get_audit_logs
from app.services.auth_service import (
    MAX_FAILED_ATTEMPTS,
    AccountLockedError,
    AuthService,
    DuplicateUserError,
    InvalidCredentialsError,
    _utcnow,
)
from tests.helpers import PASSWORD


def _fail_login(service, username, times):
    for _ in range(times):
        with pytest.raises(InvalidCredentialsError):
            service.authenticate(username, "wrong-password")


def test_create_user_stores_hash_not_plaintext(db_session):
    user = AuthService(db_session).create_user("alice", PASSWORD, RoleEnum.scheduler)
    assert user.password_hash != PASSWORD
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$2")  # bcrypt


def test_duplicate_username_rejected(db_session):
    service = AuthService(db_session)
    service.create_user("alice", PASSWORD, RoleEnum.scheduler)
    with pytest.raises(DuplicateUserError):
        service.create_user("alice", PASSWORD, RoleEnum.nurse)


def test_invalid_role_rejected(db_session):
    with pytest.raises(ValueError):
        AuthService(db_session).create_user("bob", PASSWORD, "surgeon-king")


def test_login_success_returns_token_with_role(db_session):
    service = AuthService(db_session)
    user = service.create_user("alice", PASSWORD, RoleEnum.scheduler)
    token, role = service.authenticate("alice", PASSWORD)
    assert role == "scheduler"
    payload = decode_access_token(token)
    assert payload["sub"] == str(user.user_id)
    assert payload["role"] == "scheduler"
    assert "exp" in payload  # sessions expire


def test_login_wrong_password(db_session):
    service = AuthService(db_session)
    service.create_user("alice", PASSWORD, RoleEnum.scheduler)
    with pytest.raises(InvalidCredentialsError):
        service.authenticate("alice", "wrong-password")


def test_login_unknown_user(db_session):
    with pytest.raises(InvalidCredentialsError):
        AuthService(db_session).authenticate("nobody", PASSWORD)


def test_account_locks_after_five_failures_even_with_correct_password(db_session):
    service = AuthService(db_session)
    service.create_user("alice", PASSWORD, RoleEnum.scheduler)

    _fail_login(service, "alice", MAX_FAILED_ATTEMPTS)

    with pytest.raises(AccountLockedError):
        service.authenticate("alice", PASSWORD)  # 6th attempt, right password


def test_four_failures_do_not_lock(db_session):
    service = AuthService(db_session)
    service.create_user("alice", PASSWORD, RoleEnum.scheduler)
    _fail_login(service, "alice", MAX_FAILED_ATTEMPTS - 1)
    token, _ = service.authenticate("alice", PASSWORD)
    assert token


def test_successful_login_resets_failed_attempts(db_session):
    service = AuthService(db_session)
    service.create_user("alice", PASSWORD, RoleEnum.scheduler)
    _fail_login(service, "alice", 3)
    service.authenticate("alice", PASSWORD)
    assert db_session.query(User).filter_by(username="alice").one().failed_attempts == 0


def test_lock_expires(db_session):
    service = AuthService(db_session)
    user = service.create_user("alice", PASSWORD, RoleEnum.scheduler)
    _fail_login(service, "alice", MAX_FAILED_ATTEMPTS)
    user.locked_until = _utcnow() - timedelta(minutes=1)
    db_session.commit()

    token, _ = service.authenticate("alice", PASSWORD)
    assert token
    db_session.refresh(user)
    assert user.failed_attempts == 0 and user.locked_until is None


def test_admin_can_unlock(db_session):
    service = AuthService(db_session)
    user = service.create_user("alice", PASSWORD, RoleEnum.scheduler)
    _fail_login(service, "alice", MAX_FAILED_ATTEMPTS)

    assert service.unlock_user(user.user_id) is not None
    token, _ = service.authenticate("alice", PASSWORD)
    assert token


def test_unlock_unknown_user_returns_none(db_session):
    assert AuthService(db_session).unlock_user(999) is None


def test_login_events_are_audited(db_session):
    service = AuthService(db_session)
    user = service.create_user("alice", PASSWORD, RoleEnum.scheduler)
    _fail_login(service, "alice", MAX_FAILED_ATTEMPTS)
    with pytest.raises(AccountLockedError):
        service.authenticate("alice", PASSWORD)

    actions = [e.action for e in get_audit_logs(db_session, user_id=user.user_id)]
    assert actions.count("login_failed") == MAX_FAILED_ATTEMPTS
    assert "account_locked" in actions
    assert "login_blocked" in actions

    service.unlock_user(user.user_id)
    service.authenticate("alice", PASSWORD)
    actions = [e.action for e in get_audit_logs(db_session, user_id=user.user_id)]
    assert "login_success" in actions


def test_password_never_written_to_audit_log(db_session):
    service = AuthService(db_session)
    service.create_user("alice", PASSWORD, RoleEnum.scheduler)
    _fail_login(service, "alice", 2)
    service.authenticate("alice", PASSWORD)
    for entry in get_audit_logs(db_session):
        assert PASSWORD not in (entry.details or "")
        assert "wrong-password" not in (entry.details or "")
