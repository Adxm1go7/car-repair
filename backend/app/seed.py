from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import make_engine
from app.demo_data import (
    DEMO_BAY_TYPES,
    DEMO_BAYS,
    DEMO_BREAKS,
    DEMO_GARAGE_CONTACT,
    DEMO_OPENING_HOURS,
    DEMO_SERVICES,
    DEMO_STAFF,
)
from app.models import Bay, BayType, OpeningHours, OpeningHoursBreak, Service, Setting, StaffUser
from app.staff.passwords import hash_password

DEFAULT_SETTINGS: Final[dict[str, Any]] = {
    "booking_window_days": 60,
    "booking_cutoff_minutes": 120,
    "slot_hold_minutes": 5,
    "payment_hold_minutes": 10,
    "free_cancellation_hours": 24,
    "reminder_hours_before": 48,
    "deposit_amount_pence": 2000,
    "garage_timezone": "Europe/London",
    "slot_grid_minutes": 30,
    "bay_buffer_minutes": 15,
    "garage_contact": DEMO_GARAGE_CONTACT,
}


def seed(session: Session, *, sample_accounts: bool = False) -> None:
    """Insert whatever is missing, never overwriting or re-creating data. The caller commits.

    `sample_accounts` adds the demo logins: never in production."""
    _seed_settings(session)
    _seed_catalogue(session)
    if sample_accounts:
        _seed_sample_accounts(session)


def _seed_sample_accounts(session: Session) -> None:
    existing = set(session.scalars(select(StaffUser.email)))
    for demo in DEMO_STAFF:
        if demo.email not in existing:  # checked first: hashing is deliberately slow
            session.execute(
                insert(StaffUser)
                .values(
                    name=demo.name,
                    email=demo.email,
                    role=demo.role,
                    password_hash=hash_password(demo.password),
                )
                .on_conflict_do_nothing(index_elements=["email"])
            )


def _seed_settings(session: Session) -> None:
    session.execute(
        insert(Setting)
        .values([{"key": key, "value": value} for key, value in DEFAULT_SETTINGS.items()])
        .on_conflict_do_nothing(index_elements=["key"])
    )


def _seed_catalogue(session: Session) -> None:
    session.execute(
        insert(BayType)
        .values([{"slug": slug, "name": name} for slug, name in DEMO_BAY_TYPES])
        .on_conflict_do_nothing(index_elements=["slug"])
    )
    bay_type_ids = dict(session.execute(select(BayType.slug, BayType.id)).tuples().all())

    session.execute(
        insert(Bay)
        .values(
            [
                {"slug": slug, "name": name, "bay_type_id": bay_type_ids[type_slug]}
                for slug, name, type_slug in DEMO_BAYS
            ]
        )
        .on_conflict_do_nothing(index_elements=["slug"])
    )

    session.execute(
        insert(Service)
        .values(
            [
                {
                    "slug": s.slug,
                    "name": s.name,
                    "category": s.category,
                    "description": s.description,
                    "duration_minutes": s.duration_minutes,
                    "price_from_pence": s.price_from_pence,
                    "price_to_pence": s.price_to_pence,
                    "required_bay_type_id": bay_type_ids[s.bay_type_slug],
                    "approval_mode": s.approval_mode,
                    "sort_order": index * 10,
                }
                for index, s in enumerate(DEMO_SERVICES)
            ]
        )
        .on_conflict_do_nothing(index_elements=["slug"])
    )

    # RETURNING gives only the days inserted by this run, so breaks are added
    # alongside a new day and never re-created after an admin removes them.
    new_weekdays = session.scalars(
        insert(OpeningHours)
        .values(
            [
                {
                    "weekday": weekday,
                    "open_time": hours[0] if hours else None,
                    "close_time": hours[1] if hours else None,
                }
                for weekday, hours in DEMO_OPENING_HOURS.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=["weekday"])
        .returning(OpeningHours.weekday)
    ).all()

    new_breaks = [
        {"weekday": weekday, "start_time": start, "end_time": end}
        for weekday in new_weekdays
        for start, end in DEMO_BREAKS.get(weekday, [])
    ]
    if new_breaks:
        session.execute(insert(OpeningHoursBreak).values(new_breaks))


def main() -> None:
    config = get_config()
    engine = make_engine(config.database_url)
    with Session(engine) as session:
        seed(session, sample_accounts=config.environment != "production")
        session.commit()
    engine.dispose()
    print("Seed complete")


if __name__ == "__main__":
    main()
