from datetime import date, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.leave import LeaveStatus
from app.models.user import User, UserRole
from app.repositories import calendar_repository, employee_repository, leave_repository
from app.schemas.calendar import EmployeeCalendar
from app.schemas.common import Page
from app.schemas.leave import (
    LeaveAllocationIn,
    LeaveApply,
    LeaveBalanceOut,
    LeaveDecision,
    LeaveRequestOut,
)

router = APIRouter(tags=["leaves"])
admin = require_roles(UserRole.ADMIN)
MAX_CALENDAR_DAYS = 366


# ---------- Per-employee ----------
@router.post(
    "/employees/{employee_id}/leaves",
    response_model=LeaveRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def apply_leave(
    employee_id: UUID,
    payload: LeaveApply,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Apply for leave on behalf of an employee. Days exclude week-offs and holidays."""
    return leave_repository.apply_leave(db, employee_id, payload, user)


@router.get("/employees/{employee_id}/leaves", response_model=Page[LeaveRequestOut])
def list_employee_leaves(
    employee_id: UUID,
    status_: Optional[LeaveStatus] = Query(None, alias="status"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    employee_repository.require_employee(db, employee_id)
    items, total = leave_repository.list_leaves(
        db, employee_id=employee_id, status=status_, date_from=date_from, date_to=date_to, skip=skip, limit=limit
    )
    return Page(items=items, total=total, skip=skip, limit=limit)


@router.get("/employees/{employee_id}/leave-balances", response_model=List[LeaveBalanceOut])
def get_leave_balances(
    employee_id: UUID,
    year: Optional[int] = Query(None, ge=2000, le=2100, description="Defaults to the current year"),
    db: Session = Depends(get_db),
):
    employee = employee_repository.require_employee(db, employee_id)
    return leave_repository.get_balances(db, employee, year or date.today().year)


@router.put(
    "/employees/{employee_id}/leave-balances",
    response_model=List[LeaveBalanceOut],
    dependencies=[Depends(admin)],
)
def set_leave_allocation(employee_id: UUID, payload: LeaveAllocationIn, db: Session = Depends(get_db)):
    """Override the annual quota of one leave type for this employee and year."""
    employee = employee_repository.require_employee(db, employee_id)
    leave_repository.set_allocation(db, employee, payload)
    return leave_repository.get_balances(db, employee, payload.year)


@router.get("/employees/{employee_id}/calendar", response_model=EmployeeCalendar)
def get_employee_calendar(
    employee_id: UUID,
    start: Optional[date] = Query(None, description="Defaults to the first day of the current month"),
    end: Optional[date] = Query(None, description="Defaults to the last day of start's month"),
    db: Session = Depends(get_db),
):
    """Day-by-day view: working day, week-off, holiday or approved leave."""
    employee = employee_repository.require_employee(db, employee_id)
    start = start or date.today().replace(day=1)
    if end is None:
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
    if end < start:
        raise HTTPException(status_code=422, detail="end must be on or after start")
    if (end - start).days + 1 > MAX_CALENDAR_DAYS:
        raise HTTPException(status_code=422, detail=f"Range may cover at most {MAX_CALENDAR_DAYS} days")

    policy, summary, days = calendar_repository.build_calendar(db, employee, start, end)
    return EmployeeCalendar(
        employee_id=employee.id, start=start, end=end, week_off_policy=policy, summary=summary, days=days
    )


# ---------- Across employees ----------
@router.get("/leaves", response_model=Page[LeaveRequestOut])
def list_leaves(
    employee_id: Optional[UUID] = None,
    status_: Optional[LeaveStatus] = Query(None, alias="status"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """All leave requests, e.g. ?status=pending for the approval queue."""
    items, total = leave_repository.list_leaves(
        db, employee_id=employee_id, status=status_, date_from=date_from, date_to=date_to, skip=skip, limit=limit
    )
    return Page(items=items, total=total, skip=skip, limit=limit)


@router.get("/leaves/{leave_id}", response_model=LeaveRequestOut)
def get_leave(leave_id: UUID, db: Session = Depends(get_db)):
    return leave_repository.get_leave(db, leave_id)


def _decide(leave_id: UUID, new_status: LeaveStatus, payload: Optional[LeaveDecision], user: User, db: Session):
    note = payload.note if payload else None
    return leave_repository.change_status(db, leave_id, new_status, user, note)


@router.post("/leaves/{leave_id}/approve", response_model=LeaveRequestOut)
def approve_leave(
    leave_id: UUID,
    payload: Optional[LeaveDecision] = None,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
):
    return _decide(leave_id, LeaveStatus.APPROVED, payload, user, db)


@router.post("/leaves/{leave_id}/reject", response_model=LeaveRequestOut)
def reject_leave(
    leave_id: UUID,
    payload: Optional[LeaveDecision] = None,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
):
    return _decide(leave_id, LeaveStatus.REJECTED, payload, user, db)


@router.post("/leaves/{leave_id}/cancel", response_model=LeaveRequestOut)
def cancel_leave(
    leave_id: UUID,
    payload: Optional[LeaveDecision] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a pending or approved leave; the days return to the balance."""
    return _decide(leave_id, LeaveStatus.CANCELLED, payload, user, db)
