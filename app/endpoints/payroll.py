from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.payroll import SalarySlipStatus
from app.models.user import User, UserRole
from app.repositories import employee_repository, payroll_repository
from app.repositories.errors import NotFoundError
from app.schemas.common import Page
from app.schemas.payroll import (
    BulkGenerateResult,
    BulkSalarySlipGenerate,
    CurrentSalaryOut,
    MarkPaidIn,
    SalaryAssignmentIn,
    SalaryAssignmentOut,
    SalaryBreakdown,
    SalarySlipGenerate,
    SalarySlipOut,
    SalarySlipSummary,
    SalaryStructureIn,
    SalaryStructureOut,
)

# Salary data is sensitive: every payroll route requires the admin or finance role
payroll_user = require_roles(UserRole.ADMIN, UserRole.FINANCE)
router = APIRouter(tags=["payroll"], dependencies=[Depends(payroll_user)])


# ---------- Salary structures ----------
@router.post("/salary-structures", response_model=SalaryStructureOut, status_code=status.HTTP_201_CREATED)
def create_salary_structure(payload: SalaryStructureIn, db: Session = Depends(get_db)):
    """Define a structure. Components are evaluated in the order given, e.g.
    BASIC 50% of gross → HRA 40% of BASIC → SPECIAL balance → PF 12% of BASIC → PT 200 fixed (not prorated)."""
    return payroll_repository.create_structure(db, payload)


@router.get("/salary-structures", response_model=List[SalaryStructureOut])
def list_salary_structures(include_inactive: bool = False, db: Session = Depends(get_db)):
    return payroll_repository.list_structures(db, include_inactive=include_inactive)


@router.get("/salary-structures/{structure_id}", response_model=SalaryStructureOut)
def get_salary_structure(structure_id: UUID, db: Session = Depends(get_db)):
    return payroll_repository.get_structure(db, structure_id)


@router.put("/salary-structures/{structure_id}", response_model=SalaryStructureOut)
def replace_salary_structure(structure_id: UUID, payload: SalaryStructureIn, db: Session = Depends(get_db)):
    """Replace the structure and all its components. Already generated slips are unaffected."""
    return payroll_repository.replace_structure(db, structure_id, payload)


