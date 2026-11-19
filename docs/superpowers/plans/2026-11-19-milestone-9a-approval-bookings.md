# Milestone 9a: Approval Bookings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Customers can request a needs-approval service online; staff approve, propose another time or decline from a Requests page; the customer pays the deposit from their booking link and the booking is confirmed.

**Architecture:** A request is a booking in `pending_approval`, and an approved one is in the new status `awaiting_deposit`. Both keep their deadline in `hold_expires_at`, and the single expiry rule in `app/repositories/bookings.py` is widened from `held` to all three "waiting" statuses. That way availability, clash checks, blocks and the worker all treat an overdue request like an overdue hold. Staff actions live in a new `app/schedule/approvals.py` beside `changes.py` and reuse its move core. The deposit for an approved booking goes through the existing `complete_deposit` path, opened from the booking link.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, pytest; React 19 + TypeScript, Vitest + Testing Library; Playwright; Stripe test mode.

**Spec:** [docs/superpowers/specs/2026-11-19-milestone-9a-approval-bookings-design.md](../specs/2026-11-19-milestone-9a-approval-bookings-design.md) (and [docs/SPEC.md](../../SPEC.md) flow 2).

## Global Constraints

- New settings, seeded as setup data (not admin-editable): `approval_hold_hours` = 48, `approval_payment_hours` = 24, `approval_lead_hours` = 24, `approval_min_payment_hours` = 2.
- Request deadline = min(sent + 48 h, start − `booking_cutoff_minutes`). Payment deadline = min(approved + 24 h, start − `booking_cutoff_minutes`).
- A request's start must be at least 24 hours after now. Approve and propose are refused when the payment deadline would be less than 2 hours after now.
- New booking status: `awaiting_deposit`. The "waiting" statuses are `held`, `pending_approval` and `awaiting_deposit`; each must have `hold_expires_at`.
- New email templates: `request_received`, `approved`, `proposed`, `declined`, `request_expired`, `deposit_expired`.
- New audit actions: `booking.approve`, `booking.propose`, `booking.decline`.
- Lock order, as in Milestone 8: `lock_shared(session)` first, then the booking row `FOR UPDATE`, then payment rows.
- The token always travels in the request body, never the URL. A bad link is always the same 404.
- Commits are one short title, "area - what", with no body and no attribution. The user runs the checks and the commit themselves.
- On Windows, write files as UTF-8 with LF line endings (Edit or Write, or `open(..., encoding="utf-8", newline="\n")`).
- Backend checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q`. Frontend checks: `cd frontend && npm run lint && npm run typecheck && npm test`. Use the same commands as M8.

## Review Focus

1. **A payment that arrives for a cancelled, declined or re-proposed booking** must be refunded, never kept silently. Pinned in Task 6 (`test_payment_on_cancelled_request_is_refunded`).
2. **Opening the pay form must not shorten the 24-hour deadline**, as `start_checkout` does for a hold. Pinned in Task 6 (`test_opening_form_keeps_payment_deadline`).
3. **A request past its deadline but not yet swept** must stop blocking the slot at once, and staff actions on it must be refused. Pinned in Task 4 (`test_overdue_request_frees_slot_before_worker`) and Task 7 (`test_approve_overdue_request_refused`).
4. **The expiry email is sent once only.** It is sent whether the worker or a new hold releases the request, and never for a request a late payment took back. Pinned in Task 4 (`test_release_queues_one_email_per_request`).
5. **Proposing a time with too little time to pay**: the propose picker has no customer cut-off, so the 2-hour minimum must refuse it. Pinned in Task 7 (`test_propose_too_soon_refused`).

---

### Task 1: Status, settings and migration

**Files:**
- Create: `backend/migrations/versions/0010_approval_bookings.py`
- Modify: `backend/app/models/booking.py` (BOOKING_STATUSES, `held_has_expiry` check), `backend/app/models/email.py` (EMAIL_TEMPLATES), `backend/app/seed.py` (DEFAULT_SETTINGS), `backend/app/repositories/availability.py`, `backend/app/settings/clashes.py`
- Test: `backend/tests/integration/test_booking_constraints.py`, `test_migrations.py`, `test_seed.py`, `test_payment_settings.py`

**Interfaces:**
- Produces:
  - `WAITING_STATUSES: Final = ("held", "pending_approval", "awaiting_deposit")` in `app/models/booking.py`.
  - `@dataclass(frozen=True) class ApprovalRules: hold_hours: int; payment_hours: int; lead_hours: int; min_payment_hours: int` and `load_approval_rules(session) -> ApprovalRules` in `app/repositories/availability.py`. These raise `SettingsUnavailable` like the other loaders.
  - `COUNTING_STATUSES` gains `"awaiting_deposit"`.

- [ ] **Step 1: Write the failing tests**
  - `test_awaiting_deposit_needs_expiry`: inserting a booking with `status="awaiting_deposit", hold_expires_at=None` raises IntegrityError on `ck_bookings_held_has_expiry`. Do the same for `pending_approval`.
  - `test_new_email_templates_allowed`: an EmailLog with each of the six new templates flushes.
  - `test_seed_adds_approval_settings`: after `seed`, `load_approval_rules` returns `ApprovalRules(48, 24, 24, 2)`.
  - `test_migrations`: the upgrade/downgrade round trip still passes (the existing test covers 0010 once it exists).
- [ ] **Step 2: Run them.** Run `uv run pytest tests/integration/test_booking_constraints.py tests/integration/test_seed.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Migration 0010 replaces `status_valid`, `held_has_expiry` (now `status NOT IN (<waiting>) OR hold_expires_at IS NOT NULL`) and email `template_valid`, using the `_replace_check` pattern from 0008. It inserts the four settings `ON CONFLICT DO NOTHING`. The downgrade restores the old checks and deletes the settings; it fails loudly if any `awaiting_deposit` rows exist.
  - Update the models and seed to match.
