from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
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
from app.models import (
    Bay,
    BayType,
    OpeningHours,
    OpeningHoursBreak,
    Service,
    Setting,
    StaffUser,
    Timetable,
)
from app.models.catalogue import FIRST_TIMETABLE_STARTS
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
    "approval_hold_hours": 48,
    "approval_payment_hours": 24,
    "approval_lead_hours": 24,
    "approval_min_payment_hours": 2,
    "garage_contact": DEMO_GARAGE_CONTACT,
}


def sample_accounts_wanted(config: AppConfig) -> bool:
    """The demo logins: everywhere except production, and on the live demo site."""
    return config.environment != "production" or config.demo_site


def seed(session: Session, *, sample_accounts: bool = False) -> None:
    """Insert whatever is missing, never overwriting or re-creating data. The caller commits.

    `sample_accounts` adds the demo logins: in production only on the demo site."""
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

    # The demo week is the first timetable, which every later one follows.
    session.execute(
        insert(Timetable)
        .values(starts_on=FIRST_TIMETABLE_STARTS)
        .on_conflict_do_nothing(index_elements=["starts_on"])
    )
    first = session.scalars(
        select(Timetable.id).where(Timetable.starts_on == FIRST_TIMETABLE_STARTS)
    ).one()

    # RETURNING gives only the days inserted by this run, so breaks are added
    # alongside a new day and never re-created after an admin removes them.
    new_weekdays = session.scalars(
        insert(OpeningHours)
        .values(
            [
                {
                    "timetable_id": first,
                    "weekday": weekday,
                    "open_time": hours[0] if hours else None,
                    "close_time": hours[1] if hours else None,
                }
                for weekday, hours in DEMO_OPENING_HOURS.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=["timetable_id", "weekday"])
        .returning(OpeningHours.weekday)
    ).all()

    new_breaks = [
        {"timetable_id": first, "weekday": weekday, "start_time": start, "end_time": end}
        for weekday in new_weekdays
        for start, end in DEMO_BREAKS.get(weekday, [])
    ]
    if new_breaks:
        session.execute(insert(OpeningHoursBreak).values(new_breaks))


def main() -> None:
    config = get_config()
    engine = make_engine(config.database_url)
    with Session(engine) as session:
        seed(session, sample_accounts=sample_accounts_wanted(config))
        session.commit()
    engine.dispose()
    print("Seed complete")


if __name__ == "__main__":
    main()
