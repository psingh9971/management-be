import datetime as dt
import enum
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.models.attendance import AttendanceStatus, PunchType


class PunchWebhookIn(BaseModel):
    """Payload sent by the biometric device / attendance middleware."""
    employee_code: str = Field(..., max_length=50)
    punch_time: datetime
    punch_type: Optional[PunchType] = None
    device_id: str = Field("unknown", max_length=100)


class PunchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    employee_id: UUID
    punch_time: datetime
    punch_type: Optional[PunchType]
    device_id: str
    source: str
    received_at: datetime


class PunchWebhookResult(BaseModel):
    status: str  # "created" | "duplicate"
    punch: PunchOut


# ---------- Daily attendance (manual marking) ----------
STATUSES_WITH_TIMES = (AttendanceStatus.PRESENT, AttendanceStatus.HALF_DAY)


class ManualAttendanceIn(BaseModel):
    """Mark an employee's attendance for a day. check_in/check_out are optional and only
    allowed for present/half_day; they must include a timezone offset, e.g. +05:30."""

    date: dt.date
    status: AttendanceStatus
    check_in: Optional[AwareDatetime] = None
    check_out: Optional[AwareDatetime] = None
    note: str = Field(..., min_length=3, description="Reason for the manual entry (kept for audit)")

    @model_validator(mode="after")
    def check_times(self) -> "ManualAttendanceIn":
        has_times = self.check_in is not None or self.check_out is not None
        if has_times and self.status not in STATUSES_WITH_TIMES:
            raise ValueError(f"check_in/check_out are not allowed when status is '{self.status.value}'")
        if self.check_out is not None and self.check_in is None:
            raise ValueError("check_out requires check_in")
        if self.check_in is not None and self.check_in.date() != self.date:
            raise ValueError("check_in must fall on the given date (in its own timezone)")
        if self.check_in is not None and self.check_out is not None:
            if self.check_out <= self.check_in:
                raise ValueError("check_out must be after check_in")
            if (self.check_out - self.check_in).total_seconds() > 24 * 3600:
                raise ValueError("check_out must be within 24 hours of check_in")
        return self


class AttendanceRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_id: UUID
    date: dt.date
    status: AttendanceStatus
    check_in: Optional[datetime]
    check_out: Optional[datetime]
    source: str
    note: Optional[str]
    marked_by_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime


# ---------- Combined attendance view (manual records + device punches + calendar) ----------
class DayStatus(str, enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"
    HALF_DAY = "half_day"
    WEEK_OFF = "week_off"
    LEAVE = "leave"
    HOLIDAY = "holiday"
    NO_RECORD = "no_record"


class DaySource(str, enum.Enum):
    MANUAL = "manual"      # attendance_records (manual marking) - always wins
    DEVICE = "device"      # derived from attendance_punches
    LEAVE = "leave"        # approved leave request
    HOLIDAY = "holiday"    # company holiday
    WEEK_OFF = "week_off"  # employee's week-off policy
    NONE = "none"


class PunchBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    punch_time: datetime
    punch_type: Optional[PunchType]
    device_id: str


class AttendanceDay(BaseModel):
    date: dt.date
    weekday: str
    status: DayStatus
    source: DaySource
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    worked_hours: Optional[float] = None
    detail: Optional[str] = None  # holiday name / leave type code
    note: Optional[str] = None  # manual entry reason
    marked_by_id: Optional[UUID] = None
    record_id: Optional[UUID] = None  # attendance_records.id when source=manual
    leave_request_id: Optional[UUID] = None
    # Raw device punches for the day, shown even when a manual record overrides them
    punches: List[PunchBrief] = []


class AttendanceSummary(BaseModel):
    present: int = 0
    absent: int = 0
    half_day: int = 0
    week_off: int = 0
    leave: int = 0
    holiday: int = 0
    no_record: int = 0
    total_worked_hours: float = 0


class AttendanceReport(BaseModel):
    employee_id: UUID
    start: dt.date
    end: dt.date
    timezone: str
    summary: AttendanceSummary
    days: List[AttendanceDay]


class EmployeeAttendanceSummary(BaseModel):
    employee_id: UUID
    employee_code: str
    name: str
    department: Optional[str]
    designation: Optional[str]
    is_active: bool
    summary: AttendanceSummary


class EmployeeDayAttendance(BaseModel):
    employee_id: UUID
    employee_code: str
    name: str
    department: Optional[str]
    designation: Optional[str]
    is_active: bool
    attendance: AttendanceDay


class DailyAttendance(BaseModel):
    date: dt.date
    weekday: str
    timezone: str
    # Counts across ALL employees matching department/is_active/search (before the status filter)
    summary: AttendanceSummary
    total: int  # employees in `items` across all pages (after the status filter)
    skip: int
    limit: int
    items: List[EmployeeDayAttendance]


class MonthlyAttendanceSummary(BaseModel):
    month: str  # YYYY-MM
    start: dt.date
    end: dt.date
    days_in_month: int
    timezone: str
    total: int  # employees matching the filters
    skip: int
    limit: int
    items: List[EmployeeAttendanceSummary]
