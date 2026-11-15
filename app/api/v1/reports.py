from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.errors import ResourceRoute
from app.core.database import get_db
from app.core.deps import require_roles
from app.models.models import RoleEnum
from app.schemas.report import UtilizationReport
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["Reports"], route_class=ResourceRoute)


@router.get("/utilization", response_model=UtilizationReport)
def utilization_report(
    start: datetime = Query(..., alias="from"),
    end: datetime = Query(..., alias="to"),
    theatre_id: Optional[int] = Query(None, alias="theatreId"),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.admin, RoleEnum.scheduler)),
):
    """Usage % per theatre and equipment item for [from, to). `to` is exclusive."""
    return ReportService(db).utilization(start, end, theatre_id)
