from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base
import enum


class RoleEnum(str, enum.Enum):
    admin = "admin"
    doctor = "doctor"
    nurse = "nurse"
    scheduler = "scheduler"


class PriorityEnum(str, enum.Enum):
    routine = "routine"
    urgent = "urgent"
    critical = "critical"


class SurgeryStatusEnum(str, enum.Enum):
    scheduled = "scheduled"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class TheatreStatusEnum(str, enum.Enum):
    available = "available"
    occupied = "occupied"
    cleaning = "cleaning"
    maintenance = "maintenance"


class EquipmentStatusEnum(str, enum.Enum):
    available = "available"
    in_use = "in_use"
    maintenance = "maintenance"


class StaffTypeEnum(str, enum.Enum):
    doctor = "doctor"
    nurse = "nurse"


class User(Base):
    __tablename__ = "app_user"

    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(RoleEnum), nullable=False)
    failed_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    staff = relationship("Staff", back_populates="user", uselist=False)


class Staff(Base):
    __tablename__ = "staff"

    staff_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("app_user.user_id"), nullable=True)
    name = Column(String, nullable=False)
    staff_type = Column(Enum(StaffTypeEnum), nullable=False)
    specialization = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="staff")
    shifts = relationship("Shift", back_populates="staff")
    surgery_staff = relationship("SurgeryStaff", back_populates="staff")


class Shift(Base):
    __tablename__ = "shift"

    shift_id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(Integer, ForeignKey("staff.staff_id"), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)

    staff = relationship("Staff", back_populates="shifts")


class Theatre(Base):
    __tablename__ = "theatre"

    theatre_id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    status = Column(Enum(TheatreStatusEnum), default=TheatreStatusEnum.available)

    surgeries = relationship("Surgery", back_populates="theatre")


class Equipment(Base):
    __tablename__ = "equipment"

    equipment_id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=True)
    status = Column(Enum(EquipmentStatusEnum), default=EquipmentStatusEnum.available)
    is_active = Column(Boolean, default=True)

    allocations = relationship("Allocation", back_populates="equipment")


class Surgery(Base):
    __tablename__ = "surgery"

    surgery_id = Column(Integer, primary_key=True, index=True)
    patient_name = Column(String, nullable=False)
    theatre_id = Column(Integer, ForeignKey("theatre.theatre_id"), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    priority = Column(Enum(PriorityEnum), default=PriorityEnum.routine)
    status = Column(Enum(SurgeryStatusEnum), default=SurgeryStatusEnum.scheduled)
    created_by = Column(Integer, ForeignKey("app_user.user_id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    theatre = relationship("Theatre", back_populates="surgeries")
    surgery_staff = relationship("SurgeryStaff", back_populates="surgery")
    emergency_case = relationship("EmergencyCase", back_populates="surgery", uselist=False)
    allocations = relationship("Allocation", back_populates="surgery")


class SurgeryStaff(Base):
    __tablename__ = "surgery_staff"
    __table_args__ = (UniqueConstraint("surgery_id", "staff_id", name="uq_surgery_staff"),)

    id = Column(Integer, primary_key=True)
    surgery_id = Column(Integer, ForeignKey("surgery.surgery_id"), nullable=False)
    staff_id = Column(Integer, ForeignKey("staff.staff_id"), nullable=False)

    surgery = relationship("Surgery", back_populates="surgery_staff")
    staff = relationship("Staff", back_populates="surgery_staff")


class EmergencyCase(Base):
    __tablename__ = "emergency_case"

    emergency_id = Column(Integer, primary_key=True, index=True)
    surgery_id = Column(Integer, ForeignKey("surgery.surgery_id"), nullable=False)
    logged_by = Column(Integer, ForeignKey("app_user.user_id"), nullable=True)
    logged_at = Column(DateTime(timezone=True), server_default=func.now())

    surgery = relationship("Surgery", back_populates="emergency_case")


class Allocation(Base):
    __tablename__ = "allocation"

    allocation_id = Column(Integer, primary_key=True, index=True)
    surgery_id = Column(Integer, ForeignKey("surgery.surgery_id"), nullable=False)
    equipment_id = Column(Integer, ForeignKey("equipment.equipment_id"), nullable=False)
    theatre_id = Column(Integer, ForeignKey("theatre.theatre_id"), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    released = Column(Boolean, default=False)

    surgery = relationship("Surgery", back_populates="allocations")
    equipment = relationship("Equipment", back_populates="allocations")


class Notification(Base):
    __tablename__ = "notification"

    notification_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("app_user.user_id"), nullable=False)
    surgery_id = Column(Integer, ForeignKey("surgery.surgery_id"), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_read = Column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    log_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("app_user.user_id"), nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=True)
    entity_id = Column(Integer, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    details = Column(Text, nullable=True)
