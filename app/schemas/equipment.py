from datetime import datetime
from typing import List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.models.models import EquipmentStatusEnum, TheatreStatusEnum


class ResourceModel(BaseModel):
    """Base schema: JSON uses camelCase as in SAD 4.3, Python code uses snake_case."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        str_strip_whitespace=True,
    )


class EquipmentCreate(ResourceModel):
    name: str = Field(min_length=1, max_length=100)
    category: Optional[str] = Field(default=None, min_length=1, max_length=100)
    status: EquipmentStatusEnum = EquipmentStatusEnum.available


class EquipmentUpdate(ResourceModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    category: Optional[str] = Field(default=None, min_length=1, max_length=100)
    status: Optional[EquipmentStatusEnum] = None


class EquipmentResponse(ResourceModel):
    equipment_id: int
    name: str
    category: Optional[str]
    status: EquipmentStatusEnum
    is_active: bool


class TheatreCreate(ResourceModel):
    name: str = Field(min_length=1, max_length=100)
    status: TheatreStatusEnum = TheatreStatusEnum.available


class TheatreUpdate(ResourceModel):
    name: str = Field(min_length=1, max_length=100)


class TheatreStatusUpdate(ResourceModel):
    status: TheatreStatusEnum


class TheatreResponse(ResourceModel):
    theatre_id: int
    name: str
    status: TheatreStatusEnum
    is_active: bool


class AvailabilityResponse(ResourceModel):
    available: bool
    status: str
    reasons: List[str]


class AllocationCreate(ResourceModel):
    surgery_id: int
    theatre_id: int
    # A set, so the same id sent twice is only allocated once
    equipment_ids: Set[int] = Field(min_length=1)


class AllocationResponse(ResourceModel):
    allocation_id: int
    surgery_id: int
    equipment_id: int
    theatre_id: int
    start_time: datetime
    end_time: datetime
    released: bool
