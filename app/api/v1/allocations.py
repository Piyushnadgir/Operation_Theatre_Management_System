from typing import List

from fastapi import APIRouter, Depends, status
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


@router.post("/{allocation_id}/release")
def release_allocation(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.scheduler, RoleEnum.admin)),
):
    EquipmentService(db).release_allocation(allocation_id, user_id=current_user.get("sub"))
    return {"status": "released"}
