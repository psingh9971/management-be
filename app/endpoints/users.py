from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import require_super_admin
from app.db.session import get_db
from app.repositories import user_repository
from app.schemas.common import Page
from app.schemas.user import UserCreate, UserOut

# Managing application users is restricted to super admins
router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_super_admin)])


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    conflicts = user_repository.find_conflicts(db, payload)
    if conflicts:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflicts)
    try:
        return user_repository.create_user(db, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")


@router.get("", response_model=Page[UserOut])
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = user_repository.list_users(db, skip=skip, limit=limit)
    return Page(items=items, total=total, skip=skip, limit=limit)
