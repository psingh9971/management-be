from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.leave import LeaveBalance, LeaveRequest, LeaveStatus, LeaveType
from app.models.user import User
from app.repositories import calendar_repository
from app.repositories.errors import ConflictError, NotFoundError, ValidationError
from app.schemas.leave import (
    LeaveAllocationIn,
    LeaveApply,
    LeaveBalanceOut,
    LeaveTypeCreate,
    LeaveTypeUpdate,
)

ACTIVE_STATUSES = (LeaveStatus.PENDING, LeaveStatus.APPROVED)

# Allowed status transitions
TRANSITIONS = {
    LeaveStatus.PENDING: {LeaveStatus.APPROVED, LeaveStatus.REJECTED, LeaveStatus.CANCELLED},
    LeaveStatus.APPROVED: {LeaveStatus.CANCELLED},
    LeaveStatus.REJECTED: set(),
    LeaveStatus.CANCELLED: set(),
}


# ---------- Leave types ----------
def list_leave_types(db: Session, include_inactive: bool = False) -> List[LeaveType]:
    stmt = select(LeaveType).order_by(LeaveType.name)
    if not include_inactive:
        stmt = stmt.where(LeaveType.is_active.is_(True))
    return list(db.scalars(stmt).all())


def get_leave_type(db: Session, leave_type_id: UUID) -> LeaveType:
    lt = db.get(LeaveType, leave_type_id)
    if lt is None:
        raise NotFoundError("Leave type not found")
    return lt


def create_leave_type(db: Session, data: LeaveTypeCreate) -> LeaveType:
    code = data.code.upper()
    if db.scalar(select(LeaveType.id).where((LeaveType.code == code) | (LeaveType.name == data.name))):
        raise ConflictError("A leave type with this name or code already exists")
    lt = LeaveType(**{**data.model_dump(), "code": code})
    db.add(lt)
    db.commit()
    db.refresh(lt)
    return lt


def update_leave_type(db: Session, leave_type_id: UUID, data: LeaveTypeUpdate) -> LeaveType:
    lt = get_leave_type(db, leave_type_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and db.scalar(
        select(LeaveType.id).where(LeaveType.name == changes["name"], LeaveType.id != lt.id)
    ):
        raise ConflictError(f"A leave type named '{changes['name']}' already exists")
    for field, value in changes.items():
        setattr(lt, field, value)
    db.commit()
    db.refresh(lt)
    return lt


# ---------- Balances ----------
def set_allocation(db: Session, employee: Employee, data: LeaveAllocationIn) -> None:
    get_leave_type(db, data.leave_type_id)
    stmt = insert(LeaveBalance).values(
        tenant_id=employee.tenant_id,  # Core insert: not stamped automatically
        employee_id=employee.id, leave_type_id=data.leave_type_id, year=data.year, allocated=data.allocated
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_leave_balance_employee_type_year",
        set_={"allocated": stmt.excluded.allocated, "updated_at": func.now()},
    )
    db.execute(stmt)
    db.commit()


def _taken(db: Session, employee_id: UUID, year: int) -> Dict[Tuple[UUID, LeaveStatus], Decimal]:
    rows = db.execute(
        select(LeaveRequest.leave_type_id, LeaveRequest.status, func.sum(LeaveRequest.days))
        .where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status.in_(ACTIVE_STATUSES),
            LeaveRequest.start_date >= date(year, 1, 1),
            LeaveRequest.start_date <= date(year, 12, 31),
        )
        .group_by(LeaveRequest.leave_type_id, LeaveRequest.status)
    ).all()
    return {(lt_id, st): total for lt_id, st, total in rows}


