"""Login, password hashing, lockout and roles (OT-F-032, OT-SR-002, OT-SR-004)."""
from datetime import datetime, timedelta, timezone
from typing import Tuple

from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.models import RoleEnum, User
from app.services.audit_service import log_action

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=15)


class AuthError(Exception):
    pass


class InvalidCredentialsError(AuthError):
    pass


class AccountLockedError(AuthError):
    def __init__(self, locked_until: datetime):
        super().__init__("Account is locked")
        self.locked_until = locked_until


class DuplicateUserError(AuthError):
    pass


def _utcnow() -> datetime:
    # The database stores naive UTC datetimes.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def create_user(self, username: str, password: str, role) -> User:
        role = RoleEnum(role)
        if self.db.query(User).filter(User.username == username).first() is not None:
            raise DuplicateUserError(f"Username '{username}' already exists")
        user = User(
            username=username,
            password_hash=get_password_hash(password),
            role=role,
            failed_attempts=0,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def authenticate(self, username: str, password: str) -> Tuple[str, str]:
        """Return (token, role). Raises InvalidCredentialsError or AccountLockedError."""
        now = _utcnow()
        user = self.db.query(User).filter(User.username == username).first()

        if user is None:
            log_action(self.db, "login_failed", details="unknown username")
            raise InvalidCredentialsError("Invalid username or password")

        if user.locked_until is not None:
            if user.locked_until > now:
                # Blocked even when the password is correct (OT-SR-004).
                log_action(self.db, "login_blocked", user_id=user.user_id,
                           entity_type="user", entity_id=user.user_id)
                raise AccountLockedError(user.locked_until)
            # Lock has expired: start fresh.
            user.locked_until = None
            user.failed_attempts = 0
            self.db.commit()

        if not verify_password(password, user.password_hash):
            user.failed_attempts = (user.failed_attempts or 0) + 1
            locked_now = user.failed_attempts >= MAX_FAILED_ATTEMPTS
            if locked_now:
                user.locked_until = now + LOCK_DURATION
            self.db.commit()
            log_action(self.db, "login_failed", user_id=user.user_id,
                       entity_type="user", entity_id=user.user_id)
            if locked_now:
                log_action(self.db, "account_locked", user_id=user.user_id,
                           entity_type="user", entity_id=user.user_id)
            raise InvalidCredentialsError("Invalid username or password")

        user.failed_attempts = 0
        user.locked_until = None
        self.db.commit()
        token = create_access_token(
            {"sub": str(user.user_id), "username": user.username, "role": user.role.value}
        )
        log_action(self.db, "login_success", user_id=user.user_id,
                   entity_type="user", entity_id=user.user_id)
        return token, user.role.value

    def unlock_user(self, user_id: int, acting_user_id=None):
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if user is None:
            return None
        user.failed_attempts = 0
        user.locked_until = None
        self.db.commit()
        self.db.refresh(user)
        log_action(self.db, "account_unlocked", user_id=acting_user_id,
                   entity_type="user", entity_id=user_id)
        return user
