"""Create (or promote) an administrator account.

Usage:
    python -m app.commands.create_admin --email admin@example.com --full-name "Admin"
The password is read from the ADMIN_PASSWORD environment variable or prompted for.
"""

import argparse
import asyncio
import getpass
import os
import sys

from pydantic import ValidationError

from app.core.exceptions import ConflictError
from app.db.session import SessionFactory, engine
from app.models.user import UserRole
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate
from app.services.user import UserService


async def create_admin(email: str, full_name: str, password: str) -> int:
    async with SessionFactory() as session:
        existing = await UserRepository(session).get_by_email(email)
        if existing is not None:
            if existing.role == UserRole.ADMIN:
                print(f"User {email} is already an administrator.")
                return 0
            await UserRepository(session).update(existing, {"role": UserRole.ADMIN})
            await session.commit()
            print(f"Promoted existing user {email} to administrator.")
            return 0

        try:
            data = UserCreate(email=email, full_name=full_name, password=password)
        except ValidationError as exc:
            print(f"Invalid input: {exc}", file=sys.stderr)
            return 1
        try:
            user = await UserService(session).create(data, role=UserRole.ADMIN)
        except ConflictError as exc:
            print(exc.message, file=sys.stderr)
            return 1
        print(f"Created administrator {user.email} (id={user.id}).")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", default="Administrator")
    args = parser.parse_args()

    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")

    async def run() -> int:
        try:
            return await create_admin(args.email, args.full_name, password)
        finally:
            await engine.dispose()

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
