from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import DUMMY_HASH, hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.scalars(select(User).where(User.username == username.lower())).first()


def find_conflicts(db: Session, data: UserCreate) -> List[str]:
    conflicts = []
    if get_user_by_username(db, data.username):
        conflicts.append(f"username '{data.username}' already exists")
    if data.email and db.scalar(select(User.id).where(User.email == data.email)):
        conflicts.append(f"email '{data.email}' already exists")
    return conflicts


def create_user(db: Session, data: UserCreate) -> User:
    user = User(
        username=data.username,
        email=data.email,
        full_name=data.full_name,
        role=data.role,
        is_super_admin=data.is_super_admin,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    """Return the user if credentials are valid and the account is active."""
    user = get_user_by_username(db, username)
    if user is None:
        verify_password(password, DUMMY_HASH)  # equalise timing
        return None
    if not verify_password(password, user.hashed_password) or not user.is_active:
        return None
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return user


def list_users(db: Session, skip: int = 0, limit: int = 50) -> Tuple[List[User], int]:
    total = db.scalar(select(func.count()).select_from(User)) or 0
    items = db.scalars(select(User).order_by(User.id).offset(skip).limit(limit)).all()
    return list(items), total
