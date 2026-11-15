"""Create the first user (there is no public sign-up).

    python -m app.utils.seed --username admin --role admin

The password is read from the OTMS_SEED_PASSWORD environment variable or asked for.
"""
import argparse
import getpass
import os

from app.core.database import Base, SessionLocal, engine
from app.models.models import RoleEnum
from app.services.auth_service import AuthService, DuplicateUserError


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an OTMS user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", default="admin", choices=[r.value for r in RoleEnum])
    args = parser.parse_args()

    password = os.environ.get("OTMS_SEED_PASSWORD") or getpass.getpass("Password (min 8 chars): ")
    if len(password) < 8:
        raise SystemExit("Password must be at least 8 characters")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = AuthService(db).create_user(args.username, password, args.role)
        print(f"Created {user.role.value} user '{user.username}' (id {user.user_id})")
    except DuplicateUserError:
        raise SystemExit(f"User '{args.username}' already exists")
    finally:
        db.close()


if __name__ == "__main__":
    main()
