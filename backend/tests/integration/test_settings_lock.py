"""The hours-and-bays lock: booking writes (shared) take turns with settings changes (exclusive)."""

import threading
import time

from sqlalchemy.orm import Session

from app.db import make_engine
from app.settings.lock import lock_exclusive, lock_shared

HOLD_FOR = 0.5  # seconds the first transaction keeps its lock


def hold_lock(url: str, take: str, locked: threading.Event, log: list[str]) -> None:
    with Session(make_engine(url)) as session:
        (lock_shared if take == "shared" else lock_exclusive)(session)
        locked.set()
        time.sleep(HOLD_FOR)
        log.append(f"{take} done")
        session.commit()  # ends the transaction, so the lock goes


def test_exclusive_waits_for_shared(migrated_url: str) -> None:
    locked, log = threading.Event(), list[str]()
    booking = threading.Thread(target=hold_lock, args=(migrated_url, "shared", locked, log))
    booking.start()
    assert locked.wait(timeout=10)
    with Session(make_engine(migrated_url)) as session:
        started = time.monotonic()
        lock_exclusive(session)
        waited = time.monotonic() - started
        log.append("exclusive got it")
        session.commit()
    booking.join(timeout=10)
    assert log == ["shared done", "exclusive got it"]
    assert waited >= HOLD_FOR * 0.8


def test_shared_locks_do_not_wait_for_each_other(migrated_url: str) -> None:
    locked, log = threading.Event(), list[str]()
    first = threading.Thread(target=hold_lock, args=(migrated_url, "shared", locked, log))
    first.start()
    assert locked.wait(timeout=10)
    with Session(make_engine(migrated_url)) as session:
        started = time.monotonic()
        lock_shared(session)
        waited = time.monotonic() - started
        session.commit()
    first.join(timeout=10)
    assert waited < HOLD_FOR / 2
