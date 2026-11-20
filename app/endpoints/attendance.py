import calendar
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import require_roles
from app.db.session import get_db
from app.models.attendance import AttendanceStatus
from app.models.user import User, UserRole
from app.repositories import attendance_repository, employee_repository
from app.schemas.attendance import (
    AttendanceRecordOut,
    AttendanceReport,
    AttendanceSummary,
    DailyAttendance,
    DayStatus,
    EmployeeAttendanceSummary,
    EmployeeDayAttendance,
    ManualAttendanceIn,
    MonthlyAttendanceSummary,
)
from app.schemas.common import Page

router = APIRouter(tags=["attendance"])
MAX_RANGE_DAYS = 366


@router.post(
    "/employees/{employee_id}/attendance/manual",
    response_model=AttendanceRecordOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "An existing record for that date was overwritten"}},
)
def mark_attendance_manually(
    employee_id: UUID,
    payload: ManualAttendanceIn,
    response: Response,
    user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Mark an employee as present / absent / half_day / week_off / leave for a date.
    Marking the same date again overwrites the earlier entry (returns 200)."""
    employee = employee_repository.require_employee(db, employee_id)
    record, created = attendance_repository.mark_attendance(db, employee, payload, user)
    if not created:
        response.status_code = status.HTTP_200_OK
    return record


def _resolve_range(
    month: Optional[str], on: Optional[date], date_from: Optional[date], date_to: Optional[date]
):
    if sum(x is not None for x in (month, on, date_from or date_to)) > 1:
        raise HTTPException(422, "Use only one of: month, date, or date_from/date_to")
    if on is not None:
        return on, on
    if date_from or date_to:
        if not (date_from and date_to):
            raise HTTPException(422, "date_from and date_to must be given together")
        if date_to < date_from:
            raise HTTPException(422, "date_to must be on or after date_from")
        if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
            raise HTTPException(422, f"Range may cover at most {MAX_RANGE_DAYS} days")
        return date_from, date_to
    if month is None:
        today = date.today()
        year, mon = today.year, today.month
    else:
        try:
            year, mon = (int(x) for x in month.split("-"))
            date(year, mon, 1)
        except ValueError:
            raise HTTPException(422, "month must be in YYYY-MM format, e.g. 2026-11")
    return date(year, mon, 1), date(year, mon, calendar.monthrange(year, mon)[1])


@router.get("/attendance/daily", response_model=DailyAttendance)
def daily_attendance(
    on: Optional[date] = Query(None, alias="date", description="YYYY-MM-DD (default: today)"),
    status_: Optional[DayStatus] = Query(None, alias="status", description="e.g. absent, no_record"),
    department: Optional[str] = None,
    is_active: Optional[bool] = Query(None, description="true/false to filter; default: all employees"),
    search: Optional[str] = Query(None, description="Matches name, employee code or email"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Every employee's attendance for one day, combining manual records and device punches
    (manual wins; raw punches are always listed). Days with neither fall back to approved
    leave / holiday / week-off, else no_record - so nobody is left out."""
    day = on or datetime.now(settings.tz).date()
    employees = employee_repository.all_employees(db, search=search, department=department, is_active=is_active)
    rows = attendance_repository.build_day_for_employees(db, employees, day)

    summary = AttendanceSummary()
    for _, a in rows:
        setattr(summary, a.status.value, getattr(summary, a.status.value) + 1)
        summary.total_worked_hours = round(summary.total_worked_hours + (a.worked_hours or 0), 2)

    if status_ is not None:
        rows = [(e, a) for e, a in rows if a.status == status_]
    page = rows[skip: skip + limit]
    return DailyAttendance(
        date=day,
        weekday=day.strftime("%A").lower(),
        timezone=settings.APP_TIMEZONE,
        summary=summary,
        total=len(rows),
        skip=skip,
        limit=limit,
        items=[
            EmployeeDayAttendance(
                employee_id=e.id,
                employee_code=e.employee_code,
                name=" ".join(x for x in (e.first_name, e.last_name) if x),
                department=e.department,
                designation=e.designation,
                is_active=e.is_active,
                attendance=a,
            )
            for e, a in page
        ],
    )


@router.get("/attendance/summary", response_model=MonthlyAttendanceSummary)
def monthly_attendance_summary(
    month: Optional[str] = Query(None, description="YYYY-MM, e.g. 2026-11 (default: current month)"),
    department: Optional[str] = None,
    is_active: Optional[bool] = Query(None, description="true/false to filter; default: all employees"),
    search: Optional[str] = Query(None, description="Matches name, employee code or email"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Attendance totals per employee for a month: present / absent / half_day / leave /
    holiday / week_off / no_record days and worked hours. Uses the same rules as
    GET /employees/{id}/attendance, so the numbers match the day-by-day view."""
    start, end = _resolve_range(month, None, None, None)
    employees, total = employee_repository.list_employees(
        db, skip=skip, limit=limit, search=search, department=department, is_active=is_active
    )
    rows = attendance_repository.build_attendance_summaries(db, employees, start, end)
    return MonthlyAttendanceSummary(
        month=start.strftime("%Y-%m"),
        start=start,
        end=end,
        days_in_month=(end - start).days + 1,
        timezone=settings.APP_TIMEZONE,
        total=total,
        skip=skip,
        limit=limit,
        items=[
            EmployeeAttendanceSummary(
                employee_id=e.id,
                employee_code=e.employee_code,
                name=" ".join(x for x in (e.first_name, e.last_name) if x),
                department=e.department,
                designation=e.designation,
                is_active=e.is_active,
                summary=summary,
            )
            for e, summary in rows
        ],
    )


@router.get("/employees/{employee_id}/attendance", response_model=AttendanceReport)
def get_attendance(
    employee_id: UUID,
    month: Optional[str] = Query(None, description="YYYY-MM, e.g. 2026-11 (default: current month)"),
    on: Optional[date] = Query(None, alias="date", description="A single day, YYYY-MM-DD"),
    date_from: Optional[date] = Query(None, description="Range start (with date_to), YYYY-MM-DD"),
    date_to: Optional[date] = Query(None, description="Range end (with date_from), YYYY-MM-DD"),
    status_: Optional[DayStatus] = Query(None, alias="status", description="Only return days with this status"),
    db: Session = Depends(get_db),
):
    """Day-by-day attendance combining manual records and device punches (plus approved
    leave, holidays and week-offs for days with neither). Manual records take precedence;
    each day still lists its raw device punches so overrides are visible."""
    start, end = _resolve_range(month, on, date_from, date_to)
    employee = employee_repository.require_employee(db, employee_id)
    report = attendance_repository.build_attendance_report(db, employee, start, end)
    if status_ is not None:
        report.days = [d for d in report.days if d.status == status_]
    return report


@router.get("/employees/{employee_id}/attendance/records", response_model=Page[AttendanceRecordOut])
def list_manual_records(
    employee_id: UUID,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status_: Optional[AttendanceStatus] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Raw manual attendance records only (audit view)."""
    employee_repository.require_employee(db, employee_id)
    items, total = attendance_repository.list_attendance_records(
        db, employee_id, date_from=date_from, date_to=date_to, status=status_, skip=skip, limit=limit
    )
    return Page(items=items, total=total, skip=skip, limit=limit)
