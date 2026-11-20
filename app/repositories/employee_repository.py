from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.employee import AadhaarCard, BankDetail, Employee, PanCard
from app.repositories.errors import NotFoundError
from app.schemas.employee import EmployeeCreate


def get_employee(db: Session, employee_id: UUID) -> Optional[Employee]:
    stmt = (
        select(Employee)
        .where(Employee.id == employee_id)
        .options(
            selectinload(Employee.bank_detail),
            selectinload(Employee.aadhaar_card),
            selectinload(Employee.pan_card),
        )
    )
    return db.scalars(stmt).first()


def get_employee_by_code(db: Session, employee_code: str) -> Optional[Employee]:
    return db.scalars(select(Employee).where(Employee.employee_code == employee_code)).first()


def find_conflicts(db: Session, data: EmployeeCreate) -> List[str]:
    """Return human-readable messages for unique fields that are already taken."""
    conflicts = []
    if get_employee_by_code(db, data.employee_code):
        conflicts.append(f"employee_code '{data.employee_code}' already exists")
    if data.email and db.scalar(select(Employee.id).where(Employee.email == data.email)):
        conflicts.append(f"email '{data.email}' already exists")
    if data.aadhaar_card and db.scalar(
        select(AadhaarCard.id).where(AadhaarCard.aadhaar_number == data.aadhaar_card.aadhaar_number)
    ):
        conflicts.append("aadhaar_number is already registered to another employee")
    if data.pan_card and db.scalar(
        select(PanCard.id).where(PanCard.pan_number == data.pan_card.pan_number)
    ):
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


def _filtered_employees(
    search: Optional[str] = None,
    department: Optional[str] = None,
    is_active: Optional[bool] = None,
):
    stmt = select(Employee)
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
    """Fetch an employee (without KYC relations) or raise NotFoundError."""
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Employee not found")
    return employee
