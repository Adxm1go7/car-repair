# Milestone 5: Deposit Payments — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The customer pays a £20 deposit in Stripe's embedded form on the booking page, and the booking is confirmed only when the server has seen the money arrive. Late payments end as a booking or a refund. The refund and the cancellation rule are built for Milestones 6 and 7. Flow 1 passes end to end in CI through the real Stripe test form.

**Architecture:** A `PaymentProvider` interface in `app/payments/` hides Stripe (`StripeProvider`), demo mode (`DemoProvider`) and the tests' `FakeProvider`. One function, `complete_deposit`, is the only path to a paid booking; the webhook, the status poll, the demo endpoint, `DELETE /api/holds/…` and the worker all call it. `payments` and `payment_events` tables make every money step idempotent. The frontend gains a third booking step, `paying`, which shows Stripe's Embedded Checkout (or the demo box) and polls the server.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, pytest + Testcontainers, the `stripe` Python package. React 19 + TypeScript, Vitest + RTL, `@stripe/stripe-js` and `@stripe/react-stripe-js`. Playwright, the Stripe CLI in CI.

**Spec:** [docs/superpowers/specs/2026-11-14-milestone-5-deposit-payments-design.md](../specs/2026-11-14-milestone-5-deposit-payments-design.md). It builds on [docs/SPEC.md](../../SPEC.md) and the [Milestone 4 design](../specs/2026-11-12-milestone-4-booking-flow-design.md). Read the design first: messages, response shapes and the order of steps in `complete_deposit` are defined there and are not repeated in full here.

## Global Constraints

- Work on branch `milestone5-deposit-payments`; merge via PR. `main` needs the `backend`, `frontend` and `compose` CI checks.
- Commit messages are in the style `area - what`. The user runs the tests and commits; the plan's commit steps are the commands to give them.
- Nothing reads the real clock except `app.clock.utc_now` and the worker's loop. Everything else takes `now`.
- Settings, never hardcoded: `payment_hold_minutes` (1–25, default 10), `deposit_amount_pence` (30–100000, default 2000), `free_cancellation_hours` (0–8760, default 24), `slot_hold_minutes` as before. Missing or invalid → 503 where needed.
- Only `complete_deposit` sets a booking `confirmed` or a deposit `paid`, and only after `provider.get_checkout` says paid.
- Stripe idempotency keys: `deposit-<booking reference>-<n>` (n = number of earlier deposit rows for the booking) and `refund-<deposit session id>-<n>` (n = number of earlier refund rows for that deposit). Not row ids: Stripe keeps keys per account for 24 hours, and a fresh database sharing the account (every CI run) would reuse `deposit-1-0` and be refused with an IdempotencyError.
- The secret key and webhook secret never appear in responses, logs, fixtures, the frontend or the repository. Only the publishable key is sent to the page.
- Only `app/payments/stripe_provider.py` imports `stripe` (plus the webhook signature check in `app/api/stripe_webhook.py`).
- Every 422 body is `{"detail": "<string>"}`. Times in responses are garage-local ISO strings with an offset.
- New dependencies: `stripe` (backend), `@stripe/stripe-js`, `@stripe/react-stripe-js` (frontend). Pin versions at least two weeks old.
- Backend gates: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`. Frontend gates: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`. Run Vitest from PowerShell, not Git Bash.
- Write files with the Edit/Write tools, or Python with `encoding="utf-8", newline="\n"` (Windows defaults corrupt them).
- `playground/` is untracked and must not be touched or committed.

## Review Focus

1. **Payment completing while the hold is released** (`DELETE`, worker or countdown at the same moment): the booking ends confirmed or refunded, never charged with nothing. Covered by `test_delete_when_payment_got_in_confirms` (Task 5) and `test_worker_completes_a_deposit_that_got_in` (Task 7).
2. **The webhook arriving twice, or after the poll already confirmed**: one confirmation, no second refund. Covered by `test_duplicate_event_changes_nothing` and `test_webhook_after_poll_confirmed_is_harmless` (Task 6).
3. **A late payment for a time someone else now holds**: exactly one refund, even if completion runs twice. Covered by `test_late_payment_time_taken_refunds_once` (Task 4).
4. **Double tap on "Continue to payment"**: one Stripe session, hold not extended twice. Covered by `test_repeat_checkout_returns_same_session` (Task 5) and the busy button (Task 8).
5. **The countdown hitting zero just after a payment got in**: the customer sees the booked page, not "you haven't been charged". Covered by `countdown end after a payment got in shows the booked page` (Task 9).

---

### Task 1: Payment settings and configuration

**Files:**
- Modify: `backend/app/seed.py`, `backend/app/repositories/availability.py`, `backend/app/config.py`, `backend/app/main.py`, `docker-compose.yml`, `.env.example`
- Test: `backend/tests/unit/test_config.py`, `backend/tests/integration/test_seed.py`, `backend/tests/integration/test_payment_settings.py` (new)

**Interfaces:**
- Produces: `DEFAULT_SETTINGS["payment_hold_minutes"] = 10`. In `app/repositories/availability.py`: `load_payment_hold_minutes(session) -> int` (1–25), `load_deposit_pence(session) -> int` (30–100000), `load_free_cancellation_hours(session) -> int` (0–8760), each raising `SettingsUnavailable`. `AppConfig` gains `stripe_secret_key: str = ""`, `stripe_publishable_key: str = ""`, `stripe_webhook_secret: str = ""` and a property `payment_provider -> Literal["stripe", "demo"]` (`"stripe"` iff `stripe_secret_key` is non-empty). `create_app` stores `app.state.config = config`.