- [ ] **Step 4: Run the backend checks.** Expected: all pass.
- [ ] **Step 5: Commit.** `backend - approval statuses and settings`

### Task 2: Approval rules (pure)

**Files:**
- Create: `backend/app/bookings/approval.py`
- Test: `backend/tests/unit/test_approval_rules.py`

**Interfaces:**
- Consumes: `ApprovalRules` (Task 1).
- Produces, all pure with aware datetimes:
  - `needs_approval(services: Sequence[Service]) -> bool`
  - `request_deadline(now, start, rules, cutoff_minutes) -> datetime`
  - `payment_deadline(now, start, rules, cutoff_minutes) -> datetime`
  - `enough_notice(now, start, rules) -> bool` (start ≥ now + lead_hours)
  - `enough_time_to_pay(now, start, rules, cutoff_minutes) -> bool` (payment_deadline ≥ now + min_payment_hours)

- [ ] **Step 1: Write the failing tests.** Use rules (48, 24, 24, 2), cutoff 120, now = 2026-12-01 09:00 UTC:
  - Start 7 days ahead: request deadline is now + 48 h, payment deadline is now + 24 h.
  - Start now + 30 h: request deadline is start − 2 h (now + 28 h).
  - Start now + 10 h: payment deadline is now + 8 h; `enough_time_to_pay` is True.
  - Start now + 3 h 59 min: payment deadline is now + 1 h 59 min; `enough_time_to_pay` is False. At now + 4 h it is True.
  - `enough_notice`: now + 24 h is True, now + 23 h 59 min is False.
  - `needs_approval`: true when any service is `needs_approval`.