def get_balances(
    db: Session, employee: Employee, year: int, leave_type_id: Optional[UUID] = None
) -> List[LeaveBalanceOut]:
    types = [get_leave_type(db, leave_type_id)] if leave_type_id else list_leave_types(db)
    custom = {
        b.leave_type_id: b.allocated
        for b in db.scalars(
            select(LeaveBalance).where(LeaveBalance.employee_id == employee.id, LeaveBalance.year == year)
        ).all()
    }
    taken = _taken(db, employee.id, year)
    out = []
    for lt in types:
        allocated = custom.get(lt.id, lt.annual_quota)
        used = taken.get((lt.id, LeaveStatus.APPROVED), Decimal(0))
        pending = taken.get((lt.id, LeaveStatus.PENDING), Decimal(0))
        out.append(LeaveBalanceOut(
            leave_type_id=lt.id,
            leave_type_code=lt.code,
            leave_type_name=lt.name,
            is_paid=lt.is_paid,
            year=year,
            allocated=float(allocated),
            is_custom_allocation=lt.id in custom,
            used=float(used),
            pending=float(pending),
            # Unpaid types (e.g. LOP) aren't limited by a balance
            available=float(allocated - used - pending) if lt.is_paid else None,
        ))
    return out


# ---------- Leave requests ----------
def apply_leave(db: Session, employee_id: UUID, data: LeaveApply, user: User) -> LeaveRequest:
    # Row lock serialises concurrent applications for the same employee,
    # so two requests can't both pass the balance check.
    employee = db.scalars(select(Employee).where(Employee.id == employee_id).with_for_update()).first()
    if employee is None:
        raise NotFoundError("Employee not found")
    if not employee.is_active:
        raise ValidationError("Employee is inactive")

    lt = get_leave_type(db, data.leave_type_id)
    if not lt.is_active:
        raise ValidationError(f"Leave type '{lt.code}' is inactive")

    overlap = db.scalars(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == employee.id,
            LeaveRequest.status.in_(ACTIVE_STATUSES),
            LeaveRequest.start_date <= data.end_date,
            LeaveRequest.end_date >= data.start_date,
        )
    ).first()
    if overlap:
        raise ConflictError(
            f"Overlaps an existing {overlap.status.value} leave "
            f"({overlap.start_date} to {overlap.end_date}, id {overlap.id})"
        )

    days = calendar_repository.count_leave_days(db, employee, data.start_date, data.end_date, data.half_day)
    if days == 0:
        raise ValidationError("The selected dates fall entirely on week-offs or holidays")

    if lt.is_paid:
        balance = get_balances(db, employee, data.start_date.year, lt.id)[0]
        if Decimal(str(balance.available)) < days:
            raise ValidationError(
                f"Insufficient {lt.code} balance: requested {days}, available {balance.available}"
            )

    leave = LeaveRequest(
        employee_id=employee.id,
        leave_type_id=lt.id,
        start_date=data.start_date,
        end_date=data.end_date,
        half_day=data.half_day,
        days=days,
        reason=data.reason,
        status=LeaveStatus.PENDING,
        requested_by_id=user.id,
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return leave


def get_leave(db: Session, leave_id: UUID) -> LeaveRequest:
    leave = db.get(LeaveRequest, leave_id)
    if leave is None:
        raise NotFoundError("Leave request not found")
    return leave


def list_leaves(
    db: Session,
    employee_id: Optional[UUID] = None,
    status: Optional[LeaveStatus] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[List[LeaveRequest], int]:
    stmt = select(LeaveRequest)
    if employee_id:
        stmt = stmt.where(LeaveRequest.employee_id == employee_id)
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    if date_from:
        stmt = stmt.where(LeaveRequest.end_date >= date_from)
    if date_to:
        stmt = stmt.where(LeaveRequest.start_date <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(LeaveRequest.start_date.desc()).offset(skip).limit(limit)).all()
    return list(items), total


def change_status(
    db: Session, leave_id: UUID, new_status: LeaveStatus, user: User, note: Optional[str]
) -> LeaveRequest:
    leave = db.scalars(select(LeaveRequest).where(LeaveRequest.id == leave_id).with_for_update(of=LeaveRequest)).first()
    if leave is None:
        raise NotFoundError("Leave request not found")
    if new_status not in TRANSITIONS[leave.status]:
        raise ValidationError(f"Leave is {leave.status.value} and cannot be changed to {new_status.value}")
    leave.status = new_status
    leave.decided_by_id = user.id
    leave.decided_at = datetime.now(timezone.utc)
    leave.decision_note = note
    db.commit()
    db.refresh(leave)
    return leave
