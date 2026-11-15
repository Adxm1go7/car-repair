# Milestone 6: Email and Booking Links — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Customers get confirmation, reminder and cancellation emails, and a private link that lets them view their booking and cancel it inside the free-cancellation window.

**Architecture:** Emails are rows in `email_log`, written in the same transaction as the change that causes them. The worker sends due rows through an `EmailSender` (SMTP to Mailpit), creating a fresh `booking_links` token for each email that carries a link, and queues reminders itself. Two POST endpoints (view, cancel) take the token in the body. A React page at `/booking/:reference#t=<token>` uses them.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, Jinja2 (new), `smtplib`, React + TypeScript + Vitest, Playwright, Mailpit.

**Spec:** [docs/superpowers/specs/2026-11-14-milestone-6-email-self-service-design.md](../specs/2026-11-14-milestone-6-email-self-service-design.md). Read it before starting. This plan doesn't repeat its reasons.

## Global Constraints

- Customers **cannot reschedule**. No reschedule endpoint, button, template or copy.
- A plain link token is never stored (database, `email_log`, logs) and never sent in a URL path or query. Only in the `#t=` fragment and in POST bodies.
- Every email is queued with `queue_email` inside the caller's transaction. No API route sends mail. Nothing here commits except the routes and the worker.
- Garage name, address, phone and email come from the `garage_contact` setting (backend) or `/api/garage` (frontend). Never hardcoded.
- Times in emails and the page are garage-local (`garage_timezone`).
- Settings: `reminder_hours_before` = 48 (new). Existing: `free_cancellation_hours` = 24.
- Link expiry: booking `end_at` + 7 days. Retry delays: 1, 5, 15, 60 minutes. Attempt limit: 5.
- Commit messages are `area - what` (for example `backend - email_log and booking_links tables`).
- Backend checks before each commit: `uv run pytest -v`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` (in `backend/`). Frontend: `npm run lint`, `npm run typecheck`, `npm test` (in `frontend/`).
- All DB access goes through a `Session` from `get_session` (routes) or the worker's session. No `garage_id`.

## Review Focus

1. **A customer name or note containing `<`, `&` or quotes** shows literally in the HTML email and isn't escaped in the plain text. Pinned in Task 2 (`test_html_escapes_customer_text`).
2. **A mangled link**: `#t=` missing or empty, the token cut short by an email client, or an absurdly long token. The page shows the safe message and the API returns 404, never a 422 or 500. Pinned in Task 7 (`test_view_with_oversized_token_is_404`) and Task 8 (`shows the invalid-link message when the fragment is missing`).
3. **A visit just after a clock change** (Sun 28 Mar 2027 09:00 BST): the email and the "free until" time show local time, not UTC. Pinned in Task 2 (`test_times_are_garage_local_across_clock_change`).
4. **SMTP down or one bad address**: the worker keeps cycling, one failing row doesn't stop the others in the same batch, and nothing is lost. Pinned in Task 5 (`test_one_failure_does_not_block_the_batch`).
5. **Cancel pressed twice** (double click, two tabs): exactly one refund and one cancellation email, and the second request gets 409. Pinned in Task 7 (`test_cancel_twice_refunds_once`).

---

## File map

| File | Responsibility |
| --- | --- |
| `backend/migrations/versions/0007_create_email_and_links.py` | New tables |
| `backend/app/models/email.py` | `EmailLog` model and its status/template tuples |
| `backend/app/models/booking_link.py` | `BookingLink` model |
| `backend/app/email/message.py` | `OutgoingEmail`, `EmailTemplate` |
| `backend/app/email/sender.py` | `EmailSender` protocol, `SmtpSender`, `EmailUnavailable` |
| `backend/app/email/render.py` + `templates/` | Jinja2 rendering of the three emails |
| `backend/app/email/queue.py` | `queue_email` |
| `backend/app/email/outbox.py` | `send_due_emails`, retry rule, "still applies" rule |
| `backend/app/email/reminders.py` | `queue_due_reminders` |
| `backend/app/bookings/links.py` | Create and look up booking links |
| `backend/app/bookings/self_service.py` | View and cancel from a link |
| `backend/app/api/my_booking.py` | `POST /api/bookings/{reference}/view` and `/cancel` |
| `frontend/src/manage/` | The booking page, its API calls and types |
| `e2e/tests/self-service.spec.ts`, `e2e/tests/mailpit.ts` | Flow 4 end to end |

