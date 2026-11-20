from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.leave import LeaveStatus


# ---------- Leave types ----------
class LeaveTypeCreate(BaseModel):
    name: str = Field(..., max_length=100)
    code: str = Field(..., max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    description: Optional[str] = None
    annual_quota: Decimal = Field(Decimal("0"), ge=0, max_digits=5, decimal_places=1)
    is_paid: bool = True
    is_active: bool = True


class LeaveTypeUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    annual_quota: Optional[Decimal] = Field(None, ge=0, max_digits=5, decimal_places=1)
    is_paid: Optional[bool] = None
    is_active: Optional[bool] = None


class LeaveTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    description: Optional[str]
    annual_quota: float
    is_paid: bool
    is_active: bool


# ---------- Balances ----------
class LeaveAllocationIn(BaseModel):
    leave_type_id: UUID
    year: int = Field(..., ge=2000, le=2100)
    allocated: Decimal = Field(..., ge=0, max_digits=5, decimal_places=1)


class LeaveBalanceOut(BaseModel):
    leave_type_id: UUID
    leave_type_code: str
    leave_type_name: str
    is_paid: bool
    year: int
    allocated: float
    is_custom_allocation: bool  # False = using the leave type's annual_quota
    used: float  # approved
    pending: float
    available: Optional[float]  # allocated - used - pending; null for unpaid types


# ---------- Leave requests ----------
class LeaveApply(BaseModel):
    leave_type_id: UUID
    start_date: date
    end_date: date
    half_day: bool = False
    reason: Optional[str] = None

    @model_validator(mode="after")
    def check_dates(self) -> "LeaveApply":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.half_day and self.start_date != self.end_date:
            raise ValueError("half_day leave must start and end on the same date")
        if self.start_date.year != self.end_date.year:
            raise ValueError("a leave request cannot span two calendar years; split it in two")
        return self


class LeaveDecision(BaseModel):
    note: Optional[str] = None


class LeaveRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_id: UUID
    leave_type_id: UUID
    leave_type_code: str
    start_date: date
    end_date: date
    half_day: bool
    days: float
    reason: Optional[str]
    status: LeaveStatus
    requested_by_id: Optional[UUID]
    decided_by_id: Optional[UUID]
    decided_at: Optional[datetime]
    decision_note: Optional[str]
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def flatten_leave_type(cls, data):
        # Pull the code off the related LeaveType when building from an ORM object
        if not isinstance(data, dict) and hasattr(data, "leave_type"):
            return {
                **{k: getattr(data, k) for k in cls.model_fields if k != "leave_type_code"},
                "leave_type_code": data.leave_type.code,
            }
        return data
