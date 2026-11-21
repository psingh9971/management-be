import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class OfferLetterStatus(str, enum.Enum):
    PROVISIONAL = "provisional"  # salary disclosed, joining date not yet confirmed
    CONFIRMED = "confirmed"      # joining date confirmed
    WITHDRAWN = "withdrawn"


class OfferLetter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Offer to a candidate (an employee record that hasn't joined yet). The salary breakdown is
    a snapshot of the employee's assigned salary structure at the time the letter was issued/updated."""

    __tablename__ = "offer_letters"
    __table_args__ = (
        # At most one live (non-withdrawn) offer per candidate
        Index(
            "uq_offer_letters_single_active",
            "employee_id",
            unique=True,
            postgresql_where=text("status <> 'withdrawn'"),
        ),
    )

    letter_number: Mapped[str] = mapped_column(String(30), unique=True)  # e.g. OL-2026-0001
    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[OfferLetterStatus] = mapped_column(
        Enum(OfferLetterStatus, name="offer_letter_status", values_callable=lambda e: [m.value for m in e]),
        default=OfferLetterStatus.PROVISIONAL,
        server_default=OfferLetterStatus.PROVISIONAL.value,
        index=True,
    )

    # ---- Position ----
    candidate_name: Mapped[str] = mapped_column(String(200))
    designation: Mapped[str] = mapped_column(String(100))
    department: Mapped[Optional[str]] = mapped_column(String(100))
    work_location: Mapped[Optional[str]] = mapped_column(String(150))

    # ---- Dates ----
    offer_date: Mapped[date] = mapped_column(Date)
    tentative_joining_date: Mapped[Optional[date]] = mapped_column(Date)
    joining_date: Mapped[Optional[date]] = mapped_column(Date)   # set when confirmed
    valid_until: Mapped[Optional[date]] = mapped_column(Date)    # accept-by date

    # ---- Salary snapshot (from the salary assignment) ----
    assignment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("employee_salary_assignments.id", ondelete="SET NULL")
    )
    structure_name: Mapped[str] = mapped_column(String(100))
    monthly_gross: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    annual_gross: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    monthly_deductions: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    monthly_net: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # [{code, name, component_type, monthly, annual}], amounts as strings
    components: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB)

    terms: Mapped[Optional[str]] = mapped_column(Text)

    issued_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    withdrawal_reason: Mapped[Optional[str]] = mapped_column(Text)

    employee: Mapped["Employee"] = relationship(lazy="joined")  # noqa: F821
