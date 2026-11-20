"""Create the first super admin (the /users API itself requires a super admin).

Usage:  python -m app.scripts.create_superadmin <username> [--role admin] [--email x@y.com]
The password is prompted for, so it never lands in shell history.
"""
import argparse
import getpass
import sys

from pydantic import ValidationError

import app.models  # noqa: F401
from app.db.session import SessionLocal
from app.models.user import UserRole
from app.repositories import user_repository
from app.schemas.user import UserCreate


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a super admin user")
    parser.add_argument("username")
    parser.add_argument("--role", choices=[r.value for r in UserRole], default=UserRole.ADMIN.value)
    parser.add_argument("--email")
    parser.add_argument("--full-name")
    args = parser.parse_args()

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
        conflicts = user_repository.find_conflicts(db, data)
        if conflicts:
            sys.exit("; ".join(conflicts))
        user = user_repository.create_user(db, data)
        print(f"Created super admin '{user.username}' (id={user.id}, role={user.role.value})")


if __name__ == "__main__":
    main()
