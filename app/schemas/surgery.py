from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.models import PriorityEnum, SurgeryStatusEnum


class SurgeryBase(BaseModel):
    patient_name: str
    theatre_id: int
    start_time: datetime
    end_time: datetime
    doctor_ids: List[int] = Field(default_factory=list)
    nurse_ids: List[int] = Field(default_factory=list)
    equipment_ids: List[int] = Field(default_factory=list)
    priority: PriorityEnum = PriorityEnum.routine


class SurgeryCreate(SurgeryBase):
    pass


class SurgeryUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    theatre_id: Optional[int] = None
    doctor_ids: Optional[List[int]] = None
    nurse_ids: Optional[List[int]] = None
    equipment_ids: Optional[List[int]] = None


class SurgeryResponse(BaseModel):
    surgery_id: int
    patient_name: str
    theatre_id: int
    start_time: datetime
    end_time: datetime
    priority: PriorityEnum
    status: SurgeryStatusEnum

    class Config:
        from_attributes = True


class ConflictDetail(BaseModel):
    resource_type: str
    resource_id: int
    message: str


class ConflictResponse(BaseModel):
    error: str = "Conflict"
    message: str
    conflicts: List[ConflictDetail]
