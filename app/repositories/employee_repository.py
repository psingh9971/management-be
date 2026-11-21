from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.employee import AadhaarCard, BankDetail, Employee, PanCard
from app.repositories.errors import NotFoundError
from app.schemas.employee import EmployeeCreate, EmployeeUpdate


def get_employee(db: Session, employee_id: UUID) -> Optional[Employee]:
    stmt = (
        select(Employee)
        .where(Employee.id == employee_id, Employee.deleted_at.is_(None))
        .options(
            selectinload(Employee.bank_detail),
            selectinload(Employee.aadhaar_card),
            selectinload(Employee.pan_card),
        )
    )
    return db.scalars(stmt).first()


def get_employee_by_code(db: Session, employee_code: str) -> Optional[Employee]:
    return db.scalars(select(Employee).where(Employee.employee_code == employee_code)).first()


def find_conflicts(db: Session, data, exclude_id: Optional[UUID] = None) -> List[str]:
    """Return human-readable messages for unique fields that are already taken.

    `data` is an EmployeeCreate or EmployeeUpdate; None fields are skipped. Pass `exclude_id`
    when updating so the employee's own current values don't count as conflicts.
    Soft-deleted employees still hold their unique values, so they are checked too.
    """

    def taken(column, value, owner_column) -> bool:
        stmt = select(column).where(column == value)
        if exclude_id is not None:
            stmt = stmt.where(owner_column != exclude_id)
        return db.scalar(stmt.limit(1)) is not None

    conflicts = []
    if data.employee_code and taken(Employee.employee_code, data.employee_code, Employee.id):
        conflicts.append(f"employee_code '{data.employee_code}' already exists")
    if data.email and taken(Employee.email, data.email, Employee.id):
        conflicts.append(f"email '{data.email}' already exists")
    if data.aadhaar_card and taken(
        AadhaarCard.aadhaar_number, data.aadhaar_card.aadhaar_number, AadhaarCard.employee_id
    ):
        conflicts.append("aadhaar_number is already registered to another employee")
    if data.pan_card and taken(PanCard.pan_number, data.pan_card.pan_number, PanCard.employee_id):
        conflicts.append("pan_number is already registered to another employee")
    return conflicts


def create_employee(db: Session, data: EmployeeCreate) -> Employee:
    employee = Employee(**data.model_dump(exclude={"bank_detail", "aadhaar_card", "pan_card"}))
    if data.bank_detail:
        employee.bank_detail = BankDetail(**data.bank_detail.model_dump())
    if data.aadhaar_card:
        employee.aadhaar_card = AadhaarCard(**data.aadhaar_card.model_dump())
    if data.pan_card:
        employee.pan_card = PanCard(**data.pan_card.model_dump())

    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


_KYC_RELATIONS = {"bank_detail": BankDetail, "aadhaar_card": AadhaarCard, "pan_card": PanCard}


def update_employee(db: Session, employee: Employee, data: EmployeeUpdate) -> Employee:
    """Apply only the fields present in the request body."""
    fields = data.model_dump(exclude_unset=True, exclude=set(_KYC_RELATIONS))
    for key, value in fields.items():
        setattr(employee, key, value)

    for rel, model in _KYC_RELATIONS.items():
        if rel not in data.model_fields_set:
            continue
        incoming = getattr(data, rel)
        current = getattr(employee, rel)
        if incoming is None:
            setattr(employee, rel, None)  # delete-orphan cascade removes the row
        elif current is None:
            setattr(employee, rel, model(**incoming.model_dump()))
        else:
            for key, value in incoming.model_dump().items():
                setattr(current, key, value)

    db.commit()
    db.refresh(employee)
    return employee


def soft_delete_employee(db: Session, employee: Employee) -> None:
    """Hide the employee everywhere and deactivate them; all data stays in the database."""
    employee.deleted_at = datetime.now(timezone.utc)
    employee.is_active = False
    db.commit()


def hard_delete_employee(db: Session, employee_id: UUID) -> bool:
    """Permanently delete the employee (soft-deleted or not) and everything linked to them.

    Every child table (KYC, bank, punches, attendance, leaves, allocations, salary structures,
    salary slips, offer letters) has an ON DELETE CASCADE FK, so Postgres removes those rows.
    """
    result = db.execute(delete(Employee).where(Employee.id == employee_id))
    db.commit()
    return result.rowcount > 0


def _filtered_employees(
    search: Optional[str] = None,
    department: Optional[str] = None,
    is_active: Optional[bool] = None,
):
    stmt = select(Employee).where(Employee.deleted_at.is_(None))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Employee.first_name.ilike(like),
                Employee.last_name.ilike(like),
                Employee.employee_code.ilike(like),
                Employee.email.ilike(like),
            )
        )
    if department:
        stmt = stmt.where(Employee.department == department)
    if is_active is not None:
        stmt = stmt.where(Employee.is_active == is_active)
    return stmt.order_by(Employee.employee_code)


def list_employees(
    db: Session,
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    department: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Tuple[List[Employee], int]:
    stmt = _filtered_employees(search, department, is_active)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.offset(skip).limit(limit)).all()
    return list(items), total


def all_employees(
    db: Session,
    search: Optional[str] = None,
    department: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> List[Employee]:
    """Every employee matching the filters (unpaginated), ordered by employee_code."""
    return list(db.scalars(_filtered_employees(search, department, is_active)).all())


def require_employee(db: Session, employee_id: UUID) -> Employee:
    """Fetch a non-deleted employee (without KYC relations) or raise NotFoundError."""
    employee = db.get(Employee, employee_id)
    if employee is None or employee.deleted_at is not None:
        raise NotFoundError("Employee not found")
    return employee
