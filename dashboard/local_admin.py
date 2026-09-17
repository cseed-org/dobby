"""Run with python -m dashboard.local_admin USERNAME [--email EXISTING_GOOGLE_EMAIL]."""
import argparse
import asyncio
from getpass import getpass
import re

from sqlalchemy import delete, select

from .database import SessionLocal, engine
from .models import Session, User
from .passwords import hash_password


async def save_admin(username: str, password_hash: str, email: str | None = None):
    async with SessionLocal() as db, db.begin():
        user = (await db.execute(select(User).where(User.local_username == username))).scalar_one_or_none()
        if email:
            linked = (await db.execute(select(User).where(User.uw_email == email))).scalar_one_or_none()
            if linked is None:
                raise ValueError("No existing user with that Google email")
            if user is not None and user.id != linked.id:
                raise ValueError("Username already belongs to a different user")
            if linked.local_username not in (None, username):
                raise ValueError("That user already has a different local username")
            user = linked
        if user is None:
            user = User(display_name=username, local_username=username, role="admin")
            db.add(user)
        else:
            await db.execute(delete(Session).where(Session.user_id == user.id))
        user.local_username = username
        user.password_hash = password_hash
        user.role = "admin"


def main():
    parser = argparse.ArgumentParser(description="Create/reset a local admin; passwords are prompted securely")
    parser.add_argument("username")
    parser.add_argument("--email", help="Attach credentials to an existing Google user")
    args = parser.parse_args()
    username = args.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,64}", username):
        parser.error("Username must be 3-64 letters, digits, dots, underscores or hyphens")
    password = getpass("Password (12-256 characters): ")
    if password != getpass("Confirm password: "):
        parser.error("Passwords do not match")

    async def run():
        try:
            await save_admin(username, hash_password(password), args.email)
        finally:
            await engine.dispose()

    try:
        asyncio.run(run())
    except ValueError as error:
        parser.error(str(error))
    print(f"Local admin '{username}' is ready. Existing sessions for this user were revoked.")


if __name__ == "__main__":
    main()
