import uuid
from typing import Callable, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User, UserRole

# Gives Swagger UI an "Authorize" button where the token can be pasted
bearer_scheme = HTTPBearer(auto_error=False)

_unauthorized = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise _unauthorized
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _unauthorized
    # Load from DB on every request so deactivation / role changes take effect immediately
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized
    return user


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    return user


def require_roles(*roles: UserRole) -> Callable[..., User]:
    """Usage: Depends(require_roles(UserRole.ADMIN, UserRole.FINANCE)). Super admins always pass."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.is_super_admin or user.role in roles:
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    return checker
