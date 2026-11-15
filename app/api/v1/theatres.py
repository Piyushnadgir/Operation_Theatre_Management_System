from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.errors import ResourceRoute
from app.core.database import get_db
from app.core.deps import get_current_user, require_roles
from app.models.models import RoleEnum
from app.schemas.equipment import (
    AvailabilityResponse,
    TheatreCreate,
    TheatreResponse,
    TheatreStatusUpdate,
    TheatreUpdate,
)
from app.services.equipment_service import EquipmentService

router = APIRouter(prefix="/theatres", tags=["Theatres"], route_class=ResourceRoute)


@router.post("", response_model=TheatreResponse, status_code=status.HTTP_201_CREATED)
def create_theatre(
    theatre_data: TheatreCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.admin)),
):
    return EquipmentService(db).create_theatre(name=theatre_data.name, status=theatre_data.status)


@router.get("", response_model=List[TheatreResponse])
def list_theatres(
    include_retired: bool = Query(False, alias="includeRetired"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return EquipmentService(db).list_theatres(include_retired=include_retired)


@router.put("/{theatre_id}", response_model=TheatreResponse)
def update_theatre(
    theatre_id: int,
    theatre_data: TheatreUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.admin)),
):
    return EquipmentService(db).update_theatre(theatre_id, name=theatre_data.name)


@router.patch("/{theatre_id}/status", response_model=TheatreResponse)
def update_theatre_status(
    theatre_id: int,
    status_data: TheatreStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.admin)),
):
    return EquipmentService(db).update_theatre_status(theatre_id, status_data.status)


@router.delete("/{theatre_id}")
def retire_theatre(
    theatre_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.admin)),
):
    EquipmentService(db).retire_theatre(theatre_id)
    return {"status": "deactivated"}


@router.get("/{theatre_id}/availability", response_model=AvailabilityResponse)
def theatre_availability(
    theatre_id: int,
    start: datetime = Query(...),
    end: datetime = Query(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return EquipmentService(db).theatre_availability(theatre_id, start, end)
