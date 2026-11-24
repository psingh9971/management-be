"""Create a tenant's first super admin (the /users API itself requires a super admin).

Usage:
  # New tenant + its super admin
  python -m app.scripts.create_superadmin <username> --tenant acme --tenant-name "Acme Pvt. Ltd." [--tenant-domain acme]
  # Super admin for an existing tenant
  python -m app.scripts.create_superadmin <username> --tenant acme [--role admin] [--email x@y.com]

The password is prompted for, so it never lands in shell history.
"""
import argparse
import getpass
import re
import sys

from pydantic import ValidationError
from sqlalchemy import select

import app.models  # noqa: F401
from app.db.session import SessionLocal
from app.db.tenancy import set_tenant
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.repositories import user_repository
from app.schemas.user import UserCreate

_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a super admin user for a tenant")
    parser.add_argument("username")
    parser.add_argument("--tenant", required=True, help="Tenant slug, e.g. 'acme'")
    parser.add_argument("--tenant-name", help="Creates the tenant with this name if the slug doesn't exist yet")
    parser.add_argument("--tenant-address", help="Address printed on offer letters (new tenant only)")
    parser.add_argument("--tenant-domain", help="Subdomain, e.g. 'acme' for acme.<app domain> (new tenant only; default: the slug)")
    parser.add_argument("--role", choices=[r.value for r in UserRole], default=UserRole.ADMIN.value)
    parser.add_argument("--email")
    parser.add_argument("--full-name")
    args = parser.parse_args()

    slug = args.tenant.strip().lower()
    if not _SLUG.match(slug):
        sys.exit("--tenant must be lowercase letters, digits and hyphens (max 63 chars)")
    domain = (args.tenant_domain or slug).strip().lower()
    if not _SLUG.match(domain):
        sys.exit("--tenant-domain must be a single subdomain label: lowercase letters, digits and hyphens (max 63 chars)")

    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        sys.exit("Passwords do not match")

    try:
        data = UserCreate(
            username=args.username,
            password=password,
            role=args.role,
            email=args.email,
            full_name=args.full_name,
            is_super_admin=True,
        )
    except ValidationError as e:
        sys.exit(str(e))

    with SessionLocal() as db:
        tenant = db.scalars(select(Tenant).where(Tenant.slug == slug)).first()
        if tenant is None:
            if not args.tenant_name:
                sys.exit(f"Tenant '{slug}' does not exist; pass --tenant-name to create it")
            if db.scalar(select(Tenant.id).where(Tenant.domain == domain)):
                sys.exit(f"Domain '{domain}' is already used by another tenant")
            tenant = Tenant(slug=slug, domain=domain, name=args.tenant_name, address=args.tenant_address)
            db.add(tenant)
            db.flush()
            print(f"Created tenant '{tenant.name}' (slug={tenant.slug}, domain={tenant.domain}, id={tenant.id})")

        conflicts = user_repository.find_conflicts(db, data)
        if conflicts:
            sys.exit("; ".join(conflicts))
        set_tenant(db, tenant.id)
        user = user_repository.create_user(db, data)  # commits the tenant too
        print(f"Created super admin '{user.username}' (id={user.id}, role={user.role.value}, tenant={tenant.slug})")


if __name__ == "__main__":
    main()