- [ ] **Step 2: Run.** Run `uv run pytest tests/unit/test_approval_rules.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the five functions.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit.** `backend - approval deadline rules`

### Task 3: The six emails

**Files:**
- Create: `backend/app/email/templates/{request_received,approved,proposed,declined,request_expired,deposit_expired}.{html,txt}.j2`
- Modify: `backend/app/email/message.py`, `backend/app/email/render.py`, `backend/app/email/outbox.py`
- Test: `backend/tests/unit/test_render_email.py`, `backend/tests/unit/test_outbox_rules.py`

**Interfaces:**
- Produces:
  - `EmailTemplate` gains the six names.
  - `EmailContext` gains `deadline: datetime | None` (taken from `booking.hold_expires_at`) and `deposit_due_pence: int` (from `load_deposit_pence`).
  - `_APPLIES_TO`: `request_received` → `pending_approval`; `approved` and `proposed` → `awaiting_deposit`; `declined` → `cancelled`; `request_expired` and `deposit_expired` → `expired`.
  - `_HAS_LINK` gains `request_received`, `approved` and `proposed`.
  - `proposed` reads `previous_start`, `previous_end` and `previous_bay` from the saved context, like `moved`.

- [ ] **Step 1: Write the failing tests** in `test_render_email.py`. For each template, render it with a fixed context and assert:
  - Subjects:
    - `request_received`: "We've got your request — {reference}"
    - `approved`: "Your booking is approved — pay the deposit to confirm — {reference}"
    - `proposed`: "We've suggested a new time — {reference}"
    - `declined`: "We can't take your booking — {reference}"
    - `request_expired`: "Your request has lapsed — {reference}"
    - `deposit_expired`: "Your booking time has been released — {reference}"
  - Bodies:
    - `approved` and `proposed` contain the deposit ("£20") and the deadline as `format_moment` ("Wed 2 Dec, 09:00").
    - `request_received` contains the deadline.
    - `proposed` contains both the old and the new time.
    - `declined` shows the reason when there is one, and has no reason line when there isn't.
    - Every template that has a link contains the link URL. The other three contain the garage phone number.
  - In `test_outbox_rules.py`, assert `email_still_applies` for each mapping above.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the templates in the style of `moved` and `garage_cancellation`, using the shared partials.
- [ ] **Step 4: Run the backend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `backend - approval emails`

### Task 4: One expiry rule for holds, requests and approvals

**Files:**
- Modify: `backend/app/repositories/bookings.py`, `backend/app/worker.py`, `backend/app/repositories/payments.py` (`stale_open_deposits`)
- Test: `backend/tests/unit/test_hold_expiry_rule.py`, `backend/tests/integration/test_hold_expiry.py`, `test_worker.py`, `test_availability_api.py`

**Interfaces:**
- Consumes: `WAITING_STATUSES` (Task 1) and the templates (Task 3).
- Produces (same names, wider meaning):
  - `expired_hold(now)` is `status IN WAITING_STATUSES AND hold_expires_at <= now`. `hold_has_expired(booking, now)` is the same rule in Python.
  - `release_hold(session, booking)` queues `request_expired` (when the booking was `pending_approval`) or `deposit_expired` (when it was `awaiting_deposit`) before marking it expired.
  - `release_expired_holds(session, now) -> int` does the same for every row. Use `UPDATE … FROM (SELECT id, status AS was …)` and `RETURNING id, reservation_id, was`, then queue the emails for the returned ids.
  - `stale_open_deposits` treats a form as stale when the booking's status is not in (`held`, `awaiting_deposit`).

- [ ] **Step 1: Write the failing tests.**
  - Unit: `hold_has_expired` is True for `pending_approval` and `awaiting_deposit` past their deadline, and False before it. It stays False for `confirmed`.
  - `test_overdue_request_frees_slot_before_worker`: a `pending_approval` booking past its deadline no longer blocks its slot in `/api/availability`, before any sweep.
  - `test_release_queues_one_email_per_request`:
    - Sweeping one overdue request and one overdue approval queues exactly one `request_expired` and one `deposit_expired`, and an overdue plain hold queues nothing.
    - A second sweep queues nothing more.
    - `release_hold` on one request queues one email.
  - `test_awaiting_form_not_stale`: an open deposit on an `awaiting_deposit` booking before its deadline isn't in `stale_open_deposits`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Update the module docstring's rule comment to match.
- [ ] **Step 4: Run the backend checks.** Expected: PASS, including the existing hold, sweep, block and clash tests unchanged.
- [ ] **Step 5: Commit.** `backend - one expiry rule for holds and requests`

### Task 5: Customer sends a request

**Files:**
- Modify: `backend/app/api/holds.py`, `backend/app/api/availability.py`, `backend/app/bookings/service.py`
- Test: create `backend/tests/integration/test_request_api.py`; modify `test_holds_api.py` and `test_availability_api.py`

**Interfaces:**
- Consumes: `needs_approval`, `enough_notice`, `request_deadline` (Task 2) and `load_approval_rules` (Task 1).
- Produces:
  - `send_request(session, reference: str, token: str, details: CustomerDetails, now, *, deadline_for: Callable[[datetime], datetime]) -> Booking` in `app/bookings/service.py`. It raises `HoldNotFound`, `HoldExpired`, or `AlreadyConfirmed` (when the booking isn't `held`). It saves the details, sets `status="pending_approval"` and `hold_expires_at=deadline_for(booking.start_at)`, and queues `request_received`.
  - Route `POST /api/holds/{reference}/request`, with body `CheckoutIn`, returns `201 BookingSummaryOut` (`status: "pending_approval"`). The errors match checkout: 404 for an unknown reference or a bad token, 409 `"Your time ran out"` for an expired hold.
  - `POST /api/holds` accepts needs-approval services. When a visit needs approval and the start is less than 24 h away, it returns 422 `"Requests need 24 hours' notice — please choose a later time"`.
  - `GET /api/availability` uses `cutoff_minutes = max(policy cutoff, lead_hours × 60)` when any requested service needs approval. The response gains `needs_approval: bool`.
  - `POST /api/holds/{reference}/checkout` returns 409 `"This visit needs approval"` for a needs-approval hold.

- [ ] **Step 1: Write the failing tests.**
  - A needs-approval service:
    - `/availability` offers no slot before now + 24 h, and returns `needs_approval: true`.
    - `/holds` at now + 23 h returns 422. At now + 2 days it returns 201.
    - `/request` returns 201 with status `pending_approval`. The booking's `hold_expires_at` is now + 48 h (for a start 7 days out), and one `request_received` email is queued.
  - `/request` with a wrong token returns 404. Past the 5-minute hold it returns 409.
  - Checkout on a needs-approval hold returns 409. `/request` on an instant hold returns 409 `"This visit doesn't need approval"`.
  - The mixed-bay-types refusal is unchanged.
- [ ] **Step 2: Run.** Run `uv run pytest tests/integration/test_request_api.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Remove the "needs approval — please call us" rejection.
- [ ] **Step 4: Run the backend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `backend - customers send approval requests`

