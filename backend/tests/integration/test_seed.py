from alembic import command
from conftest import alembic_config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import Setting
from app.seed import seed


def test_seed_inserts_default_policy_settings(db_session: Session) -> None:
    seed(db_session)
    rows = {s.key: s.value for s in db_session.scalars(select(Setting))}
    assert rows == {
        "booking_window_days": 60,
        "booking_cutoff_minutes": 120,
        "slot_hold_minutes": 10,
        "free_cancellation_hours": 24,
        "deposit_amount_pence": 2000,
    }


def test_seed_twice_creates_no_duplicates(db_session: Session) -> None:
    seed(db_session)
    seed(db_session)
    assert db_session.scalar(select(func.count()).select_from(Setting)) == 5


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
        assert session.scalar(select(func.count()).select_from(Setting)) == 5
