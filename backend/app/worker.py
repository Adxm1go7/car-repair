"""Background worker: queues reminders and sends queued email, releases expired holds,
closes the payment forms of released ones, and once a day blanks customer details older than
12 months (app/privacy/retention.py).

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
from collections.abc import Callable
from datetime import datetime
from types import FrameType

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import AppConfig, get_config
from app.db import make_engine
from app.email.outbox import send_due_emails
from app.email.reminders import queue_due_reminders
from app.email.sender import DemoInboxSender, EmailSender, SmtpSender
from app.limits import delete_old_counts
from app.logs import configure_logging
from app.payments.deps import make_provider
from app.payments.provider import PaymentProvider, PaymentUnavailable
from app.payments.service import close_open_deposit
from app.privacy.retention import RETENTION_INTERVAL, remove_old_details
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


def run_once(session: Session, now: datetime, provider: PaymentProvider) -> dict[str, int]:
    """Release every hold expired at `now`, commit, then close their payment forms. Also
    clears out expired staff sessions, old login attempts and old request counts. Returns how
    many of each were dealt with."""
    counts = {
        "holds_released": release_expired_holds(session, now),
        "sessions_deleted": delete_expired_sessions(session, now),
        "login_attempts_deleted": delete_old_attempts(session, now),
        "request_counts_deleted": delete_old_counts(session, now),
    }
    session.commit()
    counts["checkouts_closed"] = close_stale_checkouts(session, provider, now)
    return counts


def run_job(job: str, work: Callable[[], int | dict[str, int]]) -> None:
    """Run one step of the worker loop and log one line if it did anything. A dict result
    counts its first value and logs every value. A failure is logged, not raised, so one
    broken step (a mail server down) never stops the others."""
    started = time.perf_counter()
    try:
        result = work()
    except Exception:
        log.exception("job failed", extra={"job": job})
        return
    fields = result if isinstance(result, dict) else {}
    count = next(iter(result.values()), 0) if isinstance(result, dict) else result
    if count > 0 or any(fields.values()):
        log.info(
            "job finished",
            extra={
                "job": job,
                "count": count,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                **fields,
            },
        )


def queue_reminders(engine: Engine) -> int:
    with Session(engine) as session:
        now = utc_now()
        queued = queue_due_reminders(session, now, load_reminder_hours_before(session))
        session.commit()
    return queued


def make_sender(config: AppConfig, session: Session) -> EmailSender:
    """The live demo keeps emails in its Demo inbox; everywhere else they go out by SMTP."""
    if config.demo_site:
        return DemoInboxSender(session)
    return SmtpSender(config.smtp_host, config.smtp_port, config.smtp_from)


def send_emails(engine: Engine, config: AppConfig) -> int:
    with Session(engine) as session:
        sender = make_sender(config, session)
        return send_due_emails(session, sender, utc_now(), config.public_base_url)


def remove_details(engine: Engine) -> int:
    with Session(engine) as session:
        return remove_old_details(session, utc_now())


def release_holds(engine: Engine, config: AppConfig) -> dict[str, int]:
    with Session(engine) as session:
        return run_once(session, utc_now(), make_provider(config, session))


def main() -> None:
    configure_logging()
    config = get_config()
    engine = make_engine(config.database_url)
    stop = threading.Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    log.info(
        "worker started: email every %d seconds, holds every %d seconds, payments: %s, emails: %s",
        config.email_interval_seconds,
        config.worker_interval_seconds,
        config.payment_provider,
        "demo inbox" if config.demo_site else "smtp",
    )
    last_holds_run: float | None = None
    last_retention_run: float | None = None
    try:
        while not stop.is_set():
            # Each step on its own, so a broken mail server never stops holds being released.
            run_job("reminders", lambda: queue_reminders(engine))
            run_job("email", lambda: send_emails(engine, config))
            due = last_holds_run is None or (
                time.monotonic() - last_holds_run >= config.worker_interval_seconds
            )
            if due:
                last_holds_run = time.monotonic()
                run_job("holds", lambda: release_holds(engine, config))
            if last_retention_run is None or (
                time.monotonic() - last_retention_run >= RETENTION_INTERVAL.total_seconds()
            ):
                last_retention_run = time.monotonic()
                run_job("retention", lambda: remove_details(engine))
            stop.wait(config.email_interval_seconds)
    finally:
        engine.dispose()
        log.info("worker stopped")


if __name__ == "__main__":
    main()
