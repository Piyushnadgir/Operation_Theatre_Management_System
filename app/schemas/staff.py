from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.models import StaffTypeEnum


def _strip_or_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


class StaffCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    staff_type: StaffTypeEnum
    specialization: Optional[str] = Field(default=None, max_length=100)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("specialization")
    @classmethod
    def clean_specialization(cls, value):
        return _strip_or_none(value)


class StaffUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    specialization: Optional[str] = Field(default=None, max_length=100)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("specialization")
    @classmethod
    def clean_specialization(cls, value):
        return _strip_or_none(value)

    @model_validator(mode="after")
    def at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("provide at least one field to update")
        return self


class StaffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    staff_id: int
    name: str
    staff_type: StaffTypeEnum
    specialization: Optional[str] = None
    is_active: bool


class AssignmentCheckRequest(BaseModel):
    doctor_ids: List[int] = Field(default_factory=list, max_length=50)
    nurse_ids: List[int] = Field(default_factory=list, max_length=50)
    start_time: datetime
    end_time: datetime
    required_specialization: Optional[str] = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def end_after_start(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class AssignmentIssue(BaseModel):
    resource_type: str
    resource_id: int
    message: str


class AssignmentCheckResponse(BaseModel):
    valid: bool
    conflicts: List[AssignmentIssue]
