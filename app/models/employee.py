import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class Employee(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employees"

    # Code used by attendance devices to identify the employee
    employee_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    gender: Mapped[Optional[Gender]] = mapped_column(
        Enum(Gender, name="gender", values_callable=lambda e: [m.value for m in e])
    )
    date_of_joining: Mapped[Optional[date]] = mapped_column(Date)
    designation: Mapped[Optional[str]] = mapped_column(String(100))
    department: Mapped[Optional[str]] = mapped_column(String(100))
    address: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Set by the soft-delete API. Soft-deleted employees are hidden from every API but the row
    # (and its attendance / leave / payroll history) is kept. NULL = not deleted.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    # Monthly gross salary in INR. Nullable only for rows created before this column existed;
    # the create API requires it. Exposed only via GET /employees/{id}/salary.
    salary: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    # NULL = use the default week-off policy
    week_off_policy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("week_off_policies.id", ondelete="SET NULL")
    )

    bank_detail: Mapped[Optional["BankDetail"]] = relationship(
        back_populates="employee", uselist=False, cascade="all, delete-orphan"
    )
    aadhaar_card: Mapped[Optional["AadhaarCard"]] = relationship(
        back_populates="employee", uselist=False, cascade="all, delete-orphan"
    )
    pan_card: Mapped[Optional["PanCard"]] = relationship(
        back_populates="employee", uselist=False, cascade="all, delete-orphan"
    )
    punches: Mapped[List["AttendancePunch"]] = relationship(  # noqa: F821
        back_populates="employee", cascade="all, delete-orphan"
    )
    week_off_policy: Mapped[Optional["WeekOffPolicy"]] = relationship()  # noqa: F821


class BankDetail(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employee_bank_details"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), unique=True
    )
    account_holder_name: Mapped[str] = mapped_column(String(150))
    account_number: Mapped[str] = mapped_column(String(34))
    ifsc_code: Mapped[str] = mapped_column(String(11))
    bank_name: Mapped[str] = mapped_column(String(150))
    branch_name: Mapped[Optional[str]] = mapped_column(String(150))

    employee: Mapped[Employee] = relationship(back_populates="bank_detail")


class AadhaarCard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employee_aadhaar_cards"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), unique=True
    )
    aadhaar_number: Mapped[str] = mapped_column(String(12), unique=True)
    name_on_card: Mapped[str] = mapped_column(String(150))
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    address: Mapped[Optional[str]] = mapped_column(Text)

    employee: Mapped[Employee] = relationship(back_populates="aadhaar_card")


class PanCard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employee_pan_cards"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), unique=True
    )
    pan_number: Mapped[str] = mapped_column(String(10), unique=True)
    name_on_card: Mapped[str] = mapped_column(String(150))
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)

    employee: Mapped[Employee] = relationship(back_populates="pan_card")