### Task 6: Deposit for an approved booking

**Files:**
- Modify: `backend/app/payments/service.py`, `backend/app/bookings/service.py`
- Test: `backend/tests/integration/test_complete_deposit.py`, create `backend/tests/integration/test_approved_deposit.py`

**Interfaces:**
- Produces:
  - `complete_deposit` confirms an `awaiting_deposit` booking just as it confirms a `held` one. A paid deposit for any other status (`cancelled`, `confirmed` by another form, `completed`, …) is refunded with `refund_deposit`, and None is returned. The existing warning stays in the log.
  - `open_deposit_form(session, provider, booking, now, *, amount_pence: int, zone: ZoneInfo) -> CheckoutResult` in `app/bookings/service.py`. `start_checkout` and the link's pay route (Task 8) share it. It reuses an open form or starts a new one, and never changes `hold_expires_at`. For a hold, `start_checkout` still sets the 10-minute hold itself before calling it. For an approved booking, `expires_in_seconds` is the time left to the payment deadline.

- [ ] **Step 1: Write the failing tests.**
  - `test_opening_form_keeps_payment_deadline`: open a form on an `awaiting_deposit` booking. `hold_expires_at` is unchanged, and a second call returns the same form.
  - `test_awaiting_deposit_payment_confirms`: the demo provider is paid, and `complete_deposit` returns the booking as `confirmed`, `deposit_status="paid"`.
  - `test_late_payment_on_expired_approval`:
    - The time is still free, so the booking is confirmed.
    - The time is taken by another booking, so the deposit is refunded.
  - `test_payment_on_cancelled_request_is_refunded`: cancel the booking, then the deposit is paid. The booking stays `cancelled`, the deposit has a refund, and `deposit_status="refunded"`.
  - The existing `held` tests are unchanged.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the backend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `backend - deposit for approved bookings`

### Task 7: Staff approve, propose and decline

**Files:**
- Create: `backend/app/schedule/approvals.py`
- Modify: `backend/app/schedule/status_rules.py`, `backend/app/schedule/changes.py` (move core extracted; garage cancel closes the form)
- Test: `backend/tests/unit/test_status_rules.py`; create `backend/tests/integration/test_staff_approvals.py` and `backend/tests/integration/test_approval_concurrency.py`

