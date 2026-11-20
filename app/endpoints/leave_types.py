from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.user import UserRole
from app.repositories import leave_repository
from app.schemas.leave import LeaveTypeCreate, LeaveTypeOut, LeaveTypeUpdate

router = APIRouter(prefix="/leave-types", tags=["leave configuration"])
admin_only = [Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=List[LeaveTypeOut])
def list_leave_types(include_inactive: bool = False, db: Session = Depends(get_db)):
    return leave_repository.list_leave_types(db, include_inactive=include_inactive)


@router.post("", response_model=LeaveTypeOut, status_code=status.HTTP_201_CREATED, dependencies=admin_only)
def create_leave_type(payload: LeaveTypeCreate, db: Session = Depends(get_db)):
    return leave_repository.create_leave_type(db, payload)


@router.patch("/{leave_type_id}", response_model=LeaveTypeOut, dependencies=admin_only)
def update_leave_type(leave_type_id: UUID, payload: LeaveTypeUpdate, db: Session = Depends(get_db)):
    return leave_repository.update_leave_type(db, leave_type_id, payload)
