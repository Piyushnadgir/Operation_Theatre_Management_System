from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.errors import ResourceRoute
from app.core.database import get_db
from app.core.deps import get_current_user, require_roles
from app.models.models import RoleEnum
from app.schemas.emergency import (
    EmergencyCreate,
    EmergencyResponse,
    EmergencySlotResponse,
    NotificationResponse,
)
from app.services.emergency_service import (
    EmergencyConflictError,
    EmergencyNotFoundError,
    EmergencyService,
    EmergencyValidationError,
)

router = APIRouter(prefix="/emergencies", tags=["Emergencies"], route_class=ResourceRoute)


def _current_user_id(current_user: dict) -> Optional[int]:
    sub = current_user.get("sub") if isinstance(current_user, dict) else None
    if sub is None:
        return None
    try:
        return int(sub)
    except (TypeError, ValueError):
        return None


@router.post("", response_model=EmergencyResponse, status_code=status.HTTP_201_CREATED)
def log_emergency(
    body: EmergencyCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.admin, RoleEnum.doctor, RoleEnum.scheduler)),
):
    service = EmergencyService(db)
    try:
        surgery, case, moved, notif_count = service.log_and_process_emergency(
            emergency_data=body,
            logged_by_user_id=_current_user_id(current_user),
        )
    except EmergencyValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Bad Request", "message": str(exc)},
        )
    except EmergencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Conflict", "message": str(exc)},
        )

    return EmergencyResponse(
        emergency_id=case.emergency_id,
        slot=EmergencySlotResponse.model_validate(surgery),
        moved_surgeries=moved,
        notifications_created=notif_count,
    )


@router.get("/queue", response_model=List[EmergencySlotResponse])
def get_emergency_queue(
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.admin, RoleEnum.doctor, RoleEnum.nurse, RoleEnum.scheduler)),
):
    return EmergencyService(db).get_priority_queue()


@router.get("/notifications", response_model=List[NotificationResponse])
def list_notifications(
    user_id: Optional[int] = Query(None),
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    caller_id = _current_user_id(current_user)
    target_id = user_id if user_id is not None else caller_id
    if target_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Bad Request", "message": "Unable to resolve user_id"},
        )
    if target_id != caller_id and current_user.get("role") not in {RoleEnum.admin.value, RoleEnum.scheduler.value}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
    return EmergencyService(db).get_notifications(target_id, unread_only=unread_only)


@router.patch("/notifications/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    caller_id = _current_user_id(current_user)
    if caller_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Bad Request", "message": "Unable to resolve user_id"},
        )
    try:
        return EmergencyService(db).mark_notification_read(notification_id, caller_id)
    except EmergencyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Not Found", "message": str(exc)},
        )
