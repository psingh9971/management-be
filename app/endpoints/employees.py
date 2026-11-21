from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import require_super_admin
from app.db.session import get_db
from app.repositories import attendance_repository, employee_repository
from app.schemas.attendance import PunchOut
from app.schemas.common import Page
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeListItem,
    EmployeeOut,
    EmployeeUpdate,
    EmployeeWithSalaryOut,
)

router = APIRouter(prefix="/employees", tags=["employees"])


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def add_employee(payload: EmployeeCreate, db: Session = Depends(get_db)):
    conflicts = employee_repository.find_conflicts(db, payload)
    if conflicts:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflicts)
    try:
        employee = employee_repository.create_employee(db, payload)
    except IntegrityError:
        # Lost a race with a concurrent insert of the same unique value
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Employee already exists")
    return employee_repository.get_employee(db, employee.id)


@router.get("", response_model=Page[EmployeeListItem])
def list_employees(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None, description="Matches name, employee code or email"),
    department: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    items, total = employee_repository.list_employees(
        db, skip=skip, limit=limit, search=search, department=department, is_active=is_active
    )
    return Page(items=items, total=total, skip=skip, limit=limit)


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: UUID, db: Session = Depends(get_db)):
    employee = employee_repository.get_employee(db, employee_id)
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return employee


@router.patch("/{employee_id}", response_model=EmployeeOut)
def update_employee(employee_id: UUID, payload: EmployeeUpdate, db: Session = Depends(get_db)):
    """Partially update an employee. Only the fields sent in the body are changed."""
    employee = employee_repository.get_employee(db, employee_id)
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    conflicts = employee_repository.find_conflicts(db, payload, exclude_id=employee_id)
    if conflicts:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflicts)
    try:
        employee_repository.update_employee(db, employee, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Employee already exists")
    return employee_repository.get_employee(db, employee_id)


@router.delete("/{employee_id}/soft", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete_employee(employee_id: UUID, db: Session = Depends(get_db)):
    """Delete action for the frontend: hides the employee from every API and deactivates them,
    but keeps the record and all its attendance / leave / payroll history in the database."""
    employee = employee_repository.require_employee(db, employee_id)
    employee_repository.soft_delete_employee(db, employee)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_super_admin)],
)
def hard_delete_employee(employee_id: UUID, db: Session = Depends(get_db)):
    """Permanently delete an employee (including soft-deleted ones) and ALL linked data:
    KYC, bank details, punches, attendance, leaves, salary structures, salary slips and
    offer letters. Irreversible - super admin only."""
    if not employee_repository.hard_delete_employee(db, employee_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{employee_id}/salary", response_model=EmployeeWithSalaryOut)
def get_employee_with_salary(employee_id: UUID, db: Session = Depends(get_db)):
    employee = employee_repository.get_employee(db, employee_id)
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return employee


@router.get("/{employee_id}/punches", response_model=List[PunchOut])
def list_employee_punches(
    employee_id: UUID,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if not employee_repository.get_employee(db, employee_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return attendance_repository.list_punches(
        db, employee_id, date_from=date_from, date_to=date_to, skip=skip, limit=limit
    )