**Interfaces:**
- Consumes: Task 2's rules, Task 3's templates, Task 6's `complete_deposit` behaviour, and `close_open_deposit`.
- Produces:
  - `Action` gains `"approve"`, `"propose"` and `"decline"`. `booking_actions`:
    - `pending_approval` → `["approve", "propose", "decline"]`
    - `awaiting_deposit` → `["propose", "cancel"]`
    - `confirmed` is unchanged.
  - In `changes.py`: `_move_reservation(session, booking, start, bay_id, now) -> dict[str, str]`. It returns `before`, and raises `SlotUnavailable` or `NotAllowed("no_change")`. It contains everything `move_booking` does before its email and audit (free-time check, reservation update, link expiry, dropping a queued reminder). `move_booking` calls it.
  - `_locked` refuses an overdue waiting booking with `NotAllowed("expired")` (use `hold_has_expired`).
  - In `approvals.py`, with nothing committed:
    - `approve_booking(session, staff, reference, now) -> Booking`
    - `propose_booking(session, provider, staff, reference, start, bay_id, reason: str | None, now) -> Booking`
    - `decline_booking(session, staff, reference, reason: str | None, now) -> Booking`
  - What each does:
    - Each takes `lock_shared` first.
    - Approve and propose check `enough_time_to_pay` (against the new start for propose), else raise `NotAllowed("too_soon")`. They set `awaiting_deposit` with `hold_expires_at = payment_deadline(...)` and queue `approved` or `proposed` (with `_previous(before)` and `reason`).
    - Propose on an `awaiting_deposit` booking first closes its open form with `close_open_deposit`.
    - Decline sets `cancelled`, frees the reservation, and queues `declined` with `{"reason": reason}`.
    - Audit:
      - `booking.approve`: before and after status.
      - `booking.propose`: before and after start, end and bay.
      - `booking.decline`: status, plus the reason.
  - `garage_cancel` on an `awaiting_deposit` booking closes its open form before `cancel_booking`.

- [ ] **Step 1: Write the failing tests.**
  - Status rules: the action lists above.
  - Approve:
    - Approving a request 7 days out gives `awaiting_deposit`, a deadline of now + 24 h, one `approved` email and one audit row.
    - `test_approve_overdue_request_refused`: a request past its deadline gives `NotAllowed("expired")`.
    - Approving a confirmed booking gives `NotAllowed("not_allowed")`.
  - Propose:
    - Proposing a free time moves the reservation, gives `awaiting_deposit` with a new deadline, and queues one `proposed` email whose context carries `previous_start`.
    - `test_propose_too_soon_refused`: a slot 3 hours away (staff cut-off is 0) gives `NotAllowed("too_soon")` and nothing changes.
    - Proposing on `awaiting_deposit` closes the open demo form (the payment status becomes `expired`) and resets the deadline.
  - Decline gives `cancelled`, frees the slot (a new hold can take it), and queues `declined` with the reason.
  - Garage cancel of an `awaiting_deposit` booking closes its form.
  - Concurrency (`test_approval_concurrency.py`, two sessions, the same pattern as `test_settings_hours_concurrency.py`): approve against a customer cancel ends with exactly one winner, and the loser sees a refusal. Approve against decline also ends with exactly one winner.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the backend checks.** Expected: PASS, including the existing move tests.
- [ ] **Step 5: Commit.** `backend - staff approve, propose and decline`

### Task 8: Booking link, staff routes and the Requests queue

**Files:**
- Modify: `backend/app/api/my_booking.py`, `backend/app/bookings/self_service.py`, `backend/app/api/staff_bookings.py`, `backend/app/api/staff_schedule.py` (or a new `staff_requests.py` router included under `/api/staff`), `backend/app/main.py`
- Test: `backend/tests/integration/test_my_booking_api.py`, create `backend/tests/integration/test_staff_requests_api.py`, `test_staff_route_guards.py`

**Interfaces:**
- Consumes: Tasks 5 to 7.
- Produces:
  - `MyBookingOut` gains `deadline: str | None` (garage-local ISO, set for `pending_approval` and `awaiting_deposit`). `can_cancel` is True for both. The view first completes a payment the provider already has (as `hold_status` does), then releases the booking if it's overdue.
  - `POST /api/bookings/{reference}/pay` with `{token}` returns `CheckoutOut` (the same shape as `/holds/{ref}/checkout`). It returns 404 for a bad link, 409 `"Nothing to pay"` unless the booking is `awaiting_deposit` and not overdue, and 503 when the provider is down.
  - `cancel_from_link` allows `pending_approval` and `awaiting_deposit`. It closes an open form first, cancels with no refund rule needed, and queues `cancellation`.
  - Staff routes (check_origin and login, like move):
    - `POST /api/staff/bookings/{reference}/approve` with `{}`.
    - `POST /api/staff/bookings/{reference}/propose` with `MoveIn`.
    - `POST /api/staff/bookings/{reference}/decline` with `CancelIn` (an optional reason).
    - Each returns `StaffBookingOut`. Errors: 404 for an unknown booking, 409 with `detail` `not_allowed` | `expired` | `too_soon`, and 409 `TAKEN` when the slot is taken.
  - `GET /api/staff/requests` returns `list[RequestOut]`, where `RequestOut = {reference, customer_name, services: list[str], start, bay, deadline, created_at}`. It lists `pending_approval` bookings that aren't overdue, oldest `created_at` first.
  - `_history_text` describes the three new audit actions as "Approved by {who}", "New time proposed by {who}" and "Declined by {who}".

