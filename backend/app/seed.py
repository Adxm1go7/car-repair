from typing import Final

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import make_engine
from app.models import Setting

DEFAULT_SETTINGS: Final[dict[str, int]] = {
    "booking_window_days": 60,
    "booking_cutoff_minutes": 120,
    "slot_hold_minutes": 10,
    "free_cancellation_hours": 24,
    "deposit_amount_pence": 2000,
}


def seed(session: Session) -> None:
    """Insert any missing default settings. Never overwrites existing values; the caller commits."""
    statement = (
        insert(Setting)
        .values([{"key": key, "value": value} for key, value in DEFAULT_SETTINGS.items()])
        .on_conflict_do_nothing(index_elements=["key"])
    )
    session.execute(statement)


def main() -> None:
    engine = make_engine(get_config().database_url)
    with Session(engine) as session:
        seed(session)
        session.commit()
    engine.dispose()
    print("Seed complete")


if __name__ == "__main__":
    main()
