from alembic import command
from conftest import alembic_config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import Base, Bay, BayType, OpeningHours, OpeningHoursBreak, Service, Setting
from app.seed import seed

CATALOGUE_MODELS: tuple[type[Base], ...] = (
    BayType,
    Bay,
    Service,
    OpeningHours,
    OpeningHoursBreak,
)
# bay types, bays, services, opening-hours days, breaks
DEMO_COUNTS = [2, 4, 10, 7, 5]


def count(session: Session, model: type[Base]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def catalogue_counts(session: Session) -> list[int]:
    return [count(session, model) for model in CATALOGUE_MODELS]


def service_by_slug(session: Session, slug: str) -> Service:
    return session.scalars(select(Service).where(Service.slug == slug)).one()


# --- settings -----------------------------------------------------------------


def test_seed_inserts_default_settings(db_session: Session) -> None:
    seed(db_session)
    rows = {s.key: s.value for s in db_session.scalars(select(Setting))}
    assert rows == {
        "booking_window_days": 60,
        "booking_cutoff_minutes": 120,
        "slot_hold_minutes": 5,
        "payment_hold_minutes": 10,
        "free_cancellation_hours": 24,
        "deposit_amount_pence": 2000,
        "garage_timezone": "Europe/London",
        "slot_grid_minutes": 30,
        "bay_buffer_minutes": 15,
        "garage_contact": {
            "name": "Hillside Motors",
            "address": "12 Station Road, Anytown, AT1 2CD",
            "phone": "01632 960123",
            "email": "bookings@example.com",
        },
    }


def test_seed_twice_creates_no_duplicate_settings(db_session: Session) -> None:
    seed(db_session)
    seed(db_session)
    assert count(db_session, Setting) == 10


def test_seed_keeps_admin_edited_value(db_session: Session) -> None:
    seed(db_session)
    setting = db_session.get(Setting, "slot_hold_minutes")
    assert setting is not None
    setting.value = 15
    db_session.flush()
    seed(db_session)
    db_session.expire_all()
    edited = db_session.get(Setting, "slot_hold_minutes")
    assert edited is not None
    assert edited.value == 15


def test_upgrade_head_on_seeded_database_keeps_data(fresh_database_url: str) -> None:
    cfg = alembic_config(fresh_database_url)
    command.upgrade(cfg, "head")
    with Session(make_engine(fresh_database_url)) as session:
        seed(session)
        session.commit()
    command.upgrade(cfg, "head")
    with Session(make_engine(fresh_database_url)) as session:
        assert count(session, Setting) == 10
        assert catalogue_counts(session) == DEMO_COUNTS


# --- catalogue ----------------------------------------------------------------


def test_seed_inserts_demo_catalogue(db_session: Session) -> None:
    seed(db_session)
    assert catalogue_counts(db_session) == DEMO_COUNTS

    mot = service_by_slug(db_session, "mot-test")
    assert (mot.duration_minutes, mot.price_from_pence, mot.price_to_pence) == (60, 5485, None)
    assert mot.required_bay_type.slug == "mot"

    clutch = service_by_slug(db_session, "clutch-replacement")
    assert (clutch.price_from_pence, clutch.price_to_pence, clutch.approval_mode) == (
        45000,
        75000,
        "needs_approval",
    )

    monday = db_session.get(OpeningHours, 0)
    assert monday is not None
    assert [(b.start_time.isoformat(), b.end_time.isoformat()) for b in monday.breaks] == [
        ("12:30:00", "13:00:00")
    ]


def test_seed_twice_keeps_catalogue_counts(db_session: Session) -> None:
    seed(db_session)
    seed(db_session)
    assert catalogue_counts(db_session) == DEMO_COUNTS


def test_seed_keeps_edited_service_price(db_session: Session) -> None:
    seed(db_session)
    service_by_slug(db_session, "mot-test").price_from_pence = 4999
    db_session.flush()
    seed(db_session)
    db_session.expire_all()
    assert service_by_slug(db_session, "mot-test").price_from_pence == 4999


def test_seed_keeps_deactivated_service_inactive(db_session: Session) -> None:
    seed(db_session)
    service_by_slug(db_session, "full-service").active = False
    db_session.flush()
    seed(db_session)
    db_session.expire_all()
    assert service_by_slug(db_session, "full-service").active is False


def test_seed_does_not_recreate_deleted_break(db_session: Session) -> None:
    seed(db_session)
    monday = db_session.get(OpeningHours, 0)
    assert monday is not None
    monday.breaks.clear()
    db_session.flush()
    seed(db_session)
    db_session.expire_all()
    monday = db_session.get(OpeningHours, 0)
    assert monday is not None
    assert monday.breaks == []
    assert count(db_session, OpeningHoursBreak) == 4