---

### Task 1: Tables, models and the reminder setting

**Files:**
- Create: `backend/migrations/versions/0007_create_email_and_links.py`, `backend/app/models/email.py`, `backend/app/models/booking_link.py`
- Modify: `backend/app/models/__init__.py` (export both), `backend/app/seed.py` (`DEFAULT_SETTINGS`), `backend/app/repositories/availability.py`
- Test: `backend/tests/integration/test_email_constraints.py`, `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Produces:
  - `EMAIL_TEMPLATES = ("confirmation", "reminder", "cancellation")` and `EMAIL_STATUSES = ("queued", "sent", "failed", "skipped")` in `app/models/email.py`.
  - `EmailLog`: `id`, `template: str`, `booking_id: int | None` (FK bookings), `recipient: str` (String 254), `status: str` (default `"queued"`), `attempts: int` (default 0), `next_attempt_at: datetime` (server default now), `last_error: str | None` (String 500), `created_at`, `sent_at: datetime | None`, `booking` relationship. Check constraints on template and status. Index `(status, next_attempt_at)`. Partial unique index `uq_email_log_one_reminder` on `booking_id` where `template = 'reminder'`.
  - `BookingLink`: `id`, `booking_id` (FK bookings), `token_hash: str` (String 64, unique), `expires_at: datetime`, `created_at`, `booking` relationship.
  - `load_reminder_hours_before(session) -> int` (bounds 1 to 365 × 24).
  - `DEFAULT_SETTINGS["reminder_hours_before"] = 48`.

- [ ] **Step 1: Write failing tests.** In `test_email_constraints.py`, using `make_hold(..., status="confirmed")` from `factories.py`:
  - `test_second_reminder_for_a_booking_is_rejected`: two `EmailLog(template="reminder", booking_id=b.id, ...)` → `IntegrityError` on flush.
  - `test_reminders_for_different_bookings_are_allowed`, and `test_reminder_and_confirmation_for_one_booking_coexist`.
  - `test_unknown_template_or_status_is_rejected` (`template="reschedule"` → `IntegrityError`).
  - `test_link_token_hash_is_unique`.
  - `test_seed_adds_reminder_hours_before` (`load_reminder_hours_before(session) == 48` after `seed`).

  In `test_migrations.py`, add `test_upgrade_head_creates_email_tables` (both table names in the inspector) and `test_downgrade_to_0006_drops_email_tables`. The existing `test_models_match_migrations` covers drift.
- [ ] **Step 2: Run them and see them fail.** `cd backend; uv run pytest tests/integration/test_email_constraints.py tests/integration/test_migrations.py -v` → errors importing `EmailLog`.
- [ ] **Step 3: Implement** the two models, migration `0007` (revises `0006`, constraint lists copied into the migration as in `0006`), the setting and the loader.
- [ ] **Step 4: Run the tests and see them pass.** Same command → all PASS. Then run the full backend checks (Global Constraints).
- [ ] **Step 5: Commit.** `git add backend; git commit -m "backend - email_log and booking_links tables, reminder setting"`

---

### Task 2: Messages, sender and templates

**Files:**
- Create: `backend/app/email/__init__.py`, `message.py`, `sender.py`, `render.py`, `templates/{confirmation,reminder,cancellation}.{txt,html}.j2`, `templates/_layout.html.j2`
- Modify: `backend/pyproject.toml` (`uv add jinja2`), `backend/tests/fakes.py` (add `FakeSender`)
- Test: `backend/tests/unit/test_render_email.py`, `backend/tests/integration/test_smtp_sender.py`

**Interfaces:**
- Produces:
  - `EmailTemplate = Literal["confirmation", "reminder", "cancellation"]`
  - `@dataclass(frozen=True) class OutgoingEmail: to: str; subject: str; text: str; html: str`
  - `class EmailUnavailable(Exception)`
  - `class EmailSender(Protocol): def send(self, message: OutgoingEmail) -> None` (raises `EmailUnavailable` on any SMTP or socket error)
  - `SmtpSender(host: str, port: int, from_address: str)`
  - `@dataclass(frozen=True) class EmailContext: reference: str; customer_name: str; start: datetime; end: datetime; zone: ZoneInfo; services: list[str]; registration: str; make: str; model: str; deposit_status: str; deposit_pence: int; free_cancellation_until: datetime; garage: dict[str, str]; link_url: str | None`
  - `render_email(template: EmailTemplate, to: str, context: EmailContext) -> OutgoingEmail`
  - `FakeSender` (tests): `sent: list[OutgoingEmail]`, `fail_for: set[str]` (recipients whose send raises `EmailUnavailable`), `fail: bool`.

Copy fixed by the spec:
- Subjects: `Your booking is confirmed — {reference}`, `See you on {weekday day month} — {reference}`, `Your booking is cancelled — {reference}`.
- Confirmation and reminder include "You can cancel free of charge until {free_cancellation_until}. After that, please call us on {phone}." and the link. The reminder says this only if that time is still in the future at render time. Otherwise it says "To change or cancel, please call us on {phone}".
- Cancellation, by `deposit_status`: `refund_pending`/`refunded` → "Your £20 deposit is being refunded."; `refund_failed` → "We'll be in touch about your refund."; `paid` → "Your deposit has been kept, as the booking was cancelled less than 24 hours before."; `waived` → no deposit line. It always ends with "To book again, please call us on {phone}."
- Every email has the garage name, address and phone in its footer.

- [ ] **Step 1: Write failing unit tests** in `test_render_email.py` with a hand-built `EmailContext`:
  - `test_confirmation_has_link_and_free_cancellation_time` (the text contains `link_url` and `"until Thu 19 Nov, 09:00"`)
  - `test_html_escapes_customer_text` (`customer_name="<b>Sam & Co</b>"` → the HTML contains `&lt;b&gt;Sam &amp; Co&lt;/b&gt;`, the text contains it verbatim)
  - `test_times_are_garage_local_across_clock_change` (start `2027-03-28T08:00Z`, zone Europe/London → "09:00")
  - `test_cancellation_wording_per_deposit_status` (parametrised over the 5 statuses above)
  - `test_reminder_after_window_says_call` (`free_cancellation_until` in the past → no "free of charge")
  - `test_no_garage_details_hardcoded` (render with a garage named "Test Garage" and phone "000" → both appear, and "Hillside" doesn't)
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_render_email.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** `message.py`, `render.py` (a Jinja2 `Environment` with `PackageLoader("app.email")`, `autoescape` on for `.html.j2` only, a `local` filter formatting like "Thu 19 Nov, 09:00") and the templates. Inline CSS only.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Write failing test** `test_smtp_sender.py::test_sends_to_a_real_smtp_server`. Start a local `aiosmtpd` controller, or a testcontainers `axllent/mailpit:v1.21` and read `GET /api/v1/messages`: the builder picks one, and mailpit is preferred because it's already in Compose. Then `SmtpSender(...).send(msg)` → one message with that subject, a text part and an HTML part. Also `test_unreachable_server_raises_email_unavailable` (port with nothing listening).
- [ ] **Step 6: Implement `SmtpSender`** with `smtplib.SMTP(host, port, timeout=10)` and an `email.message.EmailMessage` with `set_content(text)` and `add_alternative(html, subtype="html")`. Wrap `(smtplib.SMTPException, OSError)` as `EmailUnavailable`. Add `FakeSender` to `fakes.py`.
- [ ] **Step 7: Run** both test files → PASS. Run the full backend checks.
- [ ] **Step 8: Commit.** `git commit -m "backend - email sender and templates"`

---

### Task 3: Queue the confirmation on every confirm

**Files:**
- Create: `backend/app/email/queue.py`
- Modify: `backend/app/payments/service.py` (`_confirm`)
- Test: `backend/tests/integration/test_queue_email.py`

**Interfaces:**
- Consumes: `EmailLog`, `EmailTemplate`.
- Produces: `queue_email(session: Session, template: EmailTemplate, booking: Booking) -> EmailLog`. It adds a `queued` row with `recipient=booking.customer_email` (raises `ValueError` if it's None) and `next_attempt_at` = now (server default), then flushes and doesn't commit.
- Changes: `_confirm(session: Session, booking: Booking, now: datetime) -> None` now also calls `queue_email(session, "confirmation", booking)`. Update its two callers in `complete_deposit`.

- [ ] **Step 1: Write failing tests**, reusing the setup from `test_complete_deposit.py` (a `make_hold` with details plus `make_deposit`, `FakeProvider.mark_paid`):
  - `test_paying_a_held_booking_queues_one_confirmation`
  - `test_late_payment_that_gets_its_time_back_queues_one_confirmation`
  - `test_late_payment_refunded_queues_nothing`
  - `test_completing_twice_queues_once` (call `complete_deposit` twice)
  - `test_rolled_back_confirm_leaves_no_email` (use a nested `session.begin_nested()`, roll it back, and count `EmailLog` rows = 0)
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_queue_email.py -v` → FAIL.
- [ ] **Step 3: Implement** `queue_email` and the `_confirm` change.
- [ ] **Step 4: Run** this file plus `test_complete_deposit.py`, `test_stripe_webhook.py`, `test_demo_payments_api.py` and `test_hold_status_api.py` → PASS. Then the full backend checks.
- [ ] **Step 5: Commit.** `git commit -m "backend - queue a confirmation email when a deposit confirms a booking"`

