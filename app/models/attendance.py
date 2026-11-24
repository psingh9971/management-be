import enum
import uuid
import datetime as dt
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class PunchType(str, enum.Enum):
    IN = "in"
    OUT = "out"


class AttendancePunch(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "attendance_punches"
    # Devices often retry webhooks; this keeps the same punch from being stored twice.
    __table_args__ = (
        UniqueConstraint("employee_id", "punch_time", "device_id", name="uq_punch_employee_time_device"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    punch_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    punch_type: Mapped[Optional[PunchType]] = mapped_column(
        Enum(PunchType, name="punch_type", values_callable=lambda e: [m.value for m in e])
    )
    device_id: Mapped[str] = mapped_column(String(100), default="unknown", server_default="unknown")
    source: Mapped[str] = mapped_column(String(50), default="webhook", server_default="webhook")
    raw_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    employee: Mapped["Employee"] = relationship(back_populates="punches")  # noqa: F821


class AttendanceStatus(str, enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"
    HALF_DAY = "half_day"
    WEEK_OFF = "week_off"
    LEAVE = "leave"


class AttendanceRecord(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """The attendance status of one employee for one day (raw device punches live in
    attendance_punches). Currently filled by manual marking."""

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_attendance_record_employee_date"),
        CheckConstraint(
            "check_out IS NULL OR check_in IS NULL OR check_out > check_in",
            name="ck_attendance_record_times",
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    status: Mapped[AttendanceStatus] = mapped_column(
        Enum(AttendanceStatus, name="attendance_status", values_callable=lambda e: [m.value for m in e])
    )
    check_in: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    check_out: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(50), default="manual", server_default="manual")
    note: Mapped[Optional[str]] = mapped_column(Text)
    marked_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
