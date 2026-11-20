from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Iterator, List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.calendar import Holiday, WeekOffPolicy, WeekOffRule
from app.models.employee import Employee
from app.models.leave import LeaveRequest, LeaveStatus
from app.repositories.errors import ConflictError, NotFoundError
from app.schemas.calendar import (
    CalendarDay,
    CalendarSummary,
    DayStatus,
    HolidayIn,
    WeekOffPolicyIn,
    Weekday,
)


# ---------- Week-off policies ----------
def list_policies(db: Session) -> List[WeekOffPolicy]:
    return list(db.scalars(select(WeekOffPolicy).order_by(WeekOffPolicy.name)).all())


def get_policy(db: Session, policy_id: UUID) -> WeekOffPolicy:
    policy = db.get(WeekOffPolicy, policy_id)
    if policy is None:
        raise NotFoundError("Week-off policy not found")
    return policy


def get_default_policy(db: Session) -> Optional[WeekOffPolicy]:
    return db.scalars(select(WeekOffPolicy).where(WeekOffPolicy.is_default.is_(True))).first()


def _apply_policy_fields(db: Session, policy: WeekOffPolicy, data: WeekOffPolicyIn) -> None:
    clash = db.scalar(
        select(WeekOffPolicy.id).where(WeekOffPolicy.name == data.name, WeekOffPolicy.id != policy.id)
    )
    if clash:
        raise ConflictError(f"A week-off policy named '{data.name}' already exists")
    if data.is_default:
        # Only one default allowed: demote the current one
        db.execute(
            update(WeekOffPolicy)
            .where(WeekOffPolicy.is_default.is_(True), WeekOffPolicy.id != policy.id)
            .values(is_default=False)
        )
    policy.name = data.name
    policy.description = data.description
    policy.is_default = data.is_default
    if policy.rules:
        # The unit of work inserts before it deletes, which would collide with the
        # (policy_id, weekday) unique constraint - so remove old rules first.
        policy.rules = []
        db.flush()
    policy.rules = [
        WeekOffRule(weekday=r.weekday.index, weeks_of_month=r.weeks_of_month) for r in data.rules
    ]


def create_policy(db: Session, data: WeekOffPolicyIn) -> WeekOffPolicy:
    policy = WeekOffPolicy()
    _apply_policy_fields(db, policy, data)
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


def replace_policy(db: Session, policy_id: UUID, data: WeekOffPolicyIn) -> WeekOffPolicy:
    policy = get_policy(db, policy_id)
    _apply_policy_fields(db, policy, data)
    db.commit()
    db.refresh(policy)
    return policy


def assign_policy(db: Session, employee: Employee, policy_id: Optional[UUID]) -> Optional[WeekOffPolicy]:
    if policy_id is not None:
        get_policy(db, policy_id)
    employee.week_off_policy_id = policy_id
    db.commit()
    return effective_policy(db, employee)


def effective_policy(db: Session, employee: Employee) -> Optional[WeekOffPolicy]:
    if employee.week_off_policy_id:
        return db.get(WeekOffPolicy, employee.week_off_policy_id)
    return get_default_policy(db)


def is_week_off(day: date, policy: Optional[WeekOffPolicy]) -> bool:
    if policy is None:
        return False
    nth = (day.day - 1) // 7 + 1  # nth occurrence of this weekday in the month
    for rule in policy.rules:
        if rule.weekday == day.weekday() and (not rule.weeks_of_month or nth in rule.weeks_of_month):
            return True
    return False


# ---------- Holidays ----------
def create_holiday(db: Session, data: HolidayIn) -> Holiday:
    if db.scalar(select(Holiday.id).where(Holiday.date == data.date)):
        raise ConflictError(f"A holiday already exists on {data.date}")
    holiday = Holiday(**data.model_dump())
    db.add(holiday)
    db.commit()
    db.refresh(holiday)
    return holiday


def list_holidays(db: Session, year: Optional[int] = None) -> List[Holiday]:
    stmt = select(Holiday).order_by(Holiday.date)
    if year:
        stmt = stmt.where(Holiday.date >= date(year, 1, 1), Holiday.date <= date(year, 12, 31))
    return list(db.scalars(stmt).all())


def delete_holiday(db: Session, holiday_id: UUID) -> None:
    holiday = db.get(Holiday, holiday_id)
    if holiday is None:
        raise NotFoundError("Holiday not found")
    db.delete(holiday)
    db.commit()


def holidays_between(db: Session, start: date, end: date) -> Dict[date, Holiday]:
    rows = db.scalars(select(Holiday).where(Holiday.date >= start, Holiday.date <= end)).all()
    return {h.date: h for h in rows}


# ---------- Working-day calculations ----------
def _days(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def count_leave_days(db: Session, employee: Employee, start: date, end: date, half_day: bool) -> Decimal:
    """Working days in [start, end], skipping week-offs and holidays."""
    policy = effective_policy(db, employee)
    holidays = holidays_between(db, start, end)
    working = sum(1 for d in _days(start, end) if not is_week_off(d, policy) and d not in holidays)
    if half_day:
        return Decimal("0.5") if working else Decimal("0")
    return Decimal(working)


def build_calendar(db: Session, employee: Employee, start: date, end: date):
    policy = effective_policy(db, employee)
    holidays = holidays_between(db, start, end)
    leaves = db.scalars(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == employee.id,
            LeaveRequest.status == LeaveStatus.APPROVED,
            LeaveRequest.start_date <= end,
            LeaveRequest.end_date >= start,
        )
    ).all()
    leave_by_day: Dict[date, LeaveRequest] = {}
    for lr in leaves:
        for d in _days(max(lr.start_date, start), min(lr.end_date, end)):
            leave_by_day[d] = lr

    days: List[CalendarDay] = []
    counts = {"working": 0, "week_off": 0, "holiday": 0, "leave": 0.0}
    for d in _days(start, end):
        wd = Weekday.from_index(d.weekday())
        # Precedence: week-off > holiday > leave > working (leave isn't charged on off days)
        if is_week_off(d, policy):
            days.append(CalendarDay(date=d, weekday=wd, status=DayStatus.WEEK_OFF))
            counts["week_off"] += 1
        elif d in holidays:
            days.append(CalendarDay(date=d, weekday=wd, status=DayStatus.HOLIDAY, detail=holidays[d].name))
            counts["holiday"] += 1
        elif d in leave_by_day:
            lr = leave_by_day[d]
            days.append(CalendarDay(
                date=d, weekday=wd, status=DayStatus.LEAVE, detail=lr.leave_type.code,
                leave_request_id=lr.id, half_day=lr.half_day,
            ))
            counts["leave"] += 0.5 if lr.half_day else 1
        else:
            days.append(CalendarDay(date=d, weekday=wd, status=DayStatus.WORKING))
            counts["working"] += 1
    return policy, CalendarSummary(**counts), days