---

### Task 4: Booking links

**Files:**
- Create: `backend/app/bookings/links.py`
- Test: `backend/tests/integration/test_booking_links.py`

**Interfaces:**
- Consumes: `BookingLink`; `new_hold_token`, `hash_token` from `app/bookings/rules.py`; `get_booking_for_update_by_id` from `app/repositories/bookings.py`.
- Produces:
  - `LINK_VALID_AFTER_END = timedelta(days=7)`
  - `create_link(session: Session, booking: Booking) -> str`. It inserts a row with `expires_at = booking.end_at + LINK_VALID_AFTER_END`, flushes and returns the plain token.
  - `find_linked_booking(session: Session, reference: str, token: str, now: datetime, *, lock: bool = False) -> Booking | None`. It returns None if the token is longer than 100 characters, the hash is unknown, the link has expired (`expires_at <= now`) or the booking's reference ≠ `reference`. With `lock=True`, the booking is loaded with `get_booking_for_update_by_id`.

- [ ] **Step 1: Write failing tests**: `test_new_link_opens_its_booking`; `test_two_links_for_one_booking_both_work`; `test_expired_link_is_none` (now = end + 7 days exactly → None, one second before → booking); `test_wrong_token_is_none`; `test_link_for_another_reference_is_none`; `test_only_the_hash_is_stored` (no `BookingLink` column equals the plain token); `test_oversized_token_is_none` (500 characters).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_booking_links.py -v` → FAIL.
- [ ] **Step 3: Implement** `links.py`.
- [ ] **Step 4: Run** → PASS. Then the full backend checks.
- [ ] **Step 5: Commit.** `git commit -m "backend - booking links stored as hashes"`

---

### Task 5: The worker sends queued email

**Files:**
- Create: `backend/app/email/outbox.py`
- Modify: `backend/app/config.py`, `backend/app/worker.py`, `docker-compose.yml` (worker env: `SMTP_HOST: mailpit`, `SMTP_PORT: "1025"`, `SMTP_FROM`, `PUBLIC_BASE_URL: ${PUBLIC_BASE_URL:-http://localhost:8080}`, `EMAIL_INTERVAL_SECONDS: ${EMAIL_INTERVAL_SECONDS:-5}`)
- Test: `backend/tests/integration/test_outbox.py`, `backend/tests/unit/test_outbox_rules.py`

**Interfaces:**
- Consumes: `render_email`, `EmailContext`, `EmailSender`, `EmailUnavailable`, `create_link`, `load_policy`, `load_free_cancellation_hours`, `get_setting(session, "garage_contact")`, `paid_deposit`.
- Produces:
  - `AppConfig` gains `smtp_host: str = "localhost"`, `smtp_port: int = 1025`, `smtp_from: str = "bookings@example.test"`, `public_base_url: str = "http://localhost:8080"`, `email_interval_seconds: int = Field(default=5, ge=1)`.
  - `RETRY_DELAYS: tuple[timedelta, ...] = (1, 5, 15, 60 minutes)`, `MAX_ATTEMPTS = 5`.
  - `next_attempt_delay(attempts: int) -> timedelta` (pure: attempt 1 → 1 min, … attempt 4 and later → 60 min).
  - `email_still_applies(template: EmailTemplate, booking_status: str) -> bool` (pure: confirmation or reminder → `"confirmed"`; cancellation → `"cancelled"`).
  - `link_url(base_url: str, reference: str, token: str) -> str` → `f"{base_url.rstrip('/')}/booking/{reference}#t={token}"`.
  - `send_due_emails(session: Session, sender: EmailSender, now: datetime, base_url: str, batch: int = 20) -> int`. It returns how many were sent.

Per row, oldest `next_attempt_at` first, selected `status='queued' AND next_attempt_at <= now` with `FOR UPDATE SKIP LOCKED`, and committed one row at a time:
  1. The booking's status no longer applies → `status="skipped"`, commit.
  2. Otherwise, for confirmation or reminder, `create_link`. Build the `EmailContext` (`free_cancellation_until = start_at − free_cancellation_hours`) and `render_email`, then `sender.send`.
  3. Success → `status="sent"`, `sent_at=now`, commit.
  4. `EmailUnavailable` → `session.rollback()` (which drops the link), then re-load the row: `attempts += 1`, `last_error = str(error)[:500]`, and either `status="failed"` (attempts ≥ `MAX_ATTEMPTS`, logged with `log.error`) or `next_attempt_at = now + next_attempt_delay(attempts)`. Commit.

  The worker loop wakes every `email_interval_seconds` and runs `send_due_emails` every tick (Task 6 adds `queue_due_reminders` just before it). It runs the existing `run_once` whenever `worker_interval_seconds` have passed since its last run. Each step is wrapped in its own try/except that logs and carries on.

- [ ] **Step 1: Write failing unit tests** in `test_outbox_rules.py`: `test_retry_delays` (attempts 1, 2, 3, 4, 9 → 1, 5, 15, 60, 60 minutes); `test_email_still_applies` (table of template × status); `test_link_url_puts_token_in_fragment` (`"http://x/"` → `"http://x/booking/ABCD-EFGH#t=tok"`).
- [ ] **Step 2: Write failing integration tests** in `test_outbox.py` with `FakeSender`, a seeded session and a confirmed booking with a queued confirmation:
  - `test_sends_and_marks_sent` (one message to `sam@example.com`, row `sent`, `sent_at` set, one `BookingLink`)
  - `test_sent_link_opens_the_booking` (pull the token out of `sent[0].text` and check `find_linked_booking` returns the booking)
  - `test_not_due_yet_is_left` (`next_attempt_at` in the future → nothing sent)
  - `test_failure_backs_off_then_fails` (`fail=True`: after 1 call, attempts=1 and `next_attempt_at=now+1min` with no link row; after 5 due calls, `status="failed"`)
  - `test_one_failure_does_not_block_the_batch` (two rows, `fail_for={"first@example.com"}` → the second is sent)
  - `test_cancelled_booking_confirmation_is_skipped` (status `skipped`, nothing sent)
  - `test_cancellation_email_has_no_link`
- [ ] **Step 3: Run** `uv run pytest tests/unit/test_outbox_rules.py tests/integration/test_outbox.py -v` → FAIL.
- [ ] **Step 4: Implement** `outbox.py`, the config fields, the worker loop and the Compose env.
- [ ] **Step 5: Run** → PASS. Then the full backend checks, including the existing `test_worker*`/`test_hold_expiry.py`.
- [ ] **Step 6: Check it by hand.** `docker compose up --build -d`, book and pay in demo mode at http://localhost:8080, then open Mailpit at http://localhost:8025. The confirmation is there within about 5 seconds, and its link opens `/booking/...` (the page itself comes in Task 8, so a blank page is fine for now).
- [ ] **Step 7: Commit.** `git commit -m "worker - send queued email with retries"`

---

### Task 6: Reminders

**Files:**
- Create: `backend/app/email/reminders.py`
- Modify: `backend/app/worker.py` (call it before `send_due_emails`)
- Test: `backend/tests/integration/test_reminders.py`

**Interfaces:**
- Consumes: `queue_email`, `load_reminder_hours_before`.
- Produces: `queue_due_reminders(session: Session, now: datetime, hours_before: int) -> int`. It queues a reminder for each booking with `status='confirmed'`, `start_at - hours_before <= now < start_at`, `confirmed_at < start_at - hours_before` and no reminder row (`NOT EXISTS`). Each insert is guarded: an `IntegrityError` on `uq_email_log_one_reminder` inside `begin_nested()` is ignored. It returns the count and doesn't commit.

- [ ] **Step 1: Write failing tests** (start = `2026-11-20 09:00Z`, confirmed 5 days before): `test_queued_once_inside_the_window` (now = start − 47h → 1; calling again → 0; exactly one row); `test_not_yet` (now = start − 49h → 0); `test_booked_inside_48_hours_gets_none` (`confirmed_at` = start − 30h); `test_cancelled_gets_none`; `test_after_start_gets_none`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_reminders.py -v` → FAIL.
- [ ] **Step 3: Implement** it and wire it into the worker tick, reading the setting each tick.
- [ ] **Step 4: Run** → PASS. Then the full backend checks.
- [ ] **Step 5: Commit.** `git commit -m "worker - queue reminders 48 hours before"`

---

### Task 7: View and cancel endpoints

**Files:**
- Create: `backend/app/bookings/self_service.py`, `backend/app/api/my_booking.py`
- Modify: `backend/app/api/holds.py` (rename `_summary` → `booking_summary`, so it can be shared), `backend/app/main.py` (include the router), `backend/app/bookings/rules.py`
- Test: `backend/tests/unit/test_cancel_rule.py`, `backend/tests/integration/test_my_booking_api.py`

**Interfaces:**
- Consumes: `find_linked_booking`, `cancel_booking` (`payments/service.py`), `queue_email`, `load_free_cancellation_hours`, `booking_summary`.
- Produces:
  - `customer_can_cancel(status: str, start_at: datetime, now: datetime, free_cancellation_hours: int) -> bool` in `bookings/rules.py`: `status == "confirmed" and deposit_refundable(start_at, now, hours, "customer")`.
  - In `self_service.py`: `class LinkNotValid(Exception)`; `class CancelRefused(Exception)` with `reason: Literal["too_late", "not_cancellable"]`; `cancel_from_link(session, provider, reference, token, now) -> Booking`. It locks via `find_linked_booking(..., lock=True)`. Not confirmed → `CancelRefused("not_cancellable")`; outside the window → `CancelRefused("too_late")`. Otherwise it calls `cancel_booking(..., by="customer", free_cancellation_hours=...)` then `queue_email(session, "cancellation", booking)`. `PaymentUnavailable` propagates.
  - `POST /api/bookings/{reference}/view` with body `{"token": str}`, where `token` is a plain `str` so oversized values reach the lookup and get 404, not 422. It returns `MyBookingOut`: `summary: BookingSummaryOut`, `deposit_status: str`, `can_cancel: bool`, `refund_if_cancelled: bool` (`can_cancel and deposit_status == "paid"`), `free_cancellation_until: str` (garage-local ISO). Errors: 404 `"This link isn't valid"`, 503 when settings are unavailable.
  - `POST /api/bookings/{reference}/cancel`, same body → `MyBookingOut` after the cancel. Errors: 404; 409 with `detail` exactly `"too_late"` or `"not_cancellable"`; 503 `"We couldn't cancel just now"` on `PaymentUnavailable` (rolled back).

- [ ] **Step 1: Write failing unit tests** for `customer_can_cancel`: exactly 24h before → True, 24h − 1s → False, status `cancelled` → False.
- [ ] **Step 2: Write failing API tests** with `api_client`, `fake_provider` and a confirmed paid booking plus `create_link`:
  - `test_view_shows_booking_and_can_cancel`
  - `test_view_inside_window_cannot_cancel`
  - `test_view_with_wrong_expired_or_other_reference_token_is_404` (parametrised)
  - `test_view_with_oversized_token_is_404` (5000 characters)
  - `test_cancel_refunds_and_queues_cancellation` (status cancelled, `deposit_status` `refund_pending`, one refund call, one `cancellation` row)
  - `test_cancel_inside_window_is_409_too_late_and_changes_nothing`
  - `test_cancel_twice_refunds_once` (second → 409 `not_cancellable`, `len(fake_provider.called("refund")) == 1`, one cancellation row)
  - `test_cancel_when_refund_unavailable_is_503_and_changes_nothing` (`fake_provider.fail_calls={"refund"}` → booking still confirmed, reservation active, no email row)
- [ ] **Step 3: Run** `uv run pytest tests/unit/test_cancel_rule.py tests/integration/test_my_booking_api.py -v` → FAIL.
- [ ] **Step 4: Implement** it. Commit or roll back in the route, like `holds.py`.
- [ ] **Step 5: Run** → PASS. Then the full backend checks (the `holds.py` rename must keep its tests green).
- [ ] **Step 6: Commit.** `git commit -m "api - view and cancel a booking from its link"`

---

### Task 8: The booking page

**Files:**
- Create: `frontend/src/manage/types.ts`, `frontend/src/manage/api.ts`, `frontend/src/manage/ManageBookingPage.tsx`, `frontend/src/manage/ManageBookingPage.test.tsx`
- Modify: `frontend/src/App.tsx` (route `/booking/:reference` with `garage={state.catalogue.garage}`), `frontend/src/booking/BookedPage.tsx` (a line: "We've emailed you a link to view or cancel your booking."), `frontend/src/App.css` if needed
- Test: as above, plus `frontend/src/booking/BookedPage.test.tsx` for the new line

**Interfaces:**
- Consumes: the Task 7 endpoints; `Garage` (`catalogue/types.ts`); `formatLongDate`, `formatTimeRange` (`booking/format.ts`); the `Result` and `request` pattern from `booking/api.ts` (export `request`/`post` from there rather than copying them).
- Produces:
  - `type MyBooking = { summary: BookingSummary; deposit_status: string; can_cancel: boolean; refund_if_cancelled: boolean; free_cancellation_until: string }`
  - `viewBooking(reference, token): Promise<Result<MyBooking> | { ok: false; kind: 'invalid' }>` (404 → invalid)
  - `cancelBooking(reference, token): Promise<Result<MyBooking> | { ok: false; kind: 'invalid' } | { ok: false; kind: 'refused'; reason: 'too_late' | 'not_cancellable' } | { ok: false; kind: 'unavailable' }>` (409 → refused with the detail as reason, 503 → unavailable)
  - `ManageBookingPage({ garage }: { garage: Garage })`. It reads `t` from `location.hash` (`new URLSearchParams(hash.slice(1)).get('t')`). With no token, it shows the invalid message without fetching.

Copy (exact, from the design): the invalid message "This link isn't valid any more. Please call us on {phone}."; "Need a different time? Call us on {phone} and we'll sort it out."; inside the window "To change or cancel, please call us on {phone}."; confirm text "Cancel your booking on {date} at {time}?" + (only if `refund_if_cancelled`) "You'll get your £20 deposit back." + "If you just need a different time, please call us on {phone} instead and we can move it for you." Buttons "Yes, cancel it" / "Keep my booking". On 503: "We couldn't cancel just now. Please try again, or call us on {phone}." Cancelled state: "This booking is cancelled" plus by `deposit_status`: "Your deposit refund is on its way" / "Your deposit has been refunded" / "We'll be in touch about your refund" / "Your deposit was kept". No "book again" button anywhere. The deposit amount comes from `summary.deposit_paid_pence` via `formatPrice`, not a literal £20.

- [ ] **Step 1: Write failing tests** (mock `fetch` as the existing tests do):
  - `shows the invalid-link message when the fragment is missing` (and `fetch` not called)
  - `shows the invalid-link message on 404`
  - `shows the booking with a cancel button when can_cancel`
  - `shows only the call line inside the window`
  - `cancel asks first, then shows the refund on its way`
  - `keep my booking closes the dialog without a request`
  - `shows the try-again message on 503 and keeps the booking`
  - `a 409 too_late shows the call line`
  - `no reschedule or book-again wording appears` (`queryByText(/reschedule|book again/i)` is null in every state)
- [ ] **Step 2: Run** `cd frontend; npm test -- ManageBookingPage` → FAIL.
- [ ] **Step 3: Implement** it. The confirm step is in-page (`role="alertdialog"` with a labelled heading), and focus moves to it and back.
- [ ] **Step 4: Run** `npm test`, `npm run lint`, `npm run typecheck` → all pass.
- [ ] **Step 5: Check it by hand.** With Compose up, book in demo mode, open the link from the Mailpit email, cancel, then refresh: it shows the cancelled state. A second email ("Your booking is cancelled") arrives in Mailpit.
- [ ] **Step 6: Commit.** `git commit -m "frontend - booking page from the emailed link"`

---

### Task 9: Flow 4 end to end, spec and docs

**Files:**
- Create: `e2e/tests/mailpit.ts`, `e2e/tests/self-service.spec.ts`
- Modify: `docs/SPEC.md` (the edits listed in the design's "Change to the spec"), `README.md` (Mailpit at http://localhost:8025 shows the emails; new env vars), `.github/workflows/ci.yml` only if Mailpit's port needs exposing (it's already mapped in Compose)

**Interfaces:**
- Produces, in `mailpit.ts`: `MAILPIT_URL = process.env.MAILPIT_URL ?? 'http://localhost:8025'`; `waitForEmail(request: APIRequestContext, to: string, subject: RegExp, timeoutMs = 30_000): Promise<{ text: string; html: string }>`. It polls `GET /api/v1/search?query=to:"<to>"`, then `GET /api/v1/message/{ID}`, returning `Text` and `HTML`.

- [ ] **Step 1: Write the test** `flow 4: cancel from the emailed link`:
  - Use a unique address, `sam+${Date.now()}@example.com`.
  - Book MOT test as in `instant-booking.spec.ts`, but skip day buttons until the day is at least 2 days after today (London), so the cancel button shows. Move `payInStripe` and the day picker into a shared `e2e/tests/booking.ts` instead of copying them.
  - `waitForEmail(..., /Your booking is confirmed/)`, then pull the link with `/https?:\/\/\S+\/booking\/[A-Z2-9-]+#t=\S+/`, and `page.goto` it.
  - Expect the reference, the "Need a different time? Call us on" line and the **Cancel booking** button. Click it, check the dialog text, then "Yes, cancel it".
  - Expect "This booking is cancelled" and `/refund is on its way|has been refunded/`.
  - `waitForEmail(..., /Your booking is cancelled/)` and expect the text to contain "being refunded".
  - Check that availability for that day contains the start time again.
- [ ] **Step 2: Write** `a made-up link fails safely`: `page.goto('/booking/ABCD-EFGH#t=nope')` → "This link isn't valid any more", and no cancel button.
- [ ] **Step 3: Run locally** with the stack up and Stripe test keys in `.env`: `cd e2e; npm test` → both new tests and flow 1 pass.
- [ ] **Step 4: Update `docs/SPEC.md` and `README.md`.** In SPEC's checklist, tick "Token links are random, hashed in storage, expiring, and limited to one booking" and "Email sending is retried, logged, and never blocks a booking from completing".
- [ ] **Step 5: Commit.** `git commit -m "e2e - flow 4 cancel from the emailed link; spec drops customer rescheduling"`
- [ ] **Step 6: Push and open the PR.** CI's backend, frontend and compose checks must all be green before merging.
