from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import UserRole


class LoginRequest(BaseModel):
    tenant_id: UUID  # from GET /api/tenants/current
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str
    role: UserRole
    is_super_admin: bool = False
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=150)

    @field_validator("username")
    @classmethod
    def lower_username(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        if len(v) > 128:
            raise ValueError("password must be at most 128 characters")
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    username: str
    email: Optional[str]
    full_name: Optional[str]
    role: UserRole
    is_super_admin: bool
    is_active: bool
    last_login_at: Optional[datetime]
    created_at: datetime