- [ ] **Step 1: Write the failing tests**
  - `test_config.py`: `test_provider_is_demo_without_a_key`, `test_provider_is_stripe_with_a_key`, `test_production_without_a_stripe_key_is_refused` (`AppConfig(database_url=…, environment="production")` raises `ValidationError`), `test_stripe_key_needs_publishable_key` (secret set, publishable empty → `ValidationError`).
  - `test_seed.py`: the expected settings dict gains `"payment_hold_minutes": 10`.
  - `test_payment_settings.py`: for each loader, the seeded value loads; parametrised out-of-range values (`0`, `26` for the hold; `29`, `100001` for the deposit; `-1` for the hours), `true` and `"10"` raise `SettingsUnavailable`.
- [ ] **Step 2: Run them** — `uv run pytest tests/unit/test_config.py tests/integration/test_seed.py tests/integration/test_payment_settings.py -v`. Expected: FAIL (missing names, missing key).
- [ ] **Step 3: Implement** the loaders with the existing `_int_setting`, the config fields and a `model_validator(mode="after")` for the two refusals, and the seed key. In `docker-compose.yml` pass `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` (each `${NAME:-}`) to both `api` and `worker`, and give `worker` `restart: unless-stopped`. In `.env.example` add the three keys, blank, with a comment pointing at `docs/stripe-setup.md` and saying blank means demo mode. The API logs `payment provider: stripe|demo` once at startup (in `lifespan`), never a key.
- [ ] **Step 4: Run the whole backend suite** — `uv run pytest`. Expected: PASS.
- [ ] **Step 5: Commit**

```powershell
git add backend docker-compose.yml .env.example
git commit -m "backend - payment settings and stripe configuration"
```

---

### Task 2: Payments tables

**Files:**
- Create: `backend/app/models/payment.py`, `backend/migrations/versions/0006_create_payments.py`
- Modify: `backend/app/models/booking.py`, `backend/app/models/__init__.py`, `backend/tests/factories.py`
- Test: `backend/tests/integration/test_payment_constraints.py` (new), `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Produces: `Booking.deposit_status: Mapped[str]` (server default `'unpaid'`), `DEPOSIT_STATUSES = ("unpaid", "paid", "refund_pending", "refunded", "refund_failed", "waived")`. `Payment` model with the design's columns plus `refund_of: Mapped[int | None]` (FK → `payments.id`), relationship `Payment.booking`. `PaymentEvent` model (`provider`, `event_id` composite PK, `type`, `received_at`). `factories.make_deposit(session, booking, *, ref="cs_test_1", status="open", amount_pence=2000, provider="stripe") -> Payment`. `make_hold(..., status="confirmed")` now also sets `deposit_status="paid"`.

- [ ] **Step 1: Write the failing tests** (each flushes and expects `IntegrityError` unless said)
  - `test_open_deposit_can_be_stored` (no error), `test_unknown_deposit_status_is_rejected`, `test_confirmed_booking_needs_a_paid_or_waived_deposit` (confirmed + `unpaid`), `test_one_open_deposit_per_booking`, `test_provider_ref_is_unique`, `test_amount_must_be_positive`, `test_refund_needs_refund_of`, `test_deposit_status_must_suit_kind` (deposit with `succeeded`), `test_one_live_refund_per_deposit` (two `pending` refunds of one deposit), `test_failed_refund_allows_another` (a `failed` then a `pending` refund: no error), `test_event_ids_are_unique`.
  - `test_migrations.py`: `test_0006_waives_existing_confirmed_bookings` — upgrade to `0005`, insert a confirmed booking (with its reservation) by SQL, upgrade to `0006`, its `deposit_status` is `waived`; downgrade to `0005` drops `payments` and `payment_events` and the column.
- [ ] **Step 2: Run them** — `uv run pytest tests/integration/test_payment_constraints.py tests/integration/test_migrations.py -v`. Expected: FAIL (ImportError / missing revision).
- [ ] **Step 3: Implement** models and migration `0006` (down revision `0005`, same style). Constraint names (the naming convention adds prefixes): on bookings `deposit_status_valid`, `confirmed_has_deposit` (`status <> 'confirmed' OR deposit_status IN ('paid','waived')`); on payments `kind_valid`, `status_suits_kind` (`(kind = 'deposit' AND refund_of IS NULL AND status IN ('open','paid','expired')) OR (kind = 'refund' AND refund_of IS NOT NULL AND status IN ('pending','succeeded','failed'))`), `amount_positive`, unique `(provider, provider_ref)`, partial unique indexes `ux_payments_one_open_deposit` on `booking_id` where `kind = 'deposit' AND status = 'open'` and `ux_payments_one_live_refund` on `refund_of` where `kind = 'refund' AND status <> 'failed'`. The upgrade adds the column with the default, then `UPDATE bookings SET deposit_status = 'waived' WHERE status = 'confirmed'`, then the checks.
- [ ] **Step 4: Run the whole backend suite** — `uv run pytest`. Expected: PASS (existing confirm tests still pass because `confirm_hold` isn't removed until Task 5; if a confirm test fails on `confirmed_has_deposit`, set `deposit_status = "waived"` in `confirm_hold` for now and note it — Task 5 deletes it).
- [ ] **Step 5: Commit**

```powershell
git add backend
git commit -m "backend - payments tables and deposit status"
```

---

### Task 3: Payment providers

**Files:**
- Create: `backend/app/payments/__init__.py`, `backend/app/payments/provider.py`, `backend/app/payments/demo_provider.py`, `backend/app/payments/stripe_provider.py`, `backend/app/payments/deps.py`, `backend/tests/fakes.py`
- Modify: `backend/pyproject.toml`, `backend/uv.lock` (via `uv add stripe`), `backend/app/main.py`, `backend/tests/conftest.py`
- Test: `backend/tests/unit/test_stripe_provider.py` (new), `backend/tests/integration/test_demo_provider.py` (new)

**Interfaces:**
- Produces, in `provider.py`:

```python
CheckoutStatus = Literal["open", "complete", "expired"]
RefundStatus = Literal["pending", "succeeded", "failed"]

