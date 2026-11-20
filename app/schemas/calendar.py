import datetime as dt
import enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Weekday(str, enum.Enum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"

    @property
    def index(self) -> int:  # 0 = Monday, matches date.weekday()
        return list(Weekday).index(self)

    @classmethod
    def from_index(cls, i: int) -> "Weekday":
        return list(cls)[i]


# ---------- Week-off policies ----------
class WeekOffRuleIn(BaseModel):
    weekday: Weekday
    weeks_of_month: Optional[List[int]] = Field(
        None, description="Nth occurrence(s) of the weekday in the month, 1-5. Omit for every week."
    )

    @field_validator("weeks_of_month")
    @classmethod
    def validate_weeks(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is None or len(v) == 0:
            return None
        if any(w < 1 or w > 5 for w in v):
            raise ValueError("weeks_of_month values must be between 1 and 5")
        return sorted(set(v))


class WeekOffRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    weekday: Weekday
    weeks_of_month: Optional[List[int]] = None

    @field_validator("weekday", mode="before")
    @classmethod
    def from_int(cls, v):
        return Weekday.from_index(v) if isinstance(v, int) else v


class WeekOffPolicyIn(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    is_default: bool = False
    rules: List[WeekOffRuleIn] = Field(..., min_length=1)

    @field_validator("rules")
    @classmethod
    def unique_weekdays(cls, v: List[WeekOffRuleIn]) -> List[WeekOffRuleIn]:
        days = [r.weekday for r in v]
        if len(days) != len(set(days)):
            raise ValueError("each weekday may appear only once; list several weeks_of_month instead")
        return v


class WeekOffPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str]
    is_default: bool
    rules: List[WeekOffRuleOut]


class AssignWeekOffPolicy(BaseModel):
    policy_id: Optional[UUID] = Field(None, description="null = fall back to the default policy")


# ---------- Holidays ----------
class HolidayIn(BaseModel):
    date: dt.date
    name: str = Field(..., max_length=150)
    description: Optional[str] = None


class HolidayOut(HolidayIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


# ---------- Employee calendar ----------
class DayStatus(str, enum.Enum):
    WORKING = "working"
    WEEK_OFF = "week_off"
    HOLIDAY = "holiday"
    LEAVE = "leave"


class CalendarDay(BaseModel):
    date: dt.date
    weekday: Weekday
    status: DayStatus
    detail: Optional[str] = None  # holiday name / leave type code
    leave_request_id: Optional[UUID] = None
    half_day: bool = False


class CalendarSummary(BaseModel):
    working: int
    week_off: int
    holiday: int
    leave: float


class EmployeeCalendar(BaseModel):
    employee_id: UUID
    start: dt.date
    end: dt.date
    week_off_policy: Optional[WeekOffPolicyOut]
    summary: CalendarSummary
    days: List[CalendarDay]
