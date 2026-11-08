from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ShiftIn(BaseModel):
    start_time: datetime
    end_time: datetime

    @model_validator(mode="after")
    def end_after_start(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class ShiftsUpdate(BaseModel):
    shifts: List[ShiftIn] = Field(max_length=100)


class ShiftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shift_id: int
    staff_id: int
    start_time: datetime
    end_time: datetime


class ShiftsResponse(BaseModel):
    shifts: List[ShiftResponse]


class AvailabilityResponse(BaseModel):
    available: bool
