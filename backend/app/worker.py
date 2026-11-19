"""Background worker: queues reminders and sends queued email, releases expired holds, and
closes the payment forms of released ones.

Availability already ignores expired holds, so releasing is housekeeping: it makes the
database say what the rule already means. Closing the forms matters more: until it's done,
a customer who left could still pay for a time that's been given back.

Email is checked every `email_interval_seconds`, holds every `worker_interval_seconds`.
Run with `python -m app.worker`.
"""

import logging
import signal
import threading
import time
from datetime import datetime
from types import FrameType

from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import get_config
from app.db import make_engine
from app.email.outbox import send_due_emails
from app.email.reminders import queue_due_reminders
from app.email.sender import SmtpSender
from app.limits import delete_old_counts
from app.payments.deps import make_provider
from app.payments.provider import PaymentProvider, PaymentUnavailable
from app.payments.service import close_open_deposit
from app.repositories.availability import load_reminder_hours_before
from app.repositories.bookings import get_booking_for_update_by_id, release_expired_holds
from app.repositories.payments import stale_open_deposits
from app.settings.lock import lock_shared
from app.staff.sessions import delete_expired_sessions
from app.staff.throttle import delete_old_attempts

log = logging.getLogger("app.worker")


def close_stale_checkouts(session: Session, provider: PaymentProvider, now: datetime) -> int:
    """Close each payment form still open for a booking that is no longer held, committing
    one at a time. A form the provider can't close now is left for the next cycle. If a
    payment got in first, it's completed instead (booked, or refunded if the time has gone).
    Returns how many were dealt with."""
    handled = 0
    for deposit_id, booking_id in [(d.id, d.booking_id) for d in stale_open_deposits(session)]:
        try:
            # Closing may complete a payment: the shared lock first, then the row, as there.
            lock_shared(session)
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
    """Release every hold expired at `now`, commit, then close their payment forms. Also
    clears out expired staff sessions and old login attempts. Returns how many holds were
    released."""
    released = release_expired_holds(session, now)
    delete_expired_sessions(session, now)
    delete_old_attempts(session, now)
    delete_old_counts(session, now)
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

    sender = SmtpSender(config.smtp_host, config.smtp_port, config.smtp_from)
    log.info(
        "worker started: email every %d seconds, holds every %d seconds, payments: %s",
        config.email_interval_seconds,
        config.worker_interval_seconds,
        config.payment_provider,
    )
    last_holds_run: float | None = None
    try:
        while not stop.is_set():
            # Each step on its own, so a broken mail server never stops holds being released.
            try:
                with Session(engine) as session:
                    now = utc_now()
                    reminders = queue_due_reminders(
                        session, now, load_reminder_hours_before(session)
                    )
                    session.commit()
                if reminders > 0:
                    log.info("queued %d reminders", reminders)
            except Exception:
                log.exception("queueing reminders failed; trying again next time")
            try:
                with Session(engine) as session:
                    sent = send_due_emails(session, sender, utc_now(), config.public_base_url)
                if sent > 0:
                    log.info("sent %d emails", sent)
            except Exception:
                log.exception("sending email failed; trying again next time")
            due = last_holds_run is None or (
                time.monotonic() - last_holds_run >= config.worker_interval_seconds
            )
            if due:
                last_holds_run = time.monotonic()
                try:
                    with Session(engine) as session:
                        released = run_once(session, utc_now(), make_provider(config, session))
                    if released > 0:
                        log.info("released %d expired holds", released)
                except Exception:
                    log.exception("the worker's cycle failed; trying again next time")
            stop.wait(config.email_interval_seconds)
    finally:
        engine.dispose()
        log.info("worker stopped")


if __name__ == "__main__":
    main()
