"""Background worker: releases expired holds every few seconds.

Availability already ignores expired holds, so this is housekeeping: it makes the
database say what the rule already means. Run with `python -m app.worker`.
"""

import logging
import signal
import threading
from datetime import datetime
from types import FrameType

from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import get_config
from app.db import make_engine
from app.repositories.bookings import release_expired_holds

log = logging.getLogger("app.worker")


def run_once(session: Session, now: datetime) -> int:
    """Release every hold expired at `now`, commit, and say how many."""
    released = release_expired_holds(session, now)
    session.commit()
    return released


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = get_config()
    engine = make_engine(config.database_url)
    stop = threading.Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    log.info("worker started, every %d seconds", config.worker_interval_seconds)
    try:
        while not stop.is_set():
            try:
                with Session(engine) as session:
                    released = run_once(session, utc_now())
                if released > 0:
                    log.info("released %d expired holds", released)
            except Exception:
                log.exception("releasing expired holds failed; trying again next time")
            stop.wait(config.worker_interval_seconds)
    finally:
        engine.dispose()
        log.info("worker stopped")


if __name__ == "__main__":
    main()
