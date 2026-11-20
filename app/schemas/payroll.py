from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.payroll import CalculationType, ComponentType, ProrationBasis, SalarySlipStatus

Money = Decimal


# ---------- Salary structures ----------
class SalaryComponentIn(BaseModel):
    code: str = Field(..., max_length=20, pattern=r"^[A-Za-z0-9_]+$", examples=["BASIC"])
    name: str = Field(..., max_length=100, examples=["Basic Salary"])
    component_type: ComponentType
    calculation_type: CalculationType
    value: Decimal = Field(
        Decimal("0"), ge=0, max_digits=12, decimal_places=2,
        description="Monthly amount for fixed; percentage for percent_of_*; ignored for balance",
    )
    base_component_code: Optional[str] = Field(
        None, max_length=20, description="Required for percent_of_component: code of an earlier component"
    )
    is_prorated: bool = Field(
        True,
        description="False = paid/deducted in full regardless of attendance. percent_of_component always "
        "follows the earned amount of its base component. Deductions never exceed total earnings.",
    )

    @field_validator("code", "base_component_code")
    @classmethod
    def upper(cls, v: Optional[str]) -> Optional[str]:
        return v.upper() if v else v


class SalaryStructureIn(BaseModel):
    """Components are evaluated (and shown on slips) in the order given."""

    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    proration_basis: ProrationBasis = ProrationBasis.WORKING_DAYS
    is_active: bool = True
    components: List[SalaryComponentIn] = Field(..., min_length=1)

    @model_validator(mode="after")
    def check_components(self) -> "SalaryStructureIn":
        seen = {}
        balance_count = 0
        for c in self.components:
            if c.code in seen:
                raise ValueError(f"Duplicate component code '{c.code}'")
            if c.calculation_type == CalculationType.BALANCE:
                balance_count += 1
                if c.component_type != ComponentType.EARNING:
                    raise ValueError(f"'{c.code}': balance components must be earnings")
            if c.calculation_type in (CalculationType.PERCENT_OF_GROSS, CalculationType.PERCENT_OF_COMPONENT):
                if c.value > 100:
                    raise ValueError(f"'{c.code}': percentage cannot exceed 100")
            if c.calculation_type == CalculationType.PERCENT_OF_COMPONENT:
                base = c.base_component_code
                if not base:
                    raise ValueError(f"'{c.code}': base_component_code is required for percent_of_component")
                if base not in seen:
                    raise ValueError(f"'{c.code}': base component '{base}' must be listed before it")
                if seen[base].calculation_type == CalculationType.BALANCE:
                    raise ValueError(f"'{c.code}': cannot be a percentage of a balance component")
            elif c.base_component_code:
                raise ValueError(f"'{c.code}': base_component_code is only used with percent_of_component")
            seen[c.code] = c
        if balance_count > 1:
            raise ValueError("A structure can have at most one balance component")
        if not any(c.component_type == ComponentType.EARNING for c in self.components):
            raise ValueError("A structure needs at least one earning component")
        return self


class SalaryComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    component_type: ComponentType
    calculation_type: CalculationType
    value: Decimal
    base_component_code: Optional[str]
    is_prorated: bool
    sequence: int


class SalaryStructureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str]
    proration_basis: ProrationBasis
    is_active: bool
    components: List[SalaryComponentOut]
    created_at: datetime
    updated_at: datetime


class ComponentAmount(BaseModel):
    code: str
    name: str
    component_type: ComponentType
    is_prorated: bool
    amount: Money


class SalaryBreakdown(BaseModel):
    """Full-month amounts (no attendance applied)."""

    monthly_gross: Money
    components: List[ComponentAmount]
    gross_earnings: Money
    total_deductions: Money
    net_pay: Money


# ---------- Assignments ----------
class SalaryAssignmentIn(BaseModel):
    structure_id: UUID
    effective_from: date
    monthly_gross: Optional[Decimal] = Field(
        None, gt=0, max_digits=12, decimal_places=2,
        description="Defaults to the employee's salary field",
    )
    note: Optional[str] = None


class SalaryAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_id: UUID
    structure_id: UUID
    structure_name: str
    monthly_gross: Money
    effective_from: date
    effective_to: Optional[date]
    note: Optional[str]
    assigned_by_id: Optional[UUID]
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def flatten_structure(cls, data):
        if not isinstance(data, dict) and hasattr(data, "structure"):
            return {
                **{k: getattr(data, k) for k in cls.model_fields if k != "structure_name"},
                "structure_name": data.structure.name,
            }
        return data


class CurrentSalaryOut(BaseModel):
    assignment: SalaryAssignmentOut
    breakdown: SalaryBreakdown


# ---------- Salary slips ----------
class SalarySlipGenerate(BaseModel):
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    allow_incomplete_month: bool = Field(
        False,
        description="Allow a month that hasn't ended yet. Remaining days with no attendance count as loss of pay.",
    )
    note: Optional[str] = None


class BulkSalarySlipGenerate(SalarySlipGenerate):
    department: Optional[str] = None
    employee_ids: Optional[List[UUID]] = Field(None, description="Defaults to all active employees")


class SalarySlipLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    component_type: ComponentType
    is_prorated: bool
    full_amount: Money
    amount: Money


class AttendanceBreakdown(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    proration_basis: ProrationBasis
    total_days: int
    working_days: int
    week_off_days: int
    holiday_days: int
    present_days: int
    half_days: int
    paid_leave_days: float
    unpaid_leave_days: float
    absent_days: int
    unmarked_days: int
    pre_joining_days: int
    lop_days: float
    base_days: int
    payable_days: float


class SalarySlipSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_id: UUID
    employee_code: str
    employee_name: str
    year: int
    month: int
    structure_name: str
    payable_days: float
    lop_days: float
    gross_earnings: Money
    total_deductions: Money
    net_pay: Money
    status: SalarySlipStatus

    @model_validator(mode="before")
    @classmethod
    def from_slip(cls, data):
        # Build from a SalarySlip ORM object: flatten the employee and (for the
        # detailed view) group attendance fields and split lines by type.
        if isinstance(data, dict) or not hasattr(data, "employee"):
            return data
        e = data.employee
        out = {k: getattr(data, k) for k in cls.model_fields if hasattr(data, k)}
        out["employee_code"] = e.employee_code
        out["employee_name"] = " ".join(p for p in (e.first_name, e.last_name) if p)
        if "attendance" in cls.model_fields:
            out["attendance"] = AttendanceBreakdown.model_validate(data)
        if "earnings" in cls.model_fields:
            out["earnings"] = [ln for ln in data.lines if ln.component_type == ComponentType.EARNING]
            out["deductions"] = [ln for ln in data.lines if ln.component_type == ComponentType.DEDUCTION]
        return out


class SalarySlipOut(SalarySlipSummary):
    assignment_id: Optional[UUID]
    period_start: date
    period_end: date
    monthly_gross: Money
    attendance: AttendanceBreakdown
    earnings: List[SalarySlipLineOut]
    deductions: List[SalarySlipLineOut]
    note: Optional[str]
    generated_by_id: Optional[UUID]
    finalized_by_id: Optional[UUID]
    finalized_at: Optional[datetime]
    paid_at: Optional[datetime]
    payment_reference: Optional[str]
    created_at: datetime
    updated_at: datetime


class SkippedEmployee(BaseModel):
    employee_id: UUID
    employee_code: str
    reason: str


class BulkGenerateResult(BaseModel):
    year: int
    month: int
    generated: List[SalarySlipSummary]
    skipped: List[SkippedEmployee]


class MarkPaidIn(BaseModel):
    payment_reference: Optional[str] = Field(None, max_length=100, description="e.g. bank transaction / UTR number")
