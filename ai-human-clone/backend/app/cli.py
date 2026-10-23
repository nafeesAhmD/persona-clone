"""Server-side administration commands (there is no HTTP endpoint that grants admin).

    docker compose exec backend python -m app.cli create-admin --email admin@example.com
    docker compose exec backend python -m app.cli create-admin --email existing@example.com --promote
    docker compose exec backend python -m app.cli list-admins
    docker compose exec backend python -m app.cli revoke-admin --email someone@example.com

Passwords are read with getpass (never echoed, never accepted as an argument, so
they don't end up in shell history or process lists).
"""

import argparse
import getpass
import sys

from pydantic import ValidationError
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import AdminAuditLog, User
from app.schemas.auth import RegisterRequest
from app.services import auth_service
from app.services.admin_bootstrap import admin_exists, grant_admin
from app.services.errors import ConflictError


def _find(db, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def _read_password() -> str:
    for _ in range(3):
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Repeat password: ")
        if first != second:
            print("Passwords don't match, try again.", file=sys.stderr)
            continue
        return first
    raise SystemExit("Too many attempts.")


def create_admin(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        if admin_exists(db) and not args.additional:
            print(
                "An administrator already exists. Use --additional to add another one on purpose.",
                file=sys.stderr,
            )
            return 2
        user = _find(db, args.email)
        if user is not None:
            if user.is_admin:
                print(f"{user.email} is already an administrator. Nothing changed.")
                return 0
            if not args.promote:
                print(
                    f"An account with {user.email} already exists. Use --promote to make it an administrator.",
                    file=sys.stderr,
                )
                return 2
            if not user.is_active:
                print("That account is disabled; reactivate it first.", file=sys.stderr)
                return 2
            grant_admin(db, user, "cli:promote")
            print(f"{user.email} is now an administrator.")
            return 0
        try:
            data = RegisterRequest(
                email=args.email,
                username=args.username or args.email.split("@")[0],
                full_name=args.name,
                password=_read_password(),
            )
        except ValidationError as exc:
            for err in exc.errors():
                print(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}", file=sys.stderr)
            return 2
        try:
            user = auth_service.register_user(db, data)
        except ConflictError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        grant_admin(db, user, "cli:create")
        print(f"Created administrator {user.email}.")
        return 0


def list_admins(_: argparse.Namespace) -> int:
    with SessionLocal() as db:
        admins = list(db.scalars(select(User).where(User.is_admin.is_(True)).order_by(User.created_at)))
        if not admins:
            print("No administrators yet.")
        for user in admins:
            print(f"{user.email}\t{'active' if user.is_active else 'disabled'}\t{user.created_at:%Y-%m-%d}")
    return 0


def revoke_admin(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        user = _find(db, args.email)
        if user is None or not user.is_admin:
            print("No administrator with that email.", file=sys.stderr)
            return 2
        others = db.scalar(
            select(func.count()).select_from(User).where(User.is_admin.is_(True), User.id != user.id)
        )
        if not others:
            print("Refusing to remove the last administrator.", file=sys.stderr)
            return 2
        user.is_admin = False
        db.add(
            AdminAuditLog(
                admin_user_id=user.id, action="ADMIN_REVOKED", target_type="user",
                target_id=str(user.id), details={"source": "cli"},
            )
        )
        db.commit()
        print(f"{user.email} is no longer an administrator.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-admin", help="Create an administrator (or promote an account)")
    create.add_argument("--email", required=True)
    create.add_argument("--username")
    create.add_argument("--name")
    create.add_argument("--promote", action="store_true", help="Make an existing account an administrator")
    create.add_argument("--additional", action="store_true", help="Allow adding another administrator")
    create.set_defaults(handler=create_admin)

    commands.add_parser("list-admins").set_defaults(handler=list_admins)

    revoke = commands.add_parser("revoke-admin", help="Remove the admin role (never the last one)")
    revoke.add_argument("--email", required=True)
    revoke.set_defaults(handler=revoke_admin)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