@router.delete("/salary-structures/{structure_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_salary_structure(structure_id: UUID, db: Session = Depends(get_db)):
    """Only structures never assigned to anyone can be deleted; deactivate the others."""
    payroll_repository.delete_structure(db, structure_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/salary-structures/{structure_id}/preview", response_model=SalaryBreakdown)
def preview_salary_structure(
    structure_id: UUID,
    monthly_gross: Decimal = Query(..., gt=0, max_digits=12, decimal_places=2),
    db: Session = Depends(get_db),
):
    """Full-month component amounts for a given monthly gross (no attendance applied)."""
    structure = payroll_repository.get_structure(db, structure_id)
    return payroll_repository.build_breakdown(structure.components, monthly_gross)


# ---------- Assignments ----------
@router.post(
    "/employees/{employee_id}/salary-assignments",
    response_model=SalaryAssignmentOut,
    status_code=status.HTTP_201_CREATED,
)
def assign_salary_structure(
    employee_id: UUID,
    payload: SalaryAssignmentIn,
    user: User = Depends(payroll_user),
    db: Session = Depends(get_db),
):
    """Assign a structure from effective_from onwards. The previous assignment ends the day before."""
    return payroll_repository.assign_structure(db, employee_id, payload, user)


@router.get("/employees/{employee_id}/salary-assignments", response_model=List[SalaryAssignmentOut])
def list_salary_assignments(employee_id: UUID, db: Session = Depends(get_db)):
    employee_repository.require_employee(db, employee_id)
    return payroll_repository.list_assignments(db, employee_id)


@router.get("/employees/{employee_id}/salary-assignments/current", response_model=CurrentSalaryOut)
def get_current_salary(
    employee_id: UUID,
    on: Optional[date] = Query(None, alias="date", description="Defaults to today"),
    db: Session = Depends(get_db),
):
    """The assignment in effect on a date, with its full-month breakdown."""
    employee_repository.require_employee(db, employee_id)
    assignment = payroll_repository.assignment_on(db, employee_id, on or date.today())
    if assignment is None:
        raise NotFoundError("No salary structure is assigned on that date")
    return CurrentSalaryOut(
        assignment=SalaryAssignmentOut.model_validate(assignment),
        breakdown=payroll_repository.build_breakdown(assignment.structure.components, assignment.monthly_gross),
    )


@router.delete(
    "/employees/{employee_id}/salary-assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_salary_assignment(employee_id: UUID, assignment_id: UUID, db: Session = Depends(get_db)):
    """Undo the latest assignment (e.g. created by mistake); the previous one is reopened."""
    payroll_repository.delete_assignment(db, employee_id, assignment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Salary slips ----------
@router.post(
    "/employees/{employee_id}/salary-slips",
    response_model=SalarySlipOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "An existing draft slip for that month was regenerated"}},
)
def generate_salary_slip(
    employee_id: UUID,
    payload: SalarySlipGenerate,
    response: Response,
    user: User = Depends(payroll_user),
    db: Session = Depends(get_db),
):
    """Generate the month's slip from the assigned structure and attendance.
    Calling it again regenerates a draft slip (returns 200); finalized/paid slips are locked."""
    slip, created = payroll_repository.generate_slip(db, employee_id, payload, user)
    if not created:
        response.status_code = status.HTTP_200_OK
    return slip


@router.get("/employees/{employee_id}/salary-slips", response_model=Page[SalarySlipSummary])
def list_employee_salary_slips(
    employee_id: UUID,
    year: Optional[int] = Query(None, ge=2000, le=2100),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    employee_repository.require_employee(db, employee_id)
    items, total = payroll_repository.list_slips(db, employee_id=employee_id, year=year, skip=skip, limit=limit)
    return Page(items=items, total=total, skip=skip, limit=limit)


@router.post("/salary-slips/generate", response_model=BulkGenerateResult)
def generate_salary_slips_bulk(
    payload: BulkSalarySlipGenerate,
    user: User = Depends(payroll_user),
    db: Session = Depends(get_db),
):
    """Run payroll for a month: generates (or regenerates draft) slips for all active employees,
    optionally filtered by department or a list of ids. Employees that can't be processed are
    listed under `skipped` with the reason."""
    generated, skipped = payroll_repository.generate_slips_bulk(db, payload, user)
    return BulkGenerateResult(year=payload.year, month=payload.month, generated=generated, skipped=skipped)


@router.get("/salary-slips", response_model=Page[SalarySlipSummary])
def list_salary_slips(
    year: Optional[int] = Query(None, ge=2000, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    status_: Optional[SalarySlipStatus] = Query(None, alias="status"),
    employee_id: Optional[UUID] = None,
    department: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = payroll_repository.list_slips(
        db, employee_id=employee_id, year=year, month=month, status=status_,
        department=department, skip=skip, limit=limit,
    )
    return Page(items=items, total=total, skip=skip, limit=limit)


@router.get("/salary-slips/{slip_id}", response_model=SalarySlipOut)
def get_salary_slip(slip_id: UUID, db: Session = Depends(get_db)):
    return payroll_repository.get_slip(db, slip_id)


@router.post("/salary-slips/{slip_id}/finalize", response_model=SalarySlipOut)
def finalize_salary_slip(slip_id: UUID, user: User = Depends(payroll_user), db: Session = Depends(get_db)):
    """Lock a draft slip so it can no longer be regenerated."""
    return payroll_repository.finalize_slip(db, slip_id, user)


@router.post("/salary-slips/{slip_id}/reopen", response_model=SalarySlipOut)
def reopen_salary_slip(slip_id: UUID, db: Session = Depends(get_db)):
    """Move a finalized (unpaid) slip back to draft for corrections."""
    return payroll_repository.reopen_slip(db, slip_id)


@router.post("/salary-slips/{slip_id}/mark-paid", response_model=SalarySlipOut)
def mark_salary_slip_paid(slip_id: UUID, payload: Optional[MarkPaidIn] = None, db: Session = Depends(get_db)):
    return payroll_repository.mark_slip_paid(db, slip_id, payload.payment_reference if payload else None)


@router.delete("/salary-slips/{slip_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_salary_slip(slip_id: UUID, db: Session = Depends(get_db)):
    """Only draft slips can be deleted."""
    payroll_repository.delete_slip(db, slip_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
