"""Salary structures, employee assignments and attendance-based salary slips.

How a slip is calculated
------------------------
1. The structure's components are evaluated for a full month against the assignment's
   monthly gross (fixed amounts, % of gross, % of an earlier component, balance).
2. Each day of the month is resolved by the attendance module (manual record > device
   punches > approved leave > holiday > week-off) and turned into loss-of-pay (LOP) days:
     present, holiday, week-off, paid leave ......... 0
     half day (without paid leave for the other half)  0.5
     unpaid leave (e.g. LOP leave type) .............. 1 (0.5 + 0.5 unaccounted half for half-day)
     absent, or a working day with no attendance ..... 1
     days before date_of_joining ..................... 1 (working days only, for the working-days basis)
3. payable_days = base_days - lop_days, where base_days is the month's working days
   (calendar days minus week-offs and holidays) or its calendar days, per the structure's
   proration_basis. Prorated components are scaled by payable_days / base_days;
   non-prorated ones (e.g. Professional Tax) are taken in full.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID
import calendar

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.calendar import Holiday, WeekOffPolicy
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.payroll import (
    CalculationType,
    ComponentType,
    EmployeeSalaryAssignment,
    ProrationBasis,
    SalarySlip,
    SalarySlipLine,
    SalarySlipStatus,
    SalaryStructure,
    SalaryStructureComponent,
)
from app.models.user import User
from app.repositories import attendance_repository, calendar_repository
from app.repositories.errors import ConflictError, DomainError, NotFoundError, ValidationError
from app.schemas.attendance import AttendanceDay, DayStatus
from app.schemas.payroll import (
    BulkSalarySlipGenerate,
    ComponentAmount,
    SalaryAssignmentIn,
    SalaryBreakdown,
    SalarySlipGenerate,
    SalaryStructureIn,
    SkippedEmployee,
)

CENT = Decimal("0.01")
HUNDRED = Decimal(100)


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# =====================================================================
# Salary structures
# =====================================================================
def list_structures(db: Session, include_inactive: bool = False) -> List[SalaryStructure]:
    stmt = select(SalaryStructure).order_by(SalaryStructure.name)
    if not include_inactive:
        stmt = stmt.where(SalaryStructure.is_active.is_(True))
    return list(db.scalars(stmt).all())


def get_structure(db: Session, structure_id: UUID) -> SalaryStructure:
    structure = db.get(SalaryStructure, structure_id)
    if structure is None:
        raise NotFoundError("Salary structure not found")
    return structure


def _apply_structure_fields(db: Session, structure: SalaryStructure, data: SalaryStructureIn) -> None:
    clash = db.scalar(
        select(SalaryStructure.id).where(SalaryStructure.name == data.name, SalaryStructure.id != structure.id)
    )
    if clash:
        raise ConflictError(f"A salary structure named '{data.name}' already exists")
    structure.name = data.name
    structure.description = data.description
    structure.proration_basis = data.proration_basis
    structure.is_active = data.is_active
    if structure.components:
        # The unit of work inserts before it deletes, which would collide with the
        # (structure_id, code) unique constraint - so remove the old components first.
        structure.components = []
        db.flush()
    structure.components = [
        SalaryStructureComponent(
            code=c.code,
            name=c.name,
            component_type=c.component_type,
            calculation_type=c.calculation_type,
            value=c.value,
            base_component_code=c.base_component_code,
            is_prorated=c.is_prorated,
            sequence=i,
        )
        for i, c in enumerate(data.components, start=1)
    ]


def create_structure(db: Session, data: SalaryStructureIn) -> SalaryStructure:
    structure = SalaryStructure()
    _apply_structure_fields(db, structure, data)
    db.add(structure)
    db.commit()
    db.refresh(structure)
    return structure


def replace_structure(db: Session, structure_id: UUID, data: SalaryStructureIn) -> SalaryStructure:
    """Existing salary slips are snapshots and are not affected; future slips use the new definition."""
    structure = get_structure(db, structure_id)
    _apply_structure_fields(db, structure, data)
    db.commit()
    db.refresh(structure)
    return structure


def delete_structure(db: Session, structure_id: UUID) -> None:
    structure = get_structure(db, structure_id)
    in_use = db.scalar(
        select(func.count()).select_from(EmployeeSalaryAssignment)
        .where(EmployeeSalaryAssignment.structure_id == structure.id)
    )
    if in_use:
        raise ConflictError(
            f"Structure is used by {in_use} salary assignment(s); set is_active=false instead of deleting"
        )
    db.delete(structure)
    db.commit()


# =====================================================================
# Component calculation
# =====================================================================
def compute_full_amounts(
    components: Sequence[Any], monthly_gross: Decimal
) -> List[Tuple[Any, Decimal]]:
    """Full-month amount of each component, in sequence order. Works with ORM components
    or SalaryComponentIn objects (same attribute names)."""
    amounts: Dict[str, Optional[Decimal]] = {}
    balance_code: Optional[str] = None
    for c in components:
        value = Decimal(c.value)
        if c.calculation_type == CalculationType.FIXED:
            amount = value
        elif c.calculation_type == CalculationType.PERCENT_OF_GROSS:
            amount = monthly_gross * value / HUNDRED
        elif c.calculation_type == CalculationType.PERCENT_OF_COMPONENT:
            base = amounts.get(c.base_component_code)
            if base is None:
                raise ValidationError(f"'{c.code}': base component '{c.base_component_code}' is not available")
            amount = base * value / HUNDRED
        else:  # BALANCE - filled in below once all other earnings are known
            balance_code = c.code
            amount = None
        amounts[c.code] = _money(amount) if amount is not None else None

    if balance_code is not None:
        other_earnings = sum(
            (amounts[c.code] for c in components
             if c.component_type == ComponentType.EARNING and c.code != balance_code),
            Decimal(0),
        )
        balance = monthly_gross - other_earnings
        if balance < 0:
            raise ValidationError(
                f"Earnings other than '{balance_code}' ({other_earnings}) exceed the monthly gross ({monthly_gross})"
            )
        amounts[balance_code] = _money(balance)

    return [(c, amounts[c.code]) for c in components]


def build_breakdown(components: Sequence[Any], monthly_gross: Decimal) -> SalaryBreakdown:
    rows = compute_full_amounts(components, monthly_gross)
    earnings = sum((a for c, a in rows if c.component_type == ComponentType.EARNING), Decimal(0))
    deductions = sum((a for c, a in rows if c.component_type == ComponentType.DEDUCTION), Decimal(0))
    return SalaryBreakdown(
        monthly_gross=_money(monthly_gross),
        components=[
            ComponentAmount(
                code=c.code, name=c.name, component_type=c.component_type, is_prorated=c.is_prorated, amount=a
            )
            for c, a in rows
        ],
        gross_earnings=earnings,
        total_deductions=deductions,
        net_pay=earnings - deductions,
    )


# =====================================================================
# Assignments
# =====================================================================
def list_assignments(db: Session, employee_id: UUID) -> List[EmployeeSalaryAssignment]:
    return list(db.scalars(
        select(EmployeeSalaryAssignment)
        .where(EmployeeSalaryAssignment.employee_id == employee_id)
        .order_by(EmployeeSalaryAssignment.effective_from.desc())
    ).all())


def assignment_on(db: Session, employee_id: UUID, day: date) -> Optional[EmployeeSalaryAssignment]:
    return db.scalars(
        select(EmployeeSalaryAssignment).where(
            EmployeeSalaryAssignment.employee_id == employee_id,
            EmployeeSalaryAssignment.effective_from <= day,
            or_(EmployeeSalaryAssignment.effective_to.is_(None), EmployeeSalaryAssignment.effective_to >= day),
        )
    ).first()


def assign_structure(
    db: Session, employee_id: UUID, data: SalaryAssignmentIn, user: User
) -> EmployeeSalaryAssignment:
    # Lock the employee so concurrent assignments can't both close the same open assignment
    employee = db.scalars(select(Employee).where(Employee.id == employee_id).with_for_update()).first()
    if employee is None:
        raise NotFoundError("Employee not found")

    structure = get_structure(db, data.structure_id)
    if not structure.is_active:
        raise ValidationError(f"Salary structure '{structure.name}' is inactive")

    gross = data.monthly_gross if data.monthly_gross is not None else employee.salary
    if gross is None or gross <= 0:
        raise ValidationError("monthly_gross is required because the employee has no salary set")
    compute_full_amounts(structure.components, gross)  # fail early if the structure doesn't fit this gross

    later = db.scalars(
        select(EmployeeSalaryAssignment).where(
            EmployeeSalaryAssignment.employee_id == employee.id,
            EmployeeSalaryAssignment.effective_from >= data.effective_from,
        )
    ).first()
    if later:
        raise ConflictError(
            f"An assignment already starts on {later.effective_from} (id {later.id}); "
            "effective_from must be after the latest assignment"
        )

    previous = db.scalars(
        select(EmployeeSalaryAssignment).where(
            EmployeeSalaryAssignment.employee_id == employee.id,
            EmployeeSalaryAssignment.effective_to.is_(None),
        )
    ).first()
    if previous:
        previous.effective_to = data.effective_from - timedelta(days=1)

    assignment = EmployeeSalaryAssignment(
        employee_id=employee.id,
        structure_id=structure.id,
        monthly_gross=gross,
        effective_from=data.effective_from,
        note=data.note,
        assigned_by_id=user.id,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def delete_assignment(db: Session, employee_id: UUID, assignment_id: UUID) -> None:
    """Only the latest assignment can be deleted; the previous one is reopened."""
    assignment = db.get(EmployeeSalaryAssignment, assignment_id)
    if assignment is None or assignment.employee_id != employee_id:
        raise NotFoundError("Salary assignment not found")
    if assignment.effective_to is not None:
        raise ConflictError("Only the latest (open) assignment can be deleted")
    locked = db.scalar(
        select(func.count()).select_from(SalarySlip).where(
            SalarySlip.assignment_id == assignment.id, SalarySlip.status != SalarySlipStatus.DRAFT
        )
    )
    if locked:
        raise ConflictError("Finalized or paid salary slips were generated from this assignment")
    previous = db.scalars(
        select(EmployeeSalaryAssignment).where(
            EmployeeSalaryAssignment.employee_id == employee_id,
            EmployeeSalaryAssignment.effective_to == assignment.effective_from - timedelta(days=1),
        )
    ).first()
    if previous:
        previous.effective_to = None
    db.delete(assignment)
    db.commit()


# =====================================================================
# Salary slips
# =====================================================================
@dataclass
class _Calendar:
    holidays: Dict[date, Holiday]
    policies: Dict[UUID, WeekOffPolicy]
    default_policy: Optional[WeekOffPolicy]

    def policy_for(self, employee: Employee) -> Optional[WeekOffPolicy]:
        if employee.week_off_policy_id:
            return self.policies.get(employee.week_off_policy_id)
        return self.default_policy


def _month_bounds(year: int, month: int) -> Tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _check_period(start: date, end: date, allow_incomplete: bool) -> None:
    today = datetime.now(settings.tz).date()
    if start > today:
        raise ValidationError("Cannot generate salary slips for a future month")
    if end >= today and not allow_incomplete:
        raise ValidationError(
            f"{start:%B %Y} hasn't ended yet; pass allow_incomplete_month=true to generate it anyway "
            "(days without attendance count as loss of pay)"
        )


def _attendance_counts(
    employee: Employee,
    days: List[AttendanceDay],
    leaves: Dict[date, LeaveRequest],
    cal: _Calendar,
    basis: ProrationBasis,
) -> Dict[str, Any]:
    policy = cal.policy_for(employee)
    c = dict(
        total_days=len(days), working_days=0, week_off_days=0, holiday_days=0, present_days=0, half_days=0,
        paid_leave_days=Decimal(0), unpaid_leave_days=Decimal(0), absent_days=0, unmarked_days=0,
        pre_joining_days=0, lop_days=Decimal(0),
    )
    half = Decimal("0.5")
    joined = employee.date_of_joining

    for day in days:
        d = day.date
        # Calendar classification (independent of attendance, e.g. a holiday someone worked on)
        if calendar_repository.is_week_off(d, policy):
            c["week_off_days"] += 1
            is_working = False
        elif d in cal.holidays:
            c["holiday_days"] += 1
            is_working = False
        else:
            c["working_days"] += 1
            is_working = True

        if joined and d < joined:
            c["pre_joining_days"] += 1
            if is_working or basis == ProrationBasis.CALENDAR_DAYS:
                c["lop_days"] += 1
            continue

        lr = leaves.get(d)
        if day.status == DayStatus.PRESENT:
            c["present_days"] += 1
        elif day.status == DayStatus.HALF_DAY:
            c["half_days"] += 1
            # The other half is covered only by an approved paid leave on that day
            if lr is not None and lr.leave_type.is_paid:
                c["paid_leave_days"] += half
            else:
                if lr is not None:
                    c["unpaid_leave_days"] += half
                c["lop_days"] += half
        elif day.status == DayStatus.LEAVE:
            if lr is None:
                # Marked as leave manually without a leave request: treated as paid leave
                c["paid_leave_days"] += 1
            else:
                portion = half if lr.half_day else Decimal(1)
                if lr.leave_type.is_paid:
                    c["paid_leave_days"] += portion
                else:
                    c["unpaid_leave_days"] += portion
                    c["lop_days"] += portion
                if lr.half_day:
                    c["lop_days"] += half  # no attendance for the other half
        elif day.status == DayStatus.ABSENT:
            c["absent_days"] += 1
            c["lop_days"] += 1
        elif day.status == DayStatus.NO_RECORD:
            c["unmarked_days"] += 1
            c["lop_days"] += 1
        # HOLIDAY / WEEK_OFF: paid, no LOP

    base = c["working_days"] if basis == ProrationBasis.WORKING_DAYS else c["total_days"]
    if base == 0:
        raise ValidationError("The month has no working days to prorate against")
    c["lop_days"] = min(c["lop_days"], Decimal(base))
    c["base_days"] = base
    c["payable_days"] = Decimal(base) - c["lop_days"]
    return c


def _compute_slip(
    employee: Employee,
    assignment: EmployeeSalaryAssignment,
    days: List[AttendanceDay],
    leaves: Dict[date, LeaveRequest],
    cal: _Calendar,
) -> Tuple[Dict[str, Any], List[SalarySlipLine]]:
    structure = assignment.structure
    counts = _attendance_counts(employee, days, leaves, cal, structure.proration_basis)
    ratio = counts["payable_days"] / Decimal(counts["base_days"])

    earned: Dict[str, Decimal] = {}
    rows: List[Tuple[Any, Decimal, Decimal]] = []
    for comp, full in compute_full_amounts(structure.components, assignment.monthly_gross):
        if comp.calculation_type == CalculationType.PERCENT_OF_COMPONENT:
            # e.g. PF = 12% of the Basic actually earned this month, not of the full-month Basic
            amount = _money(earned[comp.base_component_code] * Decimal(comp.value) / HUNDRED)
        elif comp.is_prorated:
            amount = _money(full * ratio)
        else:
            amount = full
        earned[comp.code] = amount
        rows.append((comp, full, amount))

    earnings = sum((a for c, _, a in rows if c.component_type == ComponentType.EARNING), Decimal(0))
    lines: List[SalarySlipLine] = []
    deductions = Decimal(0)
    for comp, full, amount in rows:
        if comp.component_type == ComponentType.DEDUCTION:
            # Never deduct more than was earned (e.g. fixed deductions in a month with no payable days)
            amount = min(amount, earnings - deductions)
            deductions += amount
        lines.append(SalarySlipLine(
            code=comp.code, name=comp.name, component_type=comp.component_type,
            is_prorated=comp.is_prorated, full_amount=full, amount=amount, sequence=comp.sequence,
        ))

    fields = dict(
        assignment_id=assignment.id,
        structure_name=structure.name,
        proration_basis=structure.proration_basis,
        monthly_gross=assignment.monthly_gross,
        gross_earnings=earnings,
        total_deductions=deductions,
        net_pay=earnings - deductions,
        **counts,
    )
    return fields, lines


def _load_calendar(db: Session, start: date, end: date) -> _Calendar:
    policies = {p.id: p for p in calendar_repository.list_policies(db)}
    return _Calendar(
        holidays=calendar_repository.holidays_between(db, start, end),
        policies=policies,
        default_policy=next((p for p in policies.values() if p.is_default), None),
    )


def _assignments_for_period(
    db: Session, employee_ids: List[UUID], start: date, end: date
) -> Dict[UUID, EmployeeSalaryAssignment]:
    """The assignment in effect for each employee, preferring the latest one overlapping the month
    (a mid-month change applies to the whole month)."""
    rows = db.scalars(
        select(EmployeeSalaryAssignment)
        .where(
            EmployeeSalaryAssignment.employee_id.in_(employee_ids),
            EmployeeSalaryAssignment.effective_from <= end,
            or_(EmployeeSalaryAssignment.effective_to.is_(None), EmployeeSalaryAssignment.effective_to >= start),
        )
        .order_by(EmployeeSalaryAssignment.effective_from)
    ).all()
    return {a.employee_id: a for a in rows}  # later rows overwrite earlier ones


def _save_slip(
    db: Session,
    employee: Employee,
    year: int,
    month: int,
    fields: Dict[str, Any],
    lines: List[SalarySlipLine],
    note: Optional[str],
    user: User,
) -> Tuple[SalarySlip, bool]:
    start, end = _month_bounds(year, month)
    slip = db.scalars(
        select(SalarySlip)
        .where(SalarySlip.employee_id == employee.id, SalarySlip.year == year, SalarySlip.month == month)
        .with_for_update(of=SalarySlip)
    ).first()
    created = slip is None
    if slip is None:
        slip = SalarySlip(employee_id=employee.id, year=year, month=month)
        db.add(slip)
    elif slip.status != SalarySlipStatus.DRAFT:
        raise ConflictError(
            f"A {slip.status.value} salary slip already exists for {start:%B %Y} (id {slip.id}); reopen it first"
        )
    else:
        slip.lines = []
        db.flush()

    for k, v in fields.items():
        setattr(slip, k, v)
    slip.period_start, slip.period_end = start, end
    slip.note = note
    slip.generated_by_id = user.id
    slip.lines = lines
    db.flush()
    return slip, created


def generate_slip(
    db: Session, employee_id: UUID, data: SalarySlipGenerate, user: User
) -> Tuple[SalarySlip, bool]:
    """Create (or regenerate a draft) salary slip for one employee and month."""
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Employee not found")
    start, end = _month_bounds(data.year, data.month)
    _check_period(start, end, data.allow_incomplete_month)

    assignment = _assignments_for_period(db, [employee.id], start, end).get(employee.id)
    if assignment is None:
        raise ValidationError(f"No salary structure is assigned to this employee for {start:%B %Y}")

    cal = _load_calendar(db, start, end)
    days, _, leaves = attendance_repository.resolve_days_for_employees(db, [employee], start, end)[employee.id]
    fields, lines = _compute_slip(employee, assignment, days, leaves, cal)
    try:
        slip, created = _save_slip(db, employee, data.year, data.month, fields, lines, data.note, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("A salary slip for this month was created concurrently; retry")
    db.refresh(slip)
    return slip, created


def generate_slips_bulk(
    db: Session, data: BulkSalarySlipGenerate, user: User
) -> Tuple[List[SalarySlip], List[SkippedEmployee]]:
    start, end = _month_bounds(data.year, data.month)
    _check_period(start, end, data.allow_incomplete_month)

    stmt = select(Employee).order_by(Employee.employee_code)
    if data.employee_ids:
        stmt = stmt.where(Employee.id.in_(data.employee_ids))
    else:
        stmt = stmt.where(Employee.is_active.is_(True))
    if data.department:
        stmt = stmt.where(Employee.department == data.department)
    employees = list(db.scalars(stmt).all())
    if data.employee_ids:
        missing = set(data.employee_ids) - {e.id for e in employees}
        if missing:
            raise NotFoundError(f"Employee(s) not found: {', '.join(sorted(map(str, missing)))}")

    assignments = _assignments_for_period(db, [e.id for e in employees], start, end)
    cal = _load_calendar(db, start, end)
    with_assignment = [e for e in employees if e.id in assignments]
    resolved = attendance_repository.resolve_days_for_employees(db, with_assignment, start, end)

    generated: List[SalarySlip] = []
    skipped: List[SkippedEmployee] = []
    for e in employees:
        assignment = assignments.get(e.id)
        if assignment is None:
            skipped.append(SkippedEmployee(
                employee_id=e.id, employee_code=e.employee_code, reason="No salary structure assigned for this month"
            ))
            continue
        days, _, leaves = resolved[e.id]
        try:
            # Savepoint per employee: one failure doesn't discard the others
            with db.begin_nested():
                fields, lines = _compute_slip(e, assignment, days, leaves, cal)
                slip, _ = _save_slip(db, e, data.year, data.month, fields, lines, data.note, user)
            generated.append(slip)
        except DomainError as exc:
            skipped.append(SkippedEmployee(employee_id=e.id, employee_code=e.employee_code, reason=exc.detail))
        except IntegrityError:
            skipped.append(SkippedEmployee(
                employee_id=e.id, employee_code=e.employee_code, reason="Slip was created concurrently; retry"
            ))
    db.commit()
    for slip in generated:
        db.refresh(slip)
    return generated, skipped


def get_slip(db: Session, slip_id: UUID) -> SalarySlip:
    slip = db.get(SalarySlip, slip_id)
    if slip is None:
        raise NotFoundError("Salary slip not found")
    return slip


def list_slips(
    db: Session,
    employee_id: Optional[UUID] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    status: Optional[SalarySlipStatus] = None,
    department: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[List[SalarySlip], int]:
    stmt = select(SalarySlip)
    if employee_id:
        stmt = stmt.where(SalarySlip.employee_id == employee_id)
    if year:
        stmt = stmt.where(SalarySlip.year == year)
    if month:
        stmt = stmt.where(SalarySlip.month == month)
    if status:
        stmt = stmt.where(SalarySlip.status == status)
    if department:
        stmt = stmt.where(SalarySlip.employee_id.in_(select(Employee.id).where(Employee.department == department)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(SalarySlip.year.desc(), SalarySlip.month.desc(), SalarySlip.created_at)
        .offset(skip).limit(limit)
    ).unique().all()
    return list(items), total


def _locked_slip(db: Session, slip_id: UUID) -> SalarySlip:
    slip = db.scalars(select(SalarySlip).where(SalarySlip.id == slip_id).with_for_update(of=SalarySlip)).first()
    if slip is None:
        raise NotFoundError("Salary slip not found")
    return slip


def _require_status(slip: SalarySlip, expected: SalarySlipStatus, action: str) -> None:
    if slip.status != expected:
        raise ValidationError(f"Only {expected.value} slips can be {action}; this one is {slip.status.value}")


def finalize_slip(db: Session, slip_id: UUID, user: User) -> SalarySlip:
    slip = _locked_slip(db, slip_id)
    _require_status(slip, SalarySlipStatus.DRAFT, "finalized")
    slip.status = SalarySlipStatus.FINALIZED
    slip.finalized_by_id = user.id
    slip.finalized_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(slip)
    return slip


def reopen_slip(db: Session, slip_id: UUID) -> SalarySlip:
    slip = _locked_slip(db, slip_id)
    _require_status(slip, SalarySlipStatus.FINALIZED, "reopened")
    slip.status = SalarySlipStatus.DRAFT
    slip.finalized_by_id = None
    slip.finalized_at = None
    db.commit()
    db.refresh(slip)
    return slip


def mark_slip_paid(db: Session, slip_id: UUID, payment_reference: Optional[str]) -> SalarySlip:
    slip = _locked_slip(db, slip_id)
    _require_status(slip, SalarySlipStatus.FINALIZED, "marked as paid")
    slip.status = SalarySlipStatus.PAID
    slip.paid_at = datetime.now(timezone.utc)
    slip.payment_reference = payment_reference
    db.commit()
    db.refresh(slip)
    return slip


def delete_slip(db: Session, slip_id: UUID) -> None:
    slip = _locked_slip(db, slip_id)
    _require_status(slip, SalarySlipStatus.DRAFT, "deleted")
    db.delete(slip)
    db.commit()
