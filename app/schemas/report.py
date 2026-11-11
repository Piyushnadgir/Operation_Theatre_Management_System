from datetime import datetime
from typing import List

from app.schemas.equipment import ResourceModel


class UsageTotals(ResourceModel):
    booked_minutes: int
    available_minutes: int
    usage_percent: float


class TheatreUsage(UsageTotals):
    theatre_id: int
    name: str


class EquipmentUsage(UsageTotals):
    equipment_id: int
    name: str


class ReportTotals(ResourceModel):
    theatres: UsageTotals
    equipment: UsageTotals


class UtilizationReport(ResourceModel):
    start: datetime
    end: datetime
    range_minutes: int
    theatres: List[TheatreUsage]
    equipment: List[EquipmentUsage]
    totals: ReportTotals
