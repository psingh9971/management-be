from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.user import UserRole
from app.repositories import calendar_repository
from app.schemas.calendar import HolidayIn, HolidayOut

router = APIRouter(prefix="/holidays", tags=["leave configuration"])
admin_only = [Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=List[HolidayOut])
def list_holidays(year: Optional[int] = Query(None, ge=2000, le=2100), db: Session = Depends(get_db)):
    return calendar_repository.list_holidays(db, year=year)


@router.post("", response_model=HolidayOut, status_code=status.HTTP_201_CREATED, dependencies=admin_only)
def create_holiday(payload: HolidayIn, db: Session = Depends(get_db)):
    return calendar_repository.create_holiday(db, payload)


@router.delete("/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=admin_only)
def delete_holiday(holiday_id: UUID, db: Session = Depends(get_db)):
    calendar_repository.delete_holiday(db, holiday_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
