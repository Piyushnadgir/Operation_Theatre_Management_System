"""Append-only audit log (OT-SR-005).

Other modules call ``log_action`` after every create / change / cancel, e.g.::

    log_action(db, "surgery.cancel", user_id=current_user.get("sub"),
               entity_type="surgery", entity_id=surgery_id)

Never put passwords, tokens or other secrets in ``details``.
"""
from typing import List, Optional, Union

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.models import AuditLog


class AuditLogImmutableError(Exception):
    """Raised when code tries to modify or delete an audit log entry."""


# The application can only add rows. (Bulk ``query.delete()`` bypasses ORM
# events, but nothing in the application does that.)
@event.listens_for(AuditLog, "before_update")
def _block_audit_update(mapper, connection, target):
    raise AuditLogImmutableError("Audit log entries cannot be modified")


@event.listens_for(AuditLog, "before_delete")
def _block_audit_delete(mapper, connection, target):
    raise AuditLogImmutableError("Audit log entries cannot be deleted")


def _as_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def log_action(
    db: Session,
    action: str,
    user_id: Union[int, str, None] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    details: Optional[str] = None,
    commit: bool = True,
) -> AuditLog:
    entry = AuditLog(
        user_id=_as_int(user_id),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    else:
        db.flush()
    return entry


def get_audit_logs(
    db: Session,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    limit: int = 100,
) -> List[AuditLog]:
    query = db.query(AuditLog)
    if entity_type is not None:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AuditLog.entity_id == entity_id)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if action is not None:
        query = query.filter(AuditLog.action == action)
    return query.order_by(AuditLog.log_id).limit(limit).all()
