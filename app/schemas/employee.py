import re
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator

from app.models.employee import Gender
from app.schemas.common import mask

AADHAAR_RE = re.compile(r"^[2-9][0-9]{11}$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
ACCOUNT_RE = re.compile(r"^[0-9]{9,18}$")


# ---------- Bank details ----------
class BankDetailBase(BaseModel):
    account_holder_name: str = Field(..., max_length=150)
    account_number: str
    ifsc_code: str
    bank_name: str = Field(..., max_length=150)
    branch_name: Optional[str] = Field(None, max_length=150)


class BankDetailCreate(BankDetailBase):
    @field_validator("account_number")
    @classmethod
    def validate_account(cls, v: str) -> str:
        v = v.replace(" ", "")
        if not ACCOUNT_RE.match(v):
            raise ValueError("account_number must be 9-18 digits")
        return v

    @field_validator("ifsc_code")
    @classmethod
    def validate_ifsc(cls, v: str) -> str:
        v = v.strip().upper()
        if not IFSC_RE.match(v):
            raise ValueError("invalid IFSC code (expected e.g. HDFC0001234)")
        return v


class BankDetailOut(BankDetailBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID

    @field_serializer("account_number")
    def _mask(self, v: str) -> str:
        return mask(v)


# ---------- Aadhaar ----------
class AadhaarCardBase(BaseModel):
    aadhaar_number: str
    name_on_card: str = Field(..., max_length=150)
    date_of_birth: Optional[date] = None
    address: Optional[str] = None


class AadhaarCardCreate(AadhaarCardBase):
    @field_validator("aadhaar_number")
    @classmethod
    def validate_aadhaar(cls, v: str) -> str:
        v = v.replace(" ", "").replace("-", "")
        if not AADHAAR_RE.match(v):
            raise ValueError("aadhaar_number must be 12 digits and not start with 0 or 1")
        return v


class AadhaarCardOut(AadhaarCardBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID

    @field_serializer("aadhaar_number")
    def _mask(self, v: str) -> str:
        return mask(v)


# ---------- PAN ----------
class PanCardBase(BaseModel):
    pan_number: str
    name_on_card: str = Field(..., max_length=150)
    date_of_birth: Optional[date] = None


class PanCardCreate(PanCardBase):
    @field_validator("pan_number")
    @classmethod
    def validate_pan(cls, v: str) -> str:
        v = v.strip().upper()
        if not PAN_RE.match(v):
            raise ValueError("invalid PAN (expected e.g. ABCDE1234F)")
        return v


class PanCardOut(PanCardBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID

    @field_serializer("pan_number")
    def _mask(self, v: str) -> str:
        return mask(v)


# ---------- Employee ----------
class EmployeeBase(BaseModel):
    employee_code: str = Field(..., max_length=50)
    first_name: str = Field(..., max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    date_of_birth: Optional[date] = None
    gender: Optional[Gender] = None
    date_of_joining: Optional[date] = None
    designation: Optional[str] = Field(None, max_length=100)
    department: Optional[str] = Field(None, max_length=100)
    address: Optional[str] = None
    is_active: bool = True


class EmployeeCreate(EmployeeBase):
    salary: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2, description="Monthly gross salary (INR)")
    bank_detail: Optional[BankDetailCreate] = None
    aadhaar_card: Optional[AadhaarCardCreate] = None
    pan_card: Optional[PanCardCreate] = None


class EmployeeListItem(EmployeeBase):
    """Lightweight row for list views - no KYC/bank data."""
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime


class EmployeeOut(EmployeeListItem):
    updated_at: datetime
    bank_detail: Optional[BankDetailOut] = None
    aadhaar_card: Optional[AadhaarCardOut] = None
    pan_card: Optional[PanCardOut] = None


class EmployeeWithSalaryOut(EmployeeOut):
    """Full employee record including salary - only returned by the salary endpoint."""
    salary: Optional[Decimal] = None