- [ ] **Step 1: Write the failing tests.**
  - Link view of a request shows `status: pending_approval`, a deadline and `can_cancel: true`.
  - Pay on an approved booking returns 200 with a demo session. Paying it through `/api/demo/...` and then viewing shows `confirmed`.
  - Pay on a request (not approved yet) returns 409. Pay with a bad token returns 404.
  - Cancelling a request from the link gives `cancelled` and one `cancellation` email.
  - The staff routes cover the happy path and each 409 detail.
  - The queue lists requests oldest first, without overdue or approved ones.
  - Route guards: add the new paths to the logged-out (401) and bad-origin (403) lists.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the backend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `backend - booking link payment and staff request routes`

### Task 9: Public site sends a request

**Files:**
- Modify: `frontend/src/App.tsx` (service cards), `frontend/src/booking/BookPage.tsx`, `frontend/src/booking/DetailsForm.tsx`, `frontend/src/booking/api.ts`, `frontend/src/booking/types.ts`, `frontend/src/booking/BookedPage.tsx`
- Test: `frontend/src/App.test.tsx`, `frontend/src/booking/BookPage.test.tsx`, `DetailsForm.test.tsx`, `BookedPage.test.tsx`

**Interfaces:**
- Produces:
  - `sendRequest(reference: string, token: string, details: CustomerDetails): Promise<Result<BookingSummary> | Expired>` in `booking/api.ts`.
  - `Availability` gains `needs_approval: boolean`.
  - `DetailsForm` gains the prop `request: boolean`.
  - `BookedPage` shows a request when `summary.status === 'pending_approval'`.

- [ ] **Step 1: Write the failing tests.**
  - Services page: a needs-approval card has a checkbox and the "Needs approval" badge, and no "call us" line.
  - Book page:
    - When availability says `needs_approval`, the details step shows "The garage will check your request and email you within 48 hours. The £20 deposit is only asked for once it's approved." and a **Send request** button, with no payment step.
    - Sending calls `sendRequest` and shows the heading "Request sent" with the reference and "We'll email you at {email}".
    - A 409 returns to picking with the existing ran-out notice.
- [ ] **Step 2: Run.** Run `npm test -- src/App.test.tsx src/booking`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the frontend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `frontend - customers send approval requests`

### Task 10: Booking link page: waiting and paying

**Files:**
- Create: `frontend/src/manage/PayDeposit.tsx`
- Modify: `frontend/src/manage/ManageBookingPage.tsx`, `frontend/src/manage/api.ts`, `frontend/src/manage/types.ts`
- Test: `frontend/src/manage/ManageBookingPage.test.tsx`, create `frontend/src/manage/PayDeposit.test.tsx`

**Interfaces:**
- Consumes: `POST /api/bookings/{reference}/pay` and the view's `deadline` (Task 8). Reuses `StripeCheckout` and `payDemo` from `booking/`.
- Produces:
  - `startPayment(reference: string, token: string): Promise<Result<Checkout> | Invalid | Conflict>` in `manage/api.ts`.
  - `MyBooking.deadline: string | null`.
  - `PayDeposit({ reference, token, payment, onPaid })`, which renders the Stripe form or the demo buttons. Once the payment is done, it polls `viewBooking` (every 2 s, up to 15 tries) until the status is `confirmed`, then calls `onPaid`.

- [ ] **Step 1: Write the failing tests.**
  - Pending: shows "We're checking your request and will email you by {Wed 2 Dec, 09:00}.", a Cancel button, and no Pay button.
  - Awaiting deposit: shows "Pay the £20 deposit by {deadline} to confirm" and a **Pay deposit** button. Pressing it opens the demo pay buttons, and paying shows the confirmed booking.
  - A 409 from pay shows "This booking can't be paid for any more. Please call us on {phone}." and reloads the booking.
  - Cancelling a pending booking says nothing about refunds.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the frontend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `frontend - pay deposit from the booking link`

