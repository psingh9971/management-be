from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.offer_letter import OfferLetterStatus
from app.models.payroll import ComponentType


class OfferLetterCreate(BaseModel):
    """Designation and department default to the employee record."""

    designation: Optional[str] = Field(None, max_length=100)
    department: Optional[str] = Field(None, max_length=100)
    work_location: Optional[str] = Field(None, max_length=150)
    offer_date: Optional[date] = Field(None, description="Defaults to today")
    tentative_joining_date: Optional[date] = Field(
        None, description="Shown as tentative; the joining date is fixed when the offer is confirmed"
    )
    valid_until: Optional[date] = Field(None, description="Date by which the candidate must accept")
    terms: Optional[str] = Field(None, description="Additional terms printed on the letter")

    @model_validator(mode="after")
    def check_dates(self):
        offer = self.offer_date or date.today()
        if self.valid_until and self.valid_until < offer:
            raise ValueError("valid_until must be on or after the offer date")
        if self.tentative_joining_date and self.tentative_joining_date < offer:
            raise ValueError("tentative_joining_date must be on or after the offer date")
        return self


class OfferLetterUpdate(BaseModel):
    """Edit a provisional letter. The salary breakdown is always re-read from the
    employee's current salary assignment."""

    designation: Optional[str] = Field(None, max_length=100)
    department: Optional[str] = Field(None, max_length=100)
    work_location: Optional[str] = Field(None, max_length=150)
    tentative_joining_date: Optional[date] = None
    valid_until: Optional[date] = None
    terms: Optional[str] = None


class OfferLetterConfirm(BaseModel):
    joining_date: date
    update_employee_joining_date: bool = Field(
        True, description="Also set the employee's date_of_joining (used by payroll for proration)"
    )


class OfferLetterWithdraw(BaseModel):
    reason: str = Field(..., min_length=3)


class OfferComponent(BaseModel):
    code: str
    name: str
    component_type: ComponentType
    monthly: Decimal
    annual: Decimal


class OfferLetterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    letter_number: str
    employee_id: UUID
    employee_code: str
    status: OfferLetterStatus
    candidate_name: str
    designation: str
    department: Optional[str]
    work_location: Optional[str]
    offer_date: date
    tentative_joining_date: Optional[date]
    joining_date: Optional[date]
    valid_until: Optional[date]
    assignment_id: Optional[UUID]
    structure_name: str
    monthly_gross: Decimal
    annual_gross: Decimal
    monthly_deductions: Decimal
    monthly_net: Decimal
    earnings: List[OfferComponent]
    deductions: List[OfferComponent]
    terms: Optional[str]
    issued_by_id: Optional[UUID]
    confirmed_by_id: Optional[UUID]
    confirmed_at: Optional[datetime]
    withdrawn_at: Optional[datetime]
    withdrawal_reason: Optional[str]
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def from_letter(cls, data):
        if isinstance(data, dict) or not hasattr(data, "employee"):
            return data
        out = {k: getattr(data, k) for k in cls.model_fields if hasattr(data, k)}
        out["employee_code"] = data.employee.employee_code
        comps = data.components or []
        out["earnings"] = [c for c in comps if c["component_type"] == ComponentType.EARNING.value]
        out["deductions"] = [c for c in comps if c["component_type"] == ComponentType.DEDUCTION.value]
        return out
