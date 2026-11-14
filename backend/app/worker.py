"""Background worker: releases expired holds, and closes the payment forms of released ones.

Availability already ignores expired holds, so releasing is housekeeping: it makes the
database say what the rule already means. Closing the forms matters more: until it's done,
a customer who left could still pay for a time that's been given back. Run with
`python -m app.worker`.
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
from app.payments.deps import make_provider
from app.payments.provider import PaymentProvider, PaymentUnavailable
from app.payments.service import close_open_deposit
from app.repositories.bookings import get_booking_for_update_by_id, release_expired_holds
from app.repositories.payments import stale_open_deposits

log = logging.getLogger("app.worker")


def close_stale_checkouts(session: Session, provider: PaymentProvider, now: datetime) -> int:
    """Close each payment form still open for a booking that is no longer held, committing
    one at a time. A form the provider can't close now is left for the next cycle. If a
    payment got in first, it's completed instead (booked, or refunded if the time has gone).
    Returns how many were dealt with."""
    handled = 0
    for deposit_id, booking_id in [(d.id, d.booking_id) for d in stale_open_deposits(session)]:
        try:
            booking = get_booking_for_update_by_id(session, booking_id)
            if booking is not None:
                close_open_deposit(session, provider, booking, now)
            session.commit()
            handled += 1
        except PaymentUnavailable:
            session.rollback()
            log.warning("couldn't close payment %d; trying again next time", deposit_id)
    return handled


def run_once(session: Session, now: datetime, provider: PaymentProvider) -> int:
    """Release every hold expired at `now`, commit, then close their payment forms.
    Returns how many holds were released."""
    released = release_expired_holds(session, now)
    session.commit()
    close_stale_checkouts(session, provider, now)
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

    log.info(
        "worker started, every %d seconds, payments: %s",
        config.worker_interval_seconds,
        config.payment_provider,
    )
    try:
        while not stop.is_set():
            try:
                with Session(engine) as session:
                    released = run_once(session, utc_now(), make_provider(config, session))
                if released > 0:
                    log.info("released %d expired holds", released)
            except Exception:
                log.exception("the worker's cycle failed; trying again next time")
            stop.wait(config.worker_interval_seconds)
    finally:
        engine.dispose()
        log.info("worker stopped")


if __name__ == "__main__":
    main()
