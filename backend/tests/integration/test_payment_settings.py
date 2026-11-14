"""The payment settings load within their bounds, or the endpoints that need them give 503."""

from collections.abc import Callable

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Setting
from app.repositories.availability import (
    SettingsUnavailable,
    load_deposit_pence,
    load_free_cancellation_hours,
    load_payment_hold_minutes,
)
from app.seed import seed

Loader = Callable[[Session], int]
LOADERS: list[tuple[str, Loader, int]] = [
    ("payment_hold_minutes", load_payment_hold_minutes, 10),
    ("deposit_amount_pence", load_deposit_pence, 2000),
    ("free_cancellation_hours", load_free_cancellation_hours, 24),
]
BAD: list[tuple[str, Loader, object]] = [
    ("payment_hold_minutes", load_payment_hold_minutes, 0),
    ("payment_hold_minutes", load_payment_hold_minutes, 26),
    ("deposit_amount_pence", load_deposit_pence, 29),
    ("deposit_amount_pence", load_deposit_pence, 100001),
    ("free_cancellation_hours", load_free_cancellation_hours, -1),
    ("free_cancellation_hours", load_free_cancellation_hours, 8761),
    *[(key, loader, value) for key, loader, _ in LOADERS for value in (True, "10")],
]


def set_value(session: Session, key: str, value: object) -> None:
    session.execute(update(Setting).where(Setting.key == key).values(value=value))
    session.flush()


@pytest.mark.parametrize(("key", "loader", "expected"), LOADERS)
def test_seeded_value_loads(db_session: Session, key: str, loader: Loader, expected: int) -> None:
    seed(db_session)
    assert loader(db_session) == expected


@pytest.mark.parametrize(("key", "loader", "value"), BAD)
def test_out_of_range_or_wrong_type_is_unavailable(
    db_session: Session, key: str, loader: Loader, value: object
) -> None:
    seed(db_session)
    set_value(db_session, key, value)
    with pytest.raises(SettingsUnavailable):
        loader(db_session)
