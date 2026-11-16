from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.errors import ResourceRoute
from app.core.database import get_db
from app.core.deps import require_roles
from app.models.models import RoleEnum
from app.schemas.equipment import AllocationCreate, AllocationResponse
from app.services.equipment_service import EquipmentService

router = APIRouter(prefix="/allocations", tags=["Allocations"], route_class=ResourceRoute)


@router.post("", response_model=List[AllocationResponse], status_code=status.HTTP_201_CREATED)
def create_allocations(
    allocation_data: AllocationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.scheduler, RoleEnum.admin)),
):
    return EquipmentService(db).allocate(
        surgery_id=allocation_data.surgery_id,
        theatre_id=allocation_data.theatre_id,
        equipment_ids=sorted(allocation_data.equipment_ids),
        user_id=current_user.get("sub"),
    )


@router.get("", response_model=List[AllocationResponse])
def list_allocations(
    surgery_id: Optional[int] = Query(None, alias="surgeryId"),
    equipment_id: Optional[int] = Query(None, alias="equipmentId"),
    include_released: bool = Query(False, alias="includeReleased"),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.scheduler, RoleEnum.admin)),
):
    """The Web UI needs the allocation ids to release them and to keep equipment on reschedule."""
    return EquipmentService(db).list_allocations(surgery_id, equipment_id, include_released)


@router.post("/{allocation_id}/release")
def release_allocation(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.scheduler, RoleEnum.admin)),
):
    EquipmentService(db).release_allocation(allocation_id, user_id=current_user.get("sub"))
    return {"status": "released"}
