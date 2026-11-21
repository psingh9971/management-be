from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.offer_letter import OfferLetter, OfferLetterStatus
from app.models.payroll import ComponentType, EmployeeSalaryAssignment
from app.models.user import User
from app.repositories import payroll_repository
from app.repositories.errors import ConflictError, NotFoundError, ValidationError
from app.schemas.offer_letter import OfferLetterConfirm, OfferLetterCreate, OfferLetterUpdate

MONTHS_PER_YEAR = Decimal(12)


def _full_name(e: Employee) -> str:
    return " ".join(p for p in (e.first_name, e.last_name) if p)


def _current_assignment(db: Session, employee_id: UUID) -> EmployeeSalaryAssignment:
    """The employee's latest (open-ended) salary assignment - what the candidate is being offered."""
    assignment = db.scalars(
        select(EmployeeSalaryAssignment).where(
            EmployeeSalaryAssignment.employee_id == employee_id,
            EmployeeSalaryAssignment.effective_to.is_(None),
        )
    ).first()
    if assignment is None:
        raise ValidationError(
            "Assign a salary structure to this employee first (POST /api/employees/{id}/salary-assignments)"
        )
    return assignment


def _snapshot_salary(letter: OfferLetter, assignment: EmployeeSalaryAssignment) -> None:
    b = payroll_repository.build_breakdown(assignment.structure.components, assignment.monthly_gross)
    letter.assignment_id = assignment.id
    letter.structure_name = assignment.structure.name
    letter.monthly_gross = b.gross_earnings
    letter.annual_gross = b.gross_earnings * MONTHS_PER_YEAR
    letter.monthly_deductions = b.total_deductions
    letter.monthly_net = b.net_pay
    letter.components = [
        {
            "code": c.code,
            "name": c.name,
            "component_type": c.component_type.value,
            "monthly": str(c.amount),
            "annual": str(c.amount * MONTHS_PER_YEAR),
        }
        for c in b.components
    ]


def _next_letter_number(db: Session, year: int) -> str:
    prefix = f"OL-{year}-"
    last = db.scalar(
        select(func.max(OfferLetter.letter_number)).where(OfferLetter.letter_number.like(f"{prefix}%"))
    )
    seq = int(last[len(prefix):]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def _active_letter(db: Session, employee_id: UUID) -> Optional[OfferLetter]:
    return db.scalars(
        select(OfferLetter).where(
            OfferLetter.employee_id == employee_id, OfferLetter.status != OfferLetterStatus.WITHDRAWN
        )
    ).first()


def create_letter(db: Session, employee_id: UUID, data: OfferLetterCreate, user: User) -> OfferLetter:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Employee not found")
    existing = _active_letter(db, employee.id)
    if existing:
        raise ConflictError(
            f"Employee already has a {existing.status.value} offer letter ({existing.letter_number}); "
            "update or withdraw it first"
        )
    designation = data.designation or employee.designation
    if not designation:
        raise ValidationError("designation is required because the employee record has none")

    offer_date = data.offer_date or date.today()
    letter = OfferLetter(
        letter_number=_next_letter_number(db, offer_date.year),
        employee_id=employee.id,
        status=OfferLetterStatus.PROVISIONAL,
        candidate_name=_full_name(employee),
        designation=designation,
        department=data.department or employee.department,
        work_location=data.work_location,
        offer_date=offer_date,
        tentative_joining_date=data.tentative_joining_date,
        valid_until=data.valid_until,
        terms=data.terms,
        issued_by_id=user.id,
    )
    _snapshot_salary(letter, _current_assignment(db, employee.id))
    db.add(letter)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("Another offer letter was created at the same time; retry")
    db.refresh(letter)
    return letter


def get_letter(db: Session, letter_id: UUID) -> OfferLetter:
    letter = db.get(OfferLetter, letter_id)
    if letter is None:
        raise NotFoundError("Offer letter not found")
    return letter


def list_letters(
    db: Session,
    employee_id: Optional[UUID] = None,
    status: Optional[OfferLetterStatus] = None,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[List[OfferLetter], int]:
    stmt = select(OfferLetter)
    if employee_id:
        stmt = stmt.where(OfferLetter.employee_id == employee_id)
    if status:
        stmt = stmt.where(OfferLetter.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(OfferLetter.created_at.desc()).offset(skip).limit(limit)).all()
    return list(items), total


def _locked(db: Session, letter_id: UUID) -> OfferLetter:
    letter = db.scalars(
        select(OfferLetter).where(OfferLetter.id == letter_id).with_for_update(of=OfferLetter)
    ).first()
    if letter is None:
        raise NotFoundError("Offer letter not found")
    return letter


def update_letter(db: Session, letter_id: UUID, data: OfferLetterUpdate) -> OfferLetter:
    """Edit a provisional letter and refresh its salary from the current assignment."""
    letter = _locked(db, letter_id)
    if letter.status != OfferLetterStatus.PROVISIONAL:
        raise ValidationError(f"Only provisional offer letters can be edited; this one is {letter.status.value}")
    changes = data.model_dump(exclude_unset=True)
    if "designation" in changes and not changes["designation"]:
        raise ValidationError("designation cannot be empty")
    for field, value in changes.items():
        setattr(letter, field, value)
    if letter.valid_until and letter.valid_until < letter.offer_date:
        raise ValidationError("valid_until must be on or after the offer date")
    letter.candidate_name = _full_name(letter.employee)
    _snapshot_salary(letter, _current_assignment(db, letter.employee_id))
    db.commit()
    db.refresh(letter)
    return letter


def confirm_letter(db: Session, letter_id: UUID, data: OfferLetterConfirm, user: User) -> OfferLetter:
    """Fix the joining date. The salary disclosed in the provisional letter is kept as-is;
    to change it, edit the letter while it is still provisional."""
    letter = _locked(db, letter_id)
    if letter.status != OfferLetterStatus.PROVISIONAL:
        raise ValidationError(f"Only provisional offer letters can be confirmed; this one is {letter.status.value}")
    if data.joining_date < letter.offer_date:
        raise ValidationError("joining_date cannot be before the offer date")
    letter.status = OfferLetterStatus.CONFIRMED
    letter.joining_date = data.joining_date
    letter.confirmed_by_id = user.id
    letter.confirmed_at = datetime.now(timezone.utc)
    if data.update_employee_joining_date:
        letter.employee.date_of_joining = data.joining_date
    db.commit()
    db.refresh(letter)
    return letter


def withdraw_letter(db: Session, letter_id: UUID, reason: str) -> OfferLetter:
    letter = _locked(db, letter_id)
    if letter.status == OfferLetterStatus.WITHDRAWN:
        raise ValidationError("Offer letter is already withdrawn")
    letter.status = OfferLetterStatus.WITHDRAWN
    letter.withdrawn_at = datetime.now(timezone.utc)
    letter.withdrawal_reason = reason
    db.commit()
    db.refresh(letter)
    return letter


def components_of(letter: OfferLetter, kind: ComponentType) -> List[dict]:
    return [c for c in (letter.components or []) if c["component_type"] == kind.value]
