import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _enum(cls, name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class ComponentType(str, enum.Enum):
    EARNING = "earning"
    DEDUCTION = "deduction"


class CalculationType(str, enum.Enum):
    FIXED = "fixed"                                  # value = monthly amount
    PERCENT_OF_GROSS = "percent_of_gross"            # value = % of the assignment's monthly gross
    PERCENT_OF_COMPONENT = "percent_of_component"    # value = % of an earlier component (base_component_code)
    BALANCE = "balance"                              # monthly gross minus all other earnings (one per structure)


class ProrationBasis(str, enum.Enum):
    # Pay = monthly amount x payable working days / working days (week-offs and holidays excluded)
    WORKING_DAYS = "working_days"
    # Pay = monthly amount x (calendar days - LOP days) / calendar days
    CALENDAR_DAYS = "calendar_days"


class SalarySlipStatus(str, enum.Enum):
    DRAFT = "draft"          # can be regenerated or deleted
    FINALIZED = "finalized"  # locked
    PAID = "paid"


class SalaryStructure(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reusable salary template, e.g. 'Standard Staff': Basic 50% of gross, HRA 40% of Basic,
    Special Allowance = balance, PF 12% of Basic, Professional Tax 200 fixed."""

    __tablename__ = "salary_structures"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    proration_basis: Mapped[ProrationBasis] = mapped_column(
        _enum(ProrationBasis, "proration_basis"),
        default=ProrationBasis.WORKING_DAYS,
        server_default=ProrationBasis.WORKING_DAYS.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    components: Mapped[List["SalaryStructureComponent"]] = relationship(
        back_populates="structure",
        cascade="all, delete-orphan",
        order_by="SalaryStructureComponent.sequence",
        lazy="selectin",
    )


class SalaryStructureComponent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "salary_structure_components"
    __table_args__ = (
        UniqueConstraint("structure_id", "code", name="uq_salary_component_structure_code"),
        CheckConstraint("value >= 0", name="ck_salary_component_value"),
    )

    structure_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("salary_structures.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    component_type: Mapped[ComponentType] = mapped_column(_enum(ComponentType, "salary_component_type"))
    calculation_type: Mapped[CalculationType] = mapped_column(_enum(CalculationType, "salary_calculation_type"))
    # Amount for FIXED, percentage for PERCENT_*; ignored for BALANCE
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    base_component_code: Mapped[Optional[str]] = mapped_column(String(20))
    # False = paid / deducted in full regardless of attendance (e.g. Professional Tax)
    is_prorated: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Evaluation and display order
    sequence: Mapped[int] = mapped_column(SmallInteger)

    structure: Mapped[SalaryStructure] = relationship(back_populates="components")


class EmployeeSalaryAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Links an employee to a salary structure with a monthly gross, for a date range.
    effective_to NULL = still in effect. Assigning a new structure closes the previous one."""

    __tablename__ = "employee_salary_assignments"
    __table_args__ = (
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_salary_assignment_dates"),
        CheckConstraint("monthly_gross > 0", name="ck_salary_assignment_gross"),
        UniqueConstraint("employee_id", "effective_from", name="uq_salary_assignment_employee_from"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    structure_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("salary_structures.id", ondelete="RESTRICT"))
    monthly_gross: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[Optional[date]] = mapped_column(Date)
    note: Mapped[Optional[str]] = mapped_column(Text)
    assigned_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    structure: Mapped[SalaryStructure] = relationship(lazy="joined")


class SalarySlip(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One employee's pay for one month. Attendance counts and component amounts are
    snapshotted, so later edits to the structure or attendance don't change it."""

    __tablename__ = "salary_slips"
    __table_args__ = (
        UniqueConstraint("employee_id", "year", "month", name="uq_salary_slip_employee_month"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_salary_slip_month"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    assignment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("employee_salary_assignments.id", ondelete="SET NULL")
    )
    structure_name: Mapped[str] = mapped_column(String(100))
    year: Mapped[int] = mapped_column(SmallInteger, index=True)
    month: Mapped[int] = mapped_column(SmallInteger, index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)

    # ---- Attendance snapshot ----
    proration_basis: Mapped[ProrationBasis] = mapped_column(_enum(ProrationBasis, "proration_basis"))
    total_days: Mapped[int] = mapped_column(SmallInteger)       # calendar days in the month
    working_days: Mapped[int] = mapped_column(SmallInteger)     # excluding week-offs and holidays
    week_off_days: Mapped[int] = mapped_column(SmallInteger)
    holiday_days: Mapped[int] = mapped_column(SmallInteger)
    present_days: Mapped[int] = mapped_column(SmallInteger)
    half_days: Mapped[int] = mapped_column(SmallInteger)
    paid_leave_days: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    unpaid_leave_days: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    absent_days: Mapped[int] = mapped_column(SmallInteger)
    unmarked_days: Mapped[int] = mapped_column(SmallInteger)    # working days with no attendance at all
    pre_joining_days: Mapped[int] = mapped_column(SmallInteger)
    lop_days: Mapped[Decimal] = mapped_column(Numeric(5, 1))     # loss of pay
    base_days: Mapped[int] = mapped_column(SmallInteger)        # proration denominator
    payable_days: Mapped[Decimal] = mapped_column(Numeric(5, 1))

    # ---- Amounts ----
    monthly_gross: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    gross_earnings: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    net_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    status: Mapped[SalarySlipStatus] = mapped_column(
        _enum(SalarySlipStatus, "salary_slip_status"),
        default=SalarySlipStatus.DRAFT,
        server_default=SalarySlipStatus.DRAFT.value,
        index=True,
    )
    note: Mapped[Optional[str]] = mapped_column(Text)
    generated_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    finalized_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    payment_reference: Mapped[Optional[str]] = mapped_column(String(100))

    lines: Mapped[List["SalarySlipLine"]] = relationship(
        back_populates="slip",
        cascade="all, delete-orphan",
        order_by="SalarySlipLine.sequence",
        lazy="selectin",
    )
    employee: Mapped["Employee"] = relationship(lazy="joined")  # noqa: F821


class SalarySlipLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "salary_slip_lines"

    slip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("salary_slips.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    component_type: Mapped[ComponentType] = mapped_column(_enum(ComponentType, "salary_component_type"))
    is_prorated: Mapped[bool] = mapped_column(Boolean)
    full_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # for a full month
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))       # after attendance proration
    sequence: Mapped[int] = mapped_column(SmallInteger)

    slip: Mapped[SalarySlip] = relationship(back_populates="lines")