@dataclass(frozen=True)
class CheckoutStarted: session_ref: str; client_secret: str | None
@dataclass(frozen=True)
class CheckoutState: status: CheckoutStatus; paid: bool; payment_intent_ref: str | None; client_secret: str | None
@dataclass(frozen=True)
class RefundState: refund_ref: str; status: RefundStatus

class PaymentUnavailable(Exception): ...

class PaymentProvider(Protocol):
    name: str
    def start_checkout(self, *, reference: str, amount_pence: int, customer_email: str,
                       description: str, idempotency_key: str) -> CheckoutStarted: ...
    def get_checkout(self, session_ref: str) -> CheckoutState: ...
    def close_checkout(self, session_ref: str) -> bool: ...   # False: it had completed
    def refund(self, *, payment_intent_ref: str, amount_pence: int, idempotency_key: str) -> RefundState: ...
    def get_refund(self, refund_ref: str) -> RefundState: ...
```

- `DemoProvider(session)`: name `"demo"`. A demo session is the deposit `payments` row itself: `start_checkout` returns `CheckoutStarted("demo_" + secrets.token_urlsafe(16), None)`; `get_checkout` reads the row by `provider_ref` and reports `paid` (status `complete`) iff its `payment_intent_ref` is set; `close_checkout` returns `False` iff paid; `refund` returns `RefundState("demo_re_…", "succeeded")`; `get_refund` returns `succeeded`.
- `StripeProvider(secret_key)`: name `"stripe"`, uses `stripe.StripeClient` with a pinned `stripe_version`, a 10-second timeout and `max_network_retries=2`. Parameters exactly as the design's "Payment provider" section (embedded `ui_mode`, `redirect_on_completion="never"`, `payment_method_types=["card"]`, GBP line item, `client_reference_id` and `metadata.reference`, `customer_email`, `expires_at = now + 31 min` using `utc_now()`). `close_checkout` calls the expire endpoint; Stripe's "session is not open" error → re-read the session and return `False` if complete, `True` if already expired. Every `stripe.StripeError` other than that becomes `PaymentUnavailable`. Check the current Stripe docs for parameter names before writing.
- `deps.py`: `get_payment_provider(request: Request, session: SessionDep) -> PaymentProvider` — `request.app.state.stripe_provider` if set, else `DemoProvider(session)`. `create_app` sets `app.state.stripe_provider = StripeProvider(config.stripe_secret_key)` when `config.payment_provider == "stripe"`, else `None`. Also `make_provider(config, session) -> PaymentProvider` for the worker.
- `tests/fakes.py`: `FakeProvider` (name `"stripe"`) with `paid: set[str]`, `closed: set[str]`, `refund_status: RefundStatus = "pending"`, `fail: bool = False` (every call raises `PaymentUnavailable`), and `calls: list[tuple[str, dict[str, object]]]`. Session refs are `cs_fake_<n>`, client secrets `cs_fake_<n>_secret`, refunds `re_fake_<n>`. `mark_paid(ref)` adds to `paid` with payment intent `pi_<ref>`.
- `conftest.py`: fixture `fake_provider() -> FakeProvider`, and `api_client` gains `app.dependency_overrides[get_payment_provider] = lambda: fake_provider`.

- [ ] **Step 1: Write the failing tests**
  - `test_stripe_provider.py` (patch the client's resource methods with `unittest.mock`, no network): `test_start_checkout_sends_the_design_parameters` (asserts `ui_mode`, `redirect_on_completion`, `payment_method_types`, amount, currency `gbp`, `metadata["reference"]`, `customer_email`, `expires_at` 31 minutes ahead within a second, and the `idempotency_key` option), `test_refund_sends_payment_intent_amount_and_key`, `test_close_reports_completed_session_as_false`, `test_stripe_errors_become_payment_unavailable`, `test_secret_key_is_not_in_the_repr`.
  - `test_demo_provider.py`: `test_demo_checkout_is_unpaid_until_marked`, `test_demo_close_refuses_once_paid`, `test_demo_refund_succeeds`.
- [ ] **Step 2: Run them** — `uv run pytest tests/unit/test_stripe_provider.py tests/integration/test_demo_provider.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** after `uv add stripe` (pin the resolved version in `pyproject.toml` as `stripe>=<version>`).
- [ ] **Step 4: Run the whole backend suite and the gates** — `uv run pytest; uv run ruff check .; uv run mypy`. Expected: PASS, clean.
- [ ] **Step 5: Commit**

```powershell
git add backend
git commit -m "backend - payment provider interface, stripe and demo providers"
```

---