### Task 11: Staff Requests page and approval actions

**Files:**
- Create: `frontend/src/staff/requests/RequestsPage.tsx`, `frontend/src/staff/requests/RequestsPage.test.tsx`, `frontend/src/staff/booking/ApprovalPanel.tsx`, `frontend/src/staff/booking/ApprovalPanel.test.tsx`
- Modify: `frontend/src/staff/StaffApp.tsx`, `StaffLayout.tsx`, `api.ts`, `types.ts`, `labels.ts`, `booking/BookingDetailPage.tsx`, `booking/MovePanel.tsx` (gains `mode: 'move' | 'propose'`), `schedule/DayView.tsx`, `schedule/WeekView.tsx`, `admin/AuditPage.tsx`, `staff.css`
- Test: the existing tests of those files

**Interfaces:**
- Consumes: Task 8's routes.
- Produces:
  - In `staff/api.ts`: `fetchRequests()`, `approveBooking(ref)`, `proposeBooking(ref, start, bayId, reason)`, `declineBooking(ref, reason)`, all returning `StaffResult`.
  - `StaffRequest` in `types.ts`.
  - Route `/staff/requests` for every staff role. The nav link reads "Requests" plus the count when there are any ("Requests (2)"), fetched when the layout mounts and on navigation.

- [ ] **Step 1: Write the failing tests.**
  - Requests page:
    - Lists each request with its reference link, customer, services, requested time, bay and "Reply by {deadline}".
    - Empty state: "No requests waiting."
  - Nav: shows "Requests (2)" for a staff user.
  - Booking page for `pending_approval`:
    - **Approve** asks "Approve this request? The customer will be emailed to pay the £20 deposit within 24 hours." Confirming calls `approveBooking`, then shows "Approved — the customer has been emailed".
    - **Propose another time** shows "Phone the customer first", then the picker, and saves with `proposeBooking`.
    - `too_soon` shows "Too soon for the customer to pay — choose a later time".
    - **Decline** has an optional reason and confirms.
  - Booking page for `awaiting_deposit`: shows Propose another time and Cancel, and no job buttons.
  - Day and week views: a `pending_approval` item is labelled "Request" and an `awaiting_deposit` one "Awaiting deposit", each with its own CSS class.
  - Audit page: the three actions read "Approved request {ref}", "Proposed a new time for {ref}" and "Declined request {ref}".
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the frontend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `frontend - staff requests and approvals`

### Task 12: End-to-end flow 2, spec and README

**Files:**
- Create: `e2e/tests/approval-booking.spec.ts`
- Modify: `e2e/tests/booking.ts` (a helper to choose a needs-approval service and a slot 2+ days ahead, if needed), `docs/SPEC.md`, `README.md`

- [ ] **Step 1: Write the test** `flow 2: a request is approved and paid`. It's skipped without Stripe test keys, like flow 1. The steps:
  1. Choose "Diagnostic check" (seeded needs-approval), pick the first slot at least 2 days ahead, and enter the details with a unique email.
  2. Press Send request and expect "Request sent".
  3. Log in as staff, open Requests, open the reference, Approve, and confirm.
  4. Find the `approved` email in Mailpit, open its link, press Pay deposit, and use `payInStripe`.
  5. Expect the booking page to show "Confirmed" and a `confirmation` email to arrive.
- [ ] **Step 2: Run it against the rebuilt stack.** Run `docker compose up -d --build && cd e2e && npx playwright test approval-booking`. Expected: PASS. Then run the whole e2e suite. Expected: all 8 pass.
- [ ] **Step 3: Update SPEC.md.**
  - Decisions log: a row "Approval bookings" with the Nov 19 decisions (propose = move + approve; pay from link; 48 h, 24 h, 24 h notice, 2 h minimum; status awaiting deposit).
  - Booking statuses: add "awaiting deposit".
  - Open question "Needs-approval hold": ticked.
  - Build order: split item 9 into "9a. Approval bookings" (done when flow 2 passes end to end in CI) and "9b. Enquiries" (done when flow 3 passes).
  - Users and roles: the staff row's "Approving bookings and enquiries arrives in Milestone 9" becomes "Staff approve, propose a time for, or decline booking requests; enquiries arrive in Milestone 9b".
- [ ] **Step 4: Update README.md.** Add a flow 2 description, and a line on the Requests page.
- [ ] **Step 5: Commit.** `e2e - approval booking flow; spec and readme`
