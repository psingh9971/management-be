from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.attendance import AttendancePunch, AttendanceRecord, AttendanceStatus, PunchType
from app.models.employee import Employee
from app.models.leave import LeaveRequest, LeaveStatus
from app.models.user import User
from app.repositories import calendar_repository
from app.repositories.errors import ValidationError
from app.schemas.attendance import (
    AttendanceDay,
    AttendanceReport,
    AttendanceSummary,
    DaySource,
    DayStatus,
    ManualAttendanceIn,
    PunchBrief,
)


def _infer_punch_type(db: Session, employee_id: UUID, punch_time: datetime) -> PunchType:
    """When the device doesn't say IN/OUT, alternate based on the previous punch that day."""
    day_start = datetime.combine(punch_time.date(), time.min, tzinfo=punch_time.tzinfo)
    last = db.scalars(
        select(AttendancePunch)
        .where(
            AttendancePunch.employee_id == employee_id,
            AttendancePunch.punch_time >= day_start,
            AttendancePunch.punch_time < punch_time,
        )
        .order_by(AttendancePunch.punch_time.desc())
        .limit(1)
    ).first()
    if last is None or last.punch_type == PunchType.OUT:
        return PunchType.IN
    return PunchType.OUT


def record_punch(
    db: Session,
    employee: Employee,
    punch_time: datetime,
    punch_type: Optional[PunchType],
    device_id: str,
    raw_payload: Optional[Dict[str, Any]] = None,
    source: str = "webhook",
) -> Tuple[AttendancePunch, bool]:
    """Insert a punch idempotently. Returns (punch, created)."""
    if punch_type is None:
        punch_type = _infer_punch_type(db, employee.id, punch_time)

    stmt = (
        insert(AttendancePunch)
        .values(
            employee_id=employee.id,
            punch_time=punch_time,
            punch_type=punch_type,
            device_id=device_id,
            source=source,
            raw_payload=raw_payload,
        )
        .on_conflict_do_nothing(constraint="uq_punch_employee_time_device")
        .returning(AttendancePunch.id)
    )
    new_id = db.execute(stmt).scalar()
    db.commit()

    if new_id is not None:
        return db.get(AttendancePunch, new_id), True

    existing = db.scalars(
        select(AttendancePunch).where(
            AttendancePunch.employee_id == employee.id,
            AttendancePunch.punch_time == punch_time,
            AttendancePunch.device_id == device_id,
        )
    ).one()
    return existing, False


def list_punches(
    db: Session,
    employee_id: UUID,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[AttendancePunch]:
    stmt = select(AttendancePunch).where(AttendancePunch.employee_id == employee_id)
    if date_from:
        stmt = stmt.where(AttendancePunch.punch_time >= date_from)
    if date_to:
        stmt = stmt.where(AttendancePunch.punch_time <= date_to)
    stmt = stmt.order_by(AttendancePunch.punch_time.desc()).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


# ---------- Daily attendance records ----------
def mark_attendance(
    db: Session, employee: Employee, data: ManualAttendanceIn, user: User
) -> Tuple[AttendanceRecord, bool]:
    """Create or overwrite the employee's attendance for data.date. Returns (record, created)."""
    if not employee.is_active:
        raise ValidationError("Employee is inactive")
    if data.date > date.today():
        raise ValidationError("Attendance cannot be marked for a future date")

    # Lock any existing row so two concurrent markings for the same day don't race
    record = db.scalars(
        select(AttendanceRecord)
        .where(AttendanceRecord.employee_id == employee.id, AttendanceRecord.date == data.date)
        .with_for_update()
    ).first()
    created = record is None
    if created:
        record = AttendanceRecord(employee_id=employee.id, date=data.date)
        db.add(record)

    record.status = data.status
    record.check_in = data.check_in
    record.check_out = data.check_out
    record.note = data.note
    record.source = "manual"
    record.marked_by_id = user.id
    db.commit()
    db.refresh(record)
    return record, created


def list_attendance_records(
    db: Session,
    employee_id: UUID,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[AttendanceStatus] = None,
    skip: int = 0,
    limit: int = 100,
) -> Tuple[List[AttendanceRecord], int]:
    stmt = select(AttendanceRecord).where(AttendanceRecord.employee_id == employee_id)
    if date_from:
        stmt = stmt.where(AttendanceRecord.date >= date_from)
    if date_to:
        stmt = stmt.where(AttendanceRecord.date <= date_to)
    if status:
        stmt = stmt.where(AttendanceRecord.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(AttendanceRecord.date.desc()).offset(skip).limit(limit)).all()
    return list(items), total


# ---------- Combined day-by-day view ----------
# Precedence for each day: manual record > device punches > approved leave > holiday
# > week-off > no_record. Used by both the per-employee view and the all-employee summary,
# so their numbers always agree.

Nested = Dict[UUID, Dict[date, Any]]


def _hours(check_in: Optional[datetime], check_out: Optional[datetime]) -> Optional[float]:
    if check_in is None or check_out is None:
        return None
    return round((check_out - check_in).total_seconds() / 3600, 2)


def _load_sources(db: Session, employee_ids: List[UUID], start: date, end: date):
    """Fetch manual records, punches and approved leaves for many employees with one query each."""
    tz = settings.tz
    records: Nested = defaultdict(dict)
    for r in db.scalars(
        select(AttendanceRecord).where(
            AttendanceRecord.employee_id.in_(employee_ids),
            AttendanceRecord.date >= start,
            AttendanceRecord.date <= end,
        )
    ).all():
        records[r.employee_id][r.date] = r

    # Punches are stored in UTC; bucket them by the local (business-timezone) date
    punches: Nested = defaultdict(lambda: defaultdict(list))
    for p in db.scalars(
        select(AttendancePunch)
        .where(
            AttendancePunch.employee_id.in_(employee_ids),
            AttendancePunch.punch_time >= datetime.combine(start, time.min, tzinfo=tz),
            AttendancePunch.punch_time < datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz),
        )
        .order_by(AttendancePunch.punch_time)
    ).all():
        punches[p.employee_id][p.punch_time.astimezone(tz).date()].append(p)

    leaves: Nested = defaultdict(dict)
    for lr in db.scalars(
        select(LeaveRequest).where(
            LeaveRequest.employee_id.in_(employee_ids),
            LeaveRequest.status == LeaveStatus.APPROVED,
            LeaveRequest.start_date <= end,
            LeaveRequest.end_date >= start,
        )
    ).all():
        d = max(lr.start_date, start)
        while d <= min(lr.end_date, end):
            leaves[lr.employee_id][d] = lr
            d += timedelta(days=1)

    return records, punches, leaves