### Task 4: Completing, refunding and cancelling

**Files:**
- Create: `backend/app/payments/rules.py`, `backend/app/payments/service.py`, `backend/app/repositories/payments.py`
- Test: `backend/tests/unit/test_payment_rules.py` (new), `backend/tests/integration/test_complete_deposit.py` (new), `backend/tests/integration/test_cancel_booking.py` (new)

**Interfaces:**
- Consumes: Task 2 models, Task 3 `PaymentProvider`, `FakeProvider`, `make_deposit`.
- Produces:
  - `rules.py`: `deposit_refundable(start_at: datetime, now: datetime, free_cancellation_hours: int, by: Literal["customer", "garage"]) -> bool`.
  - `repositories/payments.py`: `get_payment_for_update(session, provider: str, ref: str) -> Payment | None`, `get_open_deposit(session, booking_id: int) -> Payment | None`, `paid_deposit(session, booking_id: int) -> Payment | None`, `count_payments(session, *, booking_id: int | None = None, refund_of: int | None = None) -> int`, `record_event(session, provider: str, event_id: str, type: str) -> bool` (True if new; `INSERT … ON CONFLICT DO NOTHING RETURNING`), `stale_open_deposits(session) -> list[Payment]` (open deposits whose booking status isn't `held`).
  - `payments/service.py`:
    - `complete_deposit(session, provider, session_ref: str, now: datetime) -> Booking | None` — the design's steps 1–4 exactly. Re-taking an expired booking's time: inside `session.begin_nested()`, set its reservation `active = True` and flush; `IntegrityError` → roll back the savepoint and refund.
    - `refund_deposit(session, provider, deposit: Payment) -> Payment` — creates the refund row (`refund_of = deposit.id`, key `refund-<deposit.id>-<n>`), sets `booking.deposit_status` from its status (`pending → refund_pending`, `succeeded → refunded`, `failed → refund_failed`). `PaymentUnavailable` propagates.
    - `apply_refund_update(session, provider, refund_ref: str) -> bool` — False if no row; otherwise re-reads with `provider.get_refund` and updates row and `deposit_status`.
    - `close_open_deposit(session, provider, booking: Booking, now) -> Booking | None` — if the booking has an open deposit, `close_checkout`; True → mark it `expired`; False → `complete_deposit`. Returns the booking when completion confirmed it, else None.
    - `cancel_booking(session, provider, booking, now, by: Literal["customer", "garage"], free_cancellation_hours: int) -> None` — `cancelled`, reservation inactive, refund when `deposit_refundable` and `deposit_status == "paid"`.

- [ ] **Step 1: Write the failing tests**
  - `test_payment_rules.py`: customer exactly 24h before → True; 24h minus 1s → False; 24h plus 1s → True; garage at any time (including after the start) → True; `free_cancellation_hours=0` and now before start → True.
  - `test_complete_deposit.py` (seeded `db_session`, `FakeProvider`, `make_hold` + `make_deposit`):
    - `test_paid_held_booking_is_confirmed` (status, `deposit_status`, `confirmed_at`, deposit `paid` with `payment_intent_ref`)
    - `test_held_past_its_time_but_unreleased_is_confirmed`
    - `test_unpaid_session_changes_nothing`
    - `test_unknown_session_returns_none`
    - `test_completing_twice_changes_nothing` (second call: no extra provider refund call, same `confirmed_at`)
    - `test_late_payment_time_still_free_is_confirmed` (booking `expired`, reservation inactive → confirmed, reservation active)
    - `test_late_payment_time_taken_refunds_once` (another active hold on the same bay and time; completion → booking `expired`, `refund_pending`, one refund row; call again → still one refund row and one provider refund call)
    - `test_refund_failure_rolls_back` (`fail=True` during refund → `PaymentUnavailable`, no refund row after rollback)
    - `test_refund_update_marks_refunded`, `test_failed_refund_marks_refund_failed`, `test_refund_update_for_unknown_refund_returns_false`
    - `test_close_open_deposit_marks_expired`, `test_close_open_deposit_completes_when_payment_got_in`
  - `test_cancel_booking.py`: `test_customer_in_time_is_refunded`, `test_customer_late_is_not_refunded`, `test_garage_always_refunds`, `test_waived_deposit_cancels_without_refund`; each checks status `cancelled` and the reservation inactive.
- [ ] **Step 2: Run them** — `uv run pytest tests/unit/test_payment_rules.py tests/integration/test_complete_deposit.py tests/integration/test_cancel_booking.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement.** Lock order everywhere: booking row (`get_booking_for_update`) before payment rows, so the webhook, poll and worker can't deadlock.
- [ ] **Step 4: Run the whole backend suite** — `uv run pytest`. Expected: PASS.
- [ ] **Step 5: Commit**

```powershell
git add backend
git commit -m "backend - complete deposits, refunds and the cancellation rule"
```

---

### Task 5: Checkout, status and release endpoints

**Files:**
- Modify: `backend/app/api/holds.py`, `backend/app/api/catalogue.py`, `backend/app/bookings/service.py`
- Delete: `backend/tests/integration/test_confirm_hold_api.py`, `backend/tests/integration/test_confirm_sweep_race.py` (their cases move to the new files below)
- Test: `backend/tests/integration/test_checkout_api.py` (new), `backend/tests/integration/test_hold_status_api.py` (new), `backend/tests/integration/test_checkout_sweep_race.py` (new), `backend/tests/integration/test_holds_api.py`, `backend/tests/integration/test_booking_policy_api.py`

**Interfaces:**
- Consumes: Task 4 service functions, Task 1 loaders, `get_payment_provider`.
- Produces:
  - `bookings/service.py`: `confirm_hold` is removed. `start_checkout(session, provider, reference, token, details, now, *, payment_hold_minutes, amount_pence) -> CheckoutResult` with `CheckoutResult(client_secret: str | None, demo_session: str | None, expires_in_seconds: int, amount_pence: int)`. Raises `HoldNotFound`, `HoldExpired` (after releasing and closing), `AlreadyConfirmed`, `PaymentUnavailable`. On a repeat with an open deposit it returns `get_checkout`'s client secret and the seconds left until `hold_expires_at`. `cancel_hold(session, provider, reference, token, now)` now closes the open deposit first (design "Holds during payment"); if completion confirms, raises `AlreadyConfirmed`; `PaymentUnavailable` from close is logged and the hold is released anyway. `hold_status(session, provider, reference, token, now) -> Booking` (runs `complete_deposit` first when held with an open deposit; `PaymentUnavailable` there is swallowed so the poll just says `held`).
  - Routes: `POST /api/holds/{reference}/checkout` (body = the old `ConfirmIn`, renamed `CheckoutIn`), `POST /api/holds/{reference}/status` (body `CancelIn`, renamed `TokenIn`), `DELETE` as before. Responses as the design's "API" section. `/status` returns `{"status", "deposit_status", "summary"}`, `summary` only when confirmed; the frontend shows the refunded message for `refund_pending`/`refunded` and a "call us" message for `refund_failed`. `BookingSummaryOut` gains `deposit_paid_pence: int` (the paid deposit's amount, or 0).
  - `GET /api/booking-policy` adds `payment_hold_minutes`, `deposit_amount_pence`, `payment` as in the design.

- [ ] **Step 1: Write the failing tests** (`api_client` + `fake_provider`, pinned `now` as in the existing hold tests)
  - `test_checkout_api.py`: `test_checkout_saves_details_and_extends_the_hold` (200 shape, `expires_in_seconds == 600`, `hold_expires_at == now + 10 min`, payment row `open` with 2000, normalised registration), `test_repeat_checkout_returns_same_session` (same `client_secret`, one `start_checkout` call, expiry unchanged), `test_checkout_wrong_token_is_404`, `test_checkout_unknown_reference_is_404`, `test_late_checkout_is_410_and_releases`, `test_checkout_after_paid_is_409`, `test_checkout_provider_down_is_503_and_saves_nothing` (expiry unchanged, no details, no payment row), parametrised `test_checkout_field_rules` (the old confirm 422 cases), `test_checkout_broken_deposit_setting_is_503`, `test_checkout_sends_customer_email_and_amount`.
  - `test_hold_status_api.py`: `test_status_while_waiting_is_held`, `test_status_confirms_when_provider_says_paid` (no webhook), `test_status_after_release_is_expired`, `test_status_shows_refund`, `test_status_wrong_token_is_404`, `test_status_provider_down_says_held`.
  - `test_holds_api.py`: `test_delete_closes_the_open_checkout` (provider `close_checkout` called, deposit `expired`), `test_delete_when_payment_got_in_confirms` (fake marks it paid → 409, booking confirmed), `test_delete_with_provider_down_still_releases`.
  - `test_checkout_sweep_race.py`: the old confirm-vs-sweep race, with `/checkout` instead of confirm: the booking ends `held` with a 10-minute expiry and active reservation, or `expired` with an inactive one, never a mix.
  - `test_booking_policy_api.py`: demo shape (`{"provider": "demo"}`), and stripe shape with a publishable key from a config built with keys.
- [ ] **Step 2: Run them** — `uv run pytest tests/integration/test_checkout_api.py tests/integration/test_hold_status_api.py tests/integration/test_holds_api.py tests/integration/test_checkout_sweep_race.py tests/integration/test_booking_policy_api.py -v`. Expected: FAIL (404s on the new routes, missing fields).
- [ ] **Step 3: Implement.** The Stripe call in `start_checkout` runs while the booking row is locked (design's call). Map `PaymentUnavailable` → 503 with the design's message and roll back.
- [ ] **Step 4: Run the whole backend suite and gates.** Expected: PASS, clean. `grep -r confirm_hold backend/app` finds nothing.
- [ ] **Step 5: Commit**

```powershell
git add -A backend
git commit -m "backend - checkout replaces confirm, hold status, release closes checkout"
```

---

### Task 6: Stripe webhook

**Files:**
- Create: `backend/app/api/stripe_webhook.py`, `backend/tests/fixtures/stripe/checkout_session_completed.json`, `checkout_session_expired.json`, `refund_updated.json`, `payment_intent_failed.json`, `backend/tests/stripe_signing.py`
- Modify: `backend/app/main.py`, `backend/tests/conftest.py`
- Test: `backend/tests/integration/test_stripe_webhook.py` (new)

**Interfaces:**
- Consumes: `record_event`, `complete_deposit`, `apply_refund_update`, `app.state.config.stripe_webhook_secret`.
- Produces: `POST /api/stripe/webhook` as the design's "API" section, registered always (503 without a secret). `tests/stripe_signing.py`: `signed(payload: bytes, secret: str, timestamp: int | None = None) -> dict[str, str]` returning the `Stripe-Signature` header (`t=<ts>,v1=<hex hmac_sha256(secret, f"{ts}.{payload}")>`), and `event(name: str, **overrides) -> bytes` loading a fixture and replacing `id`, `data.object.id` etc. Conftest fixture `webhook_client` like `api_client` but with `stripe_webhook_secret="whsec_test"` (`# noqa: S105`).
- Fixtures contain only ids, types, amounts and statuses — no names, emails or card data.

- [ ] **Step 1: Write the failing tests**
  - `test_completed_event_confirms_the_booking`
  - `test_duplicate_event_changes_nothing` (same body twice: both 200, one `payment_events` row, one confirmation, `complete_deposit`'s provider `get_checkout` called once)
  - `test_webhook_after_poll_confirmed_is_harmless`
  - `test_completed_event_for_an_unpaid_session_confirms_nothing` (event says completed, fake says unpaid: booking still `held`)
  - `test_expired_after_completed_leaves_booking_confirmed`
  - `test_expired_event_marks_open_deposit_expired`
  - `test_refund_update_before_the_row_exists_is_503_and_unrecorded`, then the same body after creating the row → 200 and `refunded`
  - `test_unhandled_event_is_recorded_and_ignored` (`payment_intent.payment_failed`)
  - `test_unknown_session_is_200_and_ignored`
  - `test_bad_signature_is_400`, `test_missing_signature_is_400`, `test_old_timestamp_is_400`, `test_no_secret_configured_is_503`
  - `test_failure_inside_handling_rolls_back_the_event` (fake `fail=True` during a late-payment refund → 500, no `payment_events` row; same body with `fail=False` → 200, refunded)
- [ ] **Step 2: Run them** — `uv run pytest tests/integration/test_stripe_webhook.py -v`. Expected: FAIL (404).
- [ ] **Step 3: Implement.** Read `await request.body()` for the signature check (`stripe.Webhook.construct_event` or `stripe.WebhookSignature.verify_header`); parse the JSON only after it passes. Event insert and handling share one transaction; commit at the end; any exception → rollback → 500. Log the event id and type, never the body.
- [ ] **Step 4: Run the whole backend suite and gates.** Expected: PASS, clean.
- [ ] **Step 5: Commit**

```powershell
git add backend
git commit -m "backend - stripe webhook, idempotent and signature-checked"
```

---

### Task 7: Demo payments and the worker's second job

**Files:**
- Create: `backend/app/api/demo_payments.py`
- Modify: `backend/app/main.py`, `backend/app/worker.py`
- Test: `backend/tests/integration/test_demo_payments_api.py` (new), `backend/tests/integration/test_worker.py`

**Interfaces:**
- Produces: `POST /api/demo/checkout/{demo_session}` (body `{"outcome": "pay" | "decline"}`), included by `create_app` **only** when `config.payment_provider == "demo"`. `pay`: lock the booking, set the deposit's `payment_intent_ref = "demo_pi_" + random`, `complete_deposit` with a `DemoProvider`, commit, 200 `{"status": "<booking status>"}`; unknown session or not open → 404. `decline` → 402 with the design's message, no change. In `worker.py`: `run_once(session, now, provider) -> int` still returns the released count, and after releasing calls `close_stale_checkouts(session, provider, now) -> int`, which for each `stale_open_deposits` row runs `close_open_deposit` and commits per row, logging and skipping a `PaymentUnavailable`. `main()` builds the provider with `make_provider(config, session)` each cycle.

- [ ] **Step 1: Write the failing tests**
  - `test_demo_payments_api.py` (an `api_client` variant with no provider override and no Stripe key): `test_demo_pay_confirms_the_booking`, `test_demo_decline_changes_nothing`, `test_demo_pay_twice_is_harmless`, `test_demo_endpoint_absent_with_stripe` (app built with keys → 404), `test_demo_pay_after_release_is_404`.
  - `test_worker.py`: update the existing test to `run_once(session, NOW, FakeProvider())`; add `test_worker_closes_checkout_of_a_released_hold`, `test_worker_retries_a_failed_close_next_cycle` (first cycle `fail=True`: deposit still `open`; second cycle: `expired`), `test_worker_completes_a_deposit_that_got_in` (close returns False → booking confirmed or refunded per the time being free).
- [ ] **Step 2: Run them** — `uv run pytest tests/integration/test_demo_payments_api.py tests/integration/test_worker.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole backend suite and gates.** Expected: PASS, clean.
- [ ] **Step 5: Commit**

```powershell
git add backend
git commit -m "backend - demo payments, worker closes stale checkouts"
```

---

### Task 8: Frontend API and the details step

**Files:**
- Modify: `frontend/src/booking/types.ts`, `frontend/src/booking/api.ts`, `frontend/src/booking/DetailsForm.tsx`, `frontend/src/booking/BookedPage.tsx`, `frontend/src/testing/fixtures.ts`
- Test: `frontend/src/booking/api.test.ts`, `frontend/src/booking/DetailsForm.test.tsx`, `frontend/src/booking/BookedPage.test.tsx`

**Interfaces:**
- Produces, in `types.ts`: `BookingPolicy` gains `payment_hold_minutes`, `deposit_amount_pence`, `payment: PaymentConfig` where `PaymentConfig = { provider: 'stripe'; publishable_key: string } | { provider: 'demo' }`. `Checkout = { client_secret: string | null; demo_session: string | null; expires_in_seconds: number; amount_pence: number }`. `DepositStatus` union of the six values. `HoldStatus = { status: 'held' | 'expired'; deposit_status: DepositStatus } | { status: 'confirmed'; deposit_status: DepositStatus; summary: BookingSummary }`. `BookingSummary` gains `deposit_paid_pence: number`.
- In `api.ts`: `confirmHold` is replaced by `startCheckout(reference, token, details): Promise<Result<Checkout> | Expired | Paid>` (`Paid = { ok: false; kind: 'paid' }` for 409); `fetchHoldStatus(reference, token): Promise<Result<HoldStatus>>` (POST); `cancelHold(reference, token): Promise<'released' | 'paid' | 'failed'>` (204 or 404 → `released`, 409 → `paid`, anything else or a network error → `failed`; still `keepalive`); `payDemo(session, outcome: 'pay' | 'decline'): Promise<Result<{ status: string }> | Declined>` (`Declined = { ok: false; kind: 'declined' }` for 402).
- `DetailsForm` props: `onBooked` is replaced by `onCheckout: (checkout: Checkout) => void` and `onAlreadyPaid: () => void`. The button reads **Continue to payment**; while submitting it reads **Starting payment…**, is disabled and the form has `aria-busy="true"`. The announcer says "… left to continue" instead of "… left to confirm".
- `BookedPage` shows "Deposit paid: £20.00" (using `formatPrice`) when `deposit_paid_pence > 0`.

- [ ] **Step 1: Write the failing tests**
  - `api.test.ts`: `startCheckout` posts to `/api/holds/<ref>/checkout` and maps 200 / 410 / 409 / 503; `fetchHoldStatus` posts the token in the body, not the URL; `cancelHold` maps 204, 404, 409, 500 and a rejected fetch; `payDemo` maps 200 and 402.
  - `DetailsForm.test.tsx`: update the confirm tests to checkout; add `shows Starting payment… and aria-busy while waiting`, `a 409 calls onAlreadyPaid`, `hands the checkout to the page`.
  - `BookedPage.test.tsx`: `shows the deposit paid`, `hides the deposit line for a waived deposit`.
- [ ] **Step 2: Run them** — `npm test -- src/booking/api.test.ts src/booking/DetailsForm.test.tsx src/booking/BookedPage.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.** `BookPage` will fail to type-check until Task 9; keep it compiling by passing temporary handlers that log nothing and do nothing, marked `// Task 9`.
- [ ] **Step 4: Run all frontend gates.** Expected: PASS (BookPage tests that confirmed a booking are updated in Task 9; mark any that now fail with `it.todo` only if they test the removed confirm path, and list them in the commit message body).
- [ ] **Step 5: Commit**

```powershell
git add frontend
git commit -m "frontend - checkout api, continue to payment, deposit on booked page"
```

---

### Task 9: The payment step

**Files:**
- Create: `frontend/src/booking/PaymentStep.tsx`, `frontend/src/booking/StripeCheckout.tsx`, `frontend/src/booking/PaymentStep.test.tsx`
- Modify: `frontend/package.json`, `frontend/package-lock.json` (via `npm install @stripe/stripe-js @stripe/react-stripe-js`), `frontend/src/booking/BookPage.tsx`, `frontend/src/booking/BookPage.test.tsx`, `frontend/src/App.css`

**Interfaces:**
- Consumes: Task 8 API and types.
- Produces:
  - `StripeCheckout({ publishableKey, clientSecret, onComplete }: { publishableKey: string; clientSecret: string; onComplete: () => void }): JSX.Element` — `EmbeddedCheckoutProvider` + `EmbeddedCheckout`, with `loadStripe` memoised per key at module level. Tests always `vi.mock('./StripeCheckout.tsx')` with a stub that renders a **Pay (test)** button calling `onComplete`.
  - `PaymentStep(props: { hold: Hold; checkout: Checkout; payment: PaymentConfig; zone: string; details: CustomerDetails; onBooked: (s: BookingSummary) => void; onSettled: (status: HoldStatus | null) => void; onTimeUp: () => void; pollMs?: number; pollLimit?: number }): JSX.Element` — the read-only summary (time, services, registration · make model, "Deposit £20.00, balance paid at the garage"), the countdown from `checkout.expires_in_seconds` (same announcer pattern, "… left to pay"), and `StripeCheckout` or the demo box (**Pay £20.00 (demo)** / **Decline card (demo)**; decline shows the 402 message). Completion (Stripe's `onComplete` or demo pay 200) starts polling `fetchHoldStatus` every `pollMs` (1000) up to `pollLimit` (30): `confirmed` → `onBooked`; `expired` → `onSettled(status)`; limit reached → the design's "We're still confirming your payment…" message with the reference and garage phone, in place. While polling, the countdown's end is ignored; otherwise it calls `onTimeUp`.
  - `BookPage`: `Step` gains `{ kind: 'paying'; hold: Hold; checkout: Checkout }`; heading "Pay your deposit". `unreleased` is set from `onHeld` and cleared on booked as before. A new `async function settle(): Promise<void>` used by the paying step's `onTimeUp`, **Change time** and **Change services**: `await cancelHold(...)` (clearing `unreleased` first so unmount doesn't send a second one), then `fetchHoldStatus`; `confirmed` → navigate to booked; `expired` with `refund_pending`/`refunded` → picker with the refunded notice; `refund_failed` → picker with "Your payment came in after your time ran out. Please call us on … so we can refund it."; otherwise → picker with "Your time ran out, so we released it. You haven't been charged." (for the countdown) or no notice (for Change time). Change services navigates only after `settle()` finishes. Unmount and pagehide stay fire-and-forget. `onAlreadyPaid` from the details step calls `fetchHoldStatus` and navigates to booked on `confirmed`.

- [ ] **Step 1: Write the failing tests**
  - `PaymentStep.test.tsx` (fake timers where needed): `shows the summary and the deposit`, `counts down from the checkout's seconds`, `shows Stripe's form with the publishable key and client secret`, `shows the demo box in demo mode`, `demo decline shows the message and changes nothing`, `completing polls until confirmed then calls onBooked`, `a released status calls onSettled`, `gives up after the limit with the reference and phone`, `the countdown ending while polling waits for the poll`, `the countdown ending otherwise calls onTimeUp`.
  - `BookPage.test.tsx`: `continue to payment shows the payment step`, `countdown end after a payment got in shows the booked page` (cancelHold → `paid`, status → confirmed), `countdown end with nothing paid returns to the picker saying not charged`, `a late refunded payment shows the refunded notice`, `change time during payment waits for the release`, `change services during payment releases before leaving`, `leaving during payment with Back releases the hold`, `a paid booking is never released`; update the Milestone 4 tests that confirmed.
- [ ] **Step 2: Run them** — `npm test -- src/booking/PaymentStep.test.tsx src/booking/BookPage.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.** Remove the Task 8 placeholders.
- [ ] **Step 4: Run all frontend gates** — `npm run lint; npm run typecheck; npm test; npm run build`. Expected: PASS, no `it.todo` left.
- [ ] **Step 5: Commit**

```powershell
git add frontend
git commit -m "frontend - payment step with stripe embedded checkout and demo mode"
```

---

### Task 10: Real Stripe end to end, CI and the setup guide

**Files:**
- Create: `docs/stripe-setup.md`
- Modify: `e2e/tests/instant-booking.spec.ts`, `.github/workflows/ci.yml`, `README.md`, `docs/SPEC.md`

**Interfaces:**
- Consumes: everything above. Needs the user's Stripe test keys in `.env` locally and as GitHub repository secrets `STRIPE_SECRET_KEY` and `STRIPE_PUBLISHABLE_KEY` before the push. **Stop and ask the user to create the account and add the secrets (following `docs/stripe-setup.md`) before running this task's e2e step.**

- [ ] **Step 1: Write the guide** `docs/stripe-setup.md` with the contents listed in the design's "Stripe setup guide", in PowerShell commands for Windows (installing the Stripe CLI with `winget install Stripe.StripeCli` or the zip from its GitHub releases page; `stripe login`; `stripe listen --forward-to localhost:8000/api/stripe/webhook`). Include the manual checklist.
- [ ] **Step 2: Update the e2e test** (it now fails until the stack has keys): at the start, fetch `/api/booking-policy` and fail with "Stripe test keys are not configured — see docs/stripe-setup.md" unless `payment.provider === 'stripe'` and the key starts with `pk_test_`. After the details form: click **Continue to payment**, expect the heading "Pay your deposit", then inside Stripe's iframe (`page.frameLocator('iframe[name*="embedded-checkout"]')` or whatever selector the current Embedded Checkout uses — find it with `npx playwright codegen http://localhost:8080`) fill the card number `4242424242424242`, expiry `12 / 34`, CVC `123`, cardholder name and postcode if asked, press **Pay**. Then expect "You're booked" and "Deposit paid: £20.00" (timeout 30s), and the existing availability check. The test title becomes `flow 1: instant booking with a deposit`.
- [ ] **Step 3: Run it locally** with keys in `.env` and `stripe listen` running: `docker compose up --build -d --wait`, then from `e2e/`: `npm test`. Expected: 1 passed. Then stop `stripe listen` and run it again. Expected: still 1 passed (the status poll confirms without the webhook).
- [ ] **Step 4: Update CI** in the `compose` job, before `docker compose up`:
  - a step that fails with a clear message when `secrets.STRIPE_SECRET_KEY` or `secrets.STRIPE_PUBLISHABLE_KEY` is empty;
  - install a pinned Stripe CLI release (download the Linux tarball for a fixed version from `github.com/stripe/stripe-cli/releases`, at least two weeks old);
  - `echo "STRIPE_WEBHOOK_SECRET=$(stripe listen --api-key "$STRIPE_SECRET_KEY" --print-secret)" >> "$GITHUB_ENV"`;
  - start `stripe listen --api-key "$STRIPE_SECRET_KEY" --forward-to localhost:8000/api/stripe/webhook > stripe-listen.log 2>&1 &`;
  - job-level `env` passes `STRIPE_SECRET_KEY` and `STRIPE_PUBLISHABLE_KEY` from secrets so Compose picks them up;
  - add `stripe-listen.log` to the failure artifact.
- [ ] **Step 5: Update docs.** README: the payment step, demo mode versus real Stripe, a link to `docs/stripe-setup.md`, the CI secrets (and that fork and Dependabot runs of `compose` fail without them), and the e2e test now needing keys. SPEC.md: tick "Payment webhooks are idempotent".
- [ ] **Step 6: Commit and push** (the user runs these)

```powershell
git add docs e2e .github README.md
git commit -m "ci - real stripe end-to-end test, stripe setup guide"
git push -u origin milestone5-deposit-payments
```

Expected: `backend`, `frontend` and `compose` all green on the PR.
