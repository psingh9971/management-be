from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Tenant


def get_active_by_domain(db: Session, domain: str) -> Optional[Tenant]:
    stmt = select(Tenant).where(Tenant.domain == domain.lower(), Tenant.is_active.is_(True))
    return db.scalars(stmt).first()


def subdomain_from_host(host: str) -> Optional[str]:
    """Extract the tenant subdomain label from a host / origin.

    'demo.example.com' -> 'demo', 'https://demo.example.com:443' -> 'demo',
    'demo.localhost:5173' -> 'demo', 'example.com' / 'localhost' / an IP -> None.
    """
    host = host.strip().lower()
    if "://" in host:  # an Origin / URL rather than a bare host
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split(":", 1)[0].rstrip(".")
    if not host:
        return None
    labels = host.split(".")
    if all(label.isdigit() for label in labels):  # IPv4 address, no subdomain
        return None
    # 'x.localhost' has a subdomain with 2 labels; real domains need at least 3 ('x.example.com')
    min_labels = 2 if labels[-1] == "localhost" else 3
    if len(labels) < min_labels:
        return None
    return labels[0] or None
