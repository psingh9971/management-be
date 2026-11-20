import uuid
import datetime as dt
from typing import List, Optional

from sqlalchemy import Boolean, Date, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WeekOffPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named set of week-off rules, e.g. 'Sundays + 2nd/4th Saturdays'.

    Employees without an explicit policy fall back to the default policy.
    """

    __tablename__ = "week_off_policies"
    __table_args__ = (
        # At most one default policy
        Index(
            "uq_week_off_policies_single_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    rules: Mapped[List["WeekOffRule"]] = relationship(
        back_populates="policy",
        cascade="all, delete-orphan",
        order_by="WeekOffRule.weekday",
        lazy="selectin",
    )


class WeekOffRule(UUIDPrimaryKeyMixin, Base):
    """A weekday that is off. weeks_of_month limits it to the nth occurrence(s)
    in the month, e.g. weekday=5 (Saturday), weeks_of_month=[2, 4]. NULL = every week."""

    __tablename__ = "week_off_rules"
    __table_args__ = (UniqueConstraint("policy_id", "weekday", name="uq_week_off_rule_policy_weekday"),)

    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("week_off_policies.id", ondelete="CASCADE"), index=True
    )
    # 0 = Monday ... 6 = Sunday (Python's date.weekday())
    weekday: Mapped[int] = mapped_column(SmallInteger)
    weeks_of_month: Mapped[Optional[List[int]]] = mapped_column(ARRAY(SmallInteger))

    policy: Mapped[WeekOffPolicy] = relationship(back_populates="rules")


class Holiday(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Company-wide holiday; applies to all employees."""

    __tablename__ = "holidays"

    date: Mapped[dt.date] = mapped_column(Date, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[Optional[str]] = mapped_column(Text)
