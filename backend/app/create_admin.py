"""Create the garage's first admin and print a link for them to set their password.

    uv run python -m app.create_admin --name "Alex Admin" --email alex@example.com

The link is printed rather than emailed, so setup doesn't depend on mail working, and only
one token is ever made. It works once, for 72 hours.
"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bookings.rules import clean_email, clean_name
from app.clock import utc_now
from app.config import get_config
from app.db import make_engine
from app.models import StaffUser
from app.staff.audit import record_audit
from app.staff.links import issue_password_token, set_password_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create the first admin account.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    try:
        name = clean_name(args.name)
        email = clean_email(args.email)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    config = get_config()
    engine = make_engine(config.database_url)
    try:
        with Session(engine) as session:
            if session.scalars(select(StaffUser).where(StaffUser.email == email)).first():
                print(f"An account for {email} already exists", file=sys.stderr)
                return 1
            now = utc_now()
            user = StaffUser(name=name, email=email, role="admin")
            session.add(user)
            session.flush()
            record_audit(
                session,
                None,
                "staff.invite",
                "staff_user",
                user.id,
                after={"name": name, "email": email, "role": "admin", "active": True},
                now=now,
            )
            token = issue_password_token(session, user, "invite", now)
            session.commit()
    finally:
        engine.dispose()
    print(f"Set the password within 72 hours: {set_password_url(config.public_base_url, token)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
