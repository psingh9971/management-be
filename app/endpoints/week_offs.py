from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.user import UserRole
from app.repositories import calendar_repository, employee_repository
from app.schemas.calendar import AssignWeekOffPolicy, WeekOffPolicyIn, WeekOffPolicyOut

router = APIRouter(tags=["leave configuration"])
admin_only = [Depends(require_roles(UserRole.ADMIN))]


@router.get("/week-off-policies", response_model=List[WeekOffPolicyOut])
def list_policies(db: Session = Depends(get_db)):
    return calendar_repository.list_policies(db)


@router.post(
    "/week-off-policies",
    response_model=WeekOffPolicyOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=admin_only,
)
def create_policy(payload: WeekOffPolicyIn, db: Session = Depends(get_db)):
    return calendar_repository.create_policy(db, payload)


@router.put("/week-off-policies/{policy_id}", response_model=WeekOffPolicyOut, dependencies=admin_only)
def replace_policy(policy_id: UUID, payload: WeekOffPolicyIn, db: Session = Depends(get_db)):
    """Replaces the policy's name, default flag and full rule set."""
    return calendar_repository.replace_policy(db, policy_id, payload)


@router.get("/employees/{employee_id}/week-off-policy", response_model=Optional[WeekOffPolicyOut])
def get_employee_policy(employee_id: UUID, db: Session = Depends(get_db)):
    """The policy in effect for the employee (their own, else the default; null if neither)."""
    employee = employee_repository.require_employee(db, employee_id)
    return calendar_repository.effective_policy(db, employee)


@router.put(
    "/employees/{employee_id}/week-off-policy",
    response_model=Optional[WeekOffPolicyOut],
    dependencies=admin_only,
)
def assign_policy(employee_id: UUID, payload: AssignWeekOffPolicy, db: Session = Depends(get_db)):
    employee = employee_repository.require_employee(db, employee_id)
    return calendar_repository.assign_policy(db, employee, payload.policy_id)
