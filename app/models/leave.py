import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

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

from app.db.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class LeaveStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class LeaveType(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Configurable leave category, e.g. Casual Leave (CL), Sick Leave (SL), Loss of Pay (LOP)."""

    __tablename__ = "leave_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_leave_types_tenant_name"),
        UniqueConstraint("tenant_id", "code", name="uq_leave_types_tenant_code"),
    )

    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(20))
    description: Mapped[Optional[str]] = mapped_column(Text)
    # Days granted per calendar year unless overridden per employee in leave_balances
    annual_quota: Mapped[Decimal] = mapped_column(Numeric(5, 1), default=0, server_default="0")
    # Paid leave is checked against the balance; unpaid (e.g. LOP) is not
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class LeaveBalance(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Per-employee override of a leave type's annual quota for a given year."""

    __tablename__ = "leave_balances"
    __table_args__ = (
        UniqueConstraint("employee_id", "leave_type_id", "year", name="uq_leave_balance_employee_type_year"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leave_types.id", ondelete="CASCADE"))
    year: Mapped[int] = mapped_column(SmallInteger)
    allocated: Mapped[Decimal] = mapped_column(Numeric(5, 1))

    leave_type: Mapped[LeaveType] = relationship(lazy="joined")


class LeaveRequest(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_leave_request_dates"),
        CheckConstraint("NOT half_day OR start_date = end_date", name="ck_leave_request_half_day_single"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leave_types.id", ondelete="RESTRICT"))
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date)
    half_day: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Working days charged, excluding week-offs and holidays (computed at apply time)
    days: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[LeaveStatus] = mapped_column(
        Enum(LeaveStatus, name="leave_status", values_callable=lambda e: [m.value for m in e]),
        default=LeaveStatus.PENDING,
        server_default=LeaveStatus.PENDING.value,
        index=True,
    )

    requested_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[Optional[str]] = mapped_column(Text)

    leave_type: Mapped[LeaveType] = relationship(lazy="joined")