def _resolve_days(
    start: date,
    end: date,
    records: Dict[date, AttendanceRecord],
    punches_by_day: Dict[date, List[AttendancePunch]],
    leave_by_day: Dict[date, LeaveRequest],
    holidays: Dict[date, Any],
    policy: Any,
) -> Tuple[List[AttendanceDay], AttendanceSummary]:
    tz = settings.tz

    def local(t: Optional[datetime]) -> Optional[datetime]:
        return t.astimezone(tz) if t else None

    days: List[AttendanceDay] = []
    summary = AttendanceSummary()
    d = start
    while d <= end:
        day_punches = punches_by_day.get(d, [])
        entry = AttendanceDay(
            date=d,
            weekday=d.strftime("%A").lower(),
            status=DayStatus.NO_RECORD,
            source=DaySource.NONE,
            punches=[
                PunchBrief(id=p.id, punch_time=local(p.punch_time), punch_type=p.punch_type, device_id=p.device_id)
                for p in day_punches
            ],
        )
        record = records.get(d)
        if record is not None:
            entry.status = DayStatus(record.status.value)
            entry.source = DaySource.MANUAL
            entry.check_in, entry.check_out = local(record.check_in), local(record.check_out)
            entry.note, entry.marked_by_id, entry.record_id = record.note, record.marked_by_id, record.id
        elif day_punches:
            entry.status = DayStatus.PRESENT
            entry.source = DaySource.DEVICE
            entry.check_in = local(day_punches[0].punch_time)
            entry.check_out = local(day_punches[-1].punch_time) if len(day_punches) > 1 else None
        elif d in leave_by_day:
            lr = leave_by_day[d]
            entry.status, entry.source = DayStatus.LEAVE, DaySource.LEAVE
            entry.detail = lr.leave_type.code + (" (half day)" if lr.half_day else "")
            entry.leave_request_id = lr.id
        elif d in holidays:
            entry.status, entry.source, entry.detail = DayStatus.HOLIDAY, DaySource.HOLIDAY, holidays[d].name
        elif calendar_repository.is_week_off(d, policy):
            entry.status, entry.source = DayStatus.WEEK_OFF, DaySource.WEEK_OFF

        entry.worked_hours = _hours(entry.check_in, entry.check_out)
        setattr(summary, entry.status.value, getattr(summary, entry.status.value) + 1)
        summary.total_worked_hours = round(summary.total_worked_hours + (entry.worked_hours or 0), 2)
        days.append(entry)
        d += timedelta(days=1)
    return days, summary


def build_attendance_report(db: Session, employee: Employee, start: date, end: date) -> AttendanceReport:
    """One entry per day in [start, end] for a single employee."""
    records, punches, leaves = _load_sources(db, [employee.id], start, end)
    days, summary = _resolve_days(
        start,
        end,
        records[employee.id],
        punches[employee.id],
        leaves[employee.id],
        calendar_repository.holidays_between(db, start, end),
        calendar_repository.effective_policy(db, employee),
    )
    return AttendanceReport(
        employee_id=employee.id, start=start, end=end, timezone=settings.APP_TIMEZONE, summary=summary, days=days
    )


def resolve_days_for_employees(
    db: Session, employees: List[Employee], start: date, end: date
) -> Dict[UUID, Tuple[List[AttendanceDay], AttendanceSummary, Dict[date, LeaveRequest]]]:
    """Resolved day-by-day attendance for many employees with a fixed number of queries.
    Also returns each employee's approved leaves by day (used by payroll to tell paid from unpaid)."""
    if not employees:
        return {}
    records, punches, leaves = _load_sources(db, [e.id for e in employees], start, end)
    holidays = calendar_repository.holidays_between(db, start, end)
    policies = {p.id: p for p in calendar_repository.list_policies(db)}
    default_policy = next((p for p in policies.values() if p.is_default), None)

    out = {}
    for e in employees:
        policy = policies.get(e.week_off_policy_id) if e.week_off_policy_id else default_policy
        days, summary = _resolve_days(start, end, records[e.id], punches[e.id], leaves[e.id], holidays, policy)
        out[e.id] = (days, summary, leaves[e.id])
    return out


def build_attendance_summaries(
    db: Session, employees: List[Employee], start: date, end: date
) -> List[Tuple[Employee, AttendanceSummary]]:
    """Per-employee totals for [start, end] using a fixed number of queries regardless of headcount."""
    resolved = resolve_days_for_employees(db, employees, start, end)
    return [(e, resolved[e.id][1]) for e in employees]


def build_day_for_employees(
    db: Session, employees: List[Employee], day: date
) -> List[Tuple[Employee, AttendanceDay]]:
    """Each employee's resolved attendance (manual record + punches + calendar) for one day."""
    resolved = resolve_days_for_employees(db, employees, day, day)
    return [(e, resolved[e.id][0][0]) for e in employees]
