from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.models import PriorityEnum, SurgeryStatusEnum


class EmergencyCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_name: str
    theatre_id: int
    start_time: datetime
    end_time: datetime
    priority: PriorityEnum = PriorityEnum.critical
    doctor_ids: List[int] = Field(default_factory=list)
    nurse_ids: List[int] = Field(default_factory=list)
    equipment_ids: List[int] = Field(default_factory=list)


class EmergencySlotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    surgery_id: int
    patient_name: str
    theatre_id: int
    start_time: datetime
    end_time: datetime
    priority: PriorityEnum
    status: SurgeryStatusEnum


class MovedSurgeryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    surgery_id: int
    patient_name: str
    old_start_time: datetime
    old_end_time: datetime
    new_start_time: datetime
    new_end_time: datetime
    status: SurgeryStatusEnum


class EmergencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    emergency_id: int
    slot: EmergencySlotResponse
    moved_surgeries: List[MovedSurgeryResponse] = Field(default_factory=list)
    notifications_created: int = 0


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_id: int
    user_id: int
    surgery_id: Optional[int] = None
    message: str
    created_at: datetime
    is_read: bool
