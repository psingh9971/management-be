from typing import Optional

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A company using the application. Every business record belongs to exactly one tenant."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200))
    # URL-safe identifier, e.g. 'acme'. Sent by attendance devices in the X-Tenant header.
    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    # Subdomain label the tenant's frontend is served on, e.g. 'acme' -> acme.<app domain>.
    # Lowercase DNS label (letters, digits, hyphens; max 63 chars).
    domain: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    # Printed on offer letters
    address: Mapped[Optional[str]] = mapped_column(Text)
    # Inactive tenants can't log in or receive punches
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
