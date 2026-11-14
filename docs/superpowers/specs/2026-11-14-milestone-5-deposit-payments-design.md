# Milestone 5: Deposit Payments — Design

Nov 14, 2026 · Adam Ornoch

Spec: [docs/SPEC.md](../../SPEC.md), "Build order" item 5 and "Core user flows" flow 1. Builds on Milestone 4 ([design](2026-11-12-milestone-4-booking-flow-design.md), [plan](../plans/2026-11-12-milestone-4-booking-flow.md)).

## Intent

Turn "Confirm booking" into "Pay £20 deposit". A booking is confirmed only when the server has seen the money arrive, never because the browser says so. Stripe runs in test mode, so no real money moves, but the code is the code a real garage would run: going live means swapping test keys for live ones.

This milestone also builds the refund, and the "24 hours or more ahead" rule that decides it, so Milestones 6 (customer cancels from the emailed link) and 7 (staff cancel) only have to call it.

**Done when** tests pass for a payment that succeeds, one that fails, and a payment message that arrives twice or out of order, and flow 1 passes end to end in CI **through the real Stripe test form**.

## Goals

- **The payment step**: after the details form, the customer pays the deposit in **Stripe's payment form shown inside the booking page** (Stripe "Embedded Checkout"). The customer never leaves the site.
- **A `payments` table** recording each deposit and refund, and a **`payment_events` table** so a repeated Stripe message changes nothing twice.
- **`POST /api/stripe/webhook`**: Stripe's messages, signature-checked, handled idempotently.
- **The payment hold**: the time stays held for `payment_hold_minutes` (10) once the customer moves to payment. When it runs out, the server closes the Stripe form early so it can't be paid.
- **Late payments**: a payment that lands after the hold ran out still confirms the booking if the time is still free, and is refunded automatically if it isn't.
- **Refunds**: one service function that refunds a paid deposit, and the cancellation rule, both tested, ready for Milestones 6 and 7.
- **Demo mode**: with no Stripe keys set, a fresh clone still books end to end through a plain "Pay £20 (demo)" box. CI never uses it.
- A **Stripe setup guide** for someone who has never used Stripe.

## Non-goals

- **A cancel button for customers or staff** (Milestones 6 and 7). Only the refund function and rule are built.
- **Confirmation emails** (Milestone 6). Stripe test mode sends no receipts either.
- **Deposits for needs-approval bookings** (Milestone 8).
- **Editing your details on the payment step.** "Change time" and "Change services" still work; there is no "Edit details" back step.
- Payment methods other than cards (no PayPal, Klarna, bank redirects). Apple Pay and Google Pay appear only if Stripe offers them inside the card form without a redirect.
- Currencies other than GBP.

## Anti-goals

These would make the milestone a failure even if the happy path works:

- **A booking is confirmed without the server having checked the money arrived**, from Stripe or (in demo mode) the demo endpoint. The browser's "payment complete" signal only tells the page to ask the server.
- **A customer is charged and gets neither a booking nor a refund.** Every paid deposit ends as a confirmed booking or a refund.
- **A repeated or out-of-order Stripe message changes anything twice**: two refunds, a booking confirmed twice, a refunded booking re-confirmed.
- **The amount comes from the browser**, or is hardcoded. It comes from the `deposit_amount_pence` setting, read when the payment starts.
- **A secret key reaches the browser, the logs or the repository.** Only the publishable key is sent to the page.
- **The slot stays hidden for Stripe's 30 minutes** after the customer has gone.
- **Demo mode can switch on in production**, or in CI.

## Decisions made with Adam

1. **Stripe's form inside our page** (Embedded Checkout), not a redirect to Stripe and not a card form we build. Adam asked whether the redirect option would still suit real payments (yes) and what modern sites use. They chose the embedded Stripe form: it keeps customers on the site, and the server code is the same as the redirect option's, so switching later is a front-end change.
2. **The payment step gets its own hold of 10 minutes**, stored as the setting `payment_hold_minutes`. The details step keeps its 5 minutes. When the payment hold runs out, the server closes the Stripe form early rather than keeping the slot for Stripe's 30-minute minimum.
3. **A payment that slips through after the hold ran out is refunded automatically**, and the customer is told. (Claude's addition, see "Late payments": if the time is still free, the booking is confirmed instead, which is better for everyone.)
4. **The deposit amount is a setting**: the existing `deposit_amount_pence` (2000).
5. **CI runs the end-to-end test through the real Stripe test form**, using test keys Adam stores as GitHub repository secrets, and the Stripe command-line tool to pass Stripe's messages to the API inside CI. Adam accepted the cost: the check depends on Stripe being reachable and can break when Stripe changes its form.
6. **Demo mode exists only for a fresh clone with no keys**, so `docker compose up` still books out of the box. CI never uses it.
7. Refunding on eligible cancellation is built and tested here, with the buttons that use it left to Milestones 6 and 7.

## The customer's journey

1. Pick services and a time, and type details, exactly as in Milestone 4, inside the 5-minute hold. The button reads **Continue to payment** (shows "Starting payment…" and `aria-busy` while waiting, fixing a Milestone 4 deferred minor).
2. **Payment step.** The hold restarts at 10 minutes. The page shows the booking summary (time, services, car, "Deposit £20, balance paid at the garage"), the countdown, and Stripe's form below. "Change time" and "Change services" stay in the nav. The heading is "Pay your deposit".
3. **Declined card**: Stripe shows the error inside its form. The customer can try another card until the time runs out. Nothing changes on our side.
4. **Paid**: Stripe tells the page the payment is complete. The page shows "Confirming your payment…" and asks the server every second. When the server says confirmed, it goes to the booked page, which gains "Deposit paid: £20". If the server hasn't confirmed after 30 seconds, the page shows the reference and "We're still confirming your payment. Please call us on … if you don't see it confirmed."
5. **Time runs out**: the page releases the hold and **waits for the server's reply before saying anything** (Claude's call), because a payment already in flight (say, a 3-D Secure code being typed) can still get through. If the reply says the booking is released, it returns to the time picker with "Your time ran out, so we released it. You haven't been charged." Details are kept, as now. If the payment got in, it shows the booked page, or the refunded message in step 7.
6. **Leaving with a button** (Change time, Change services): the same — release, wait for the reply, and show the booked page if a payment got in. **Leaving without one** (Back, refresh, close) releases as in Milestone 4 with nothing to show; a payment in flight then still ends as a booking or a refund, and the customer learns of it from Milestone 6's email. Accepted until then.
7. **Late payment, time already taken**: if the customer's payment completes but the time has gone, the page shows "Your payment came in after your time ran out, and that time has been taken. We've refunded your £20 deposit; it can take 5–10 days to reach your card." and offers to pick another time, details kept.

## Data model

Claude's calls. Migration `0006`.

**`bookings`** gains:

| Column | Type | Notes |
| --- | --- | --- |
| `deposit_status` | text, not null, default `'unpaid'` | Check `IN ('unpaid', 'paid', 'refund_pending', 'refunded', 'refund_failed', 'waived')`. `refunded` only once the provider reports the refund succeeded. `refund_failed` flags the booking for staff (Milestone 7 shows it); it isn't retried automatically, because a refund Stripe refuses (a closed card, say) won't succeed on a second try. `waived` exists only for bookings confirmed before this milestone: the migration sets every existing `confirmed` row to it. New check: `status <> 'confirmed' OR deposit_status IN ('paid', 'waived')`. |

Details can now be on a `held` booking (they're saved when payment starts). The existing `confirmed_has_details` check still holds.

**`payments`**: one row per deposit attempt and per refund.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `booking_id` | FK → `bookings.id`, not null | |
| `kind` | text, not null | `'deposit'` or `'refund'`. |
| `provider` | text, not null | `'stripe'` or `'demo'`. |
| `provider_ref` | text, not null | Checkout Session id for a deposit, Refund id for a refund. Unique with `provider`. |
| `payment_intent_ref` | text, nullable | For a deposit, set once paid. Refunds are made against it. |
| `amount_pence` | integer, not null, > 0 | Snapshot of the setting when the payment started. |
| `currency` | text, not null, default `'gbp'` | |
| `status` | text, not null | Deposit: `'open'`, `'paid'`, `'expired'`. Refund: `'pending'`, `'succeeded'`, `'failed'`. One check per kind. |
| `created_at`, `updated_at` | timestamptz | |

- Partial unique index: at most one `open` deposit per booking.
- Partial unique index: at most one refund per deposit that isn't `failed` (`refund_of` FK → `payments.id`, nullable, set on refunds), so no path can refund twice, and a staff retry after a failure (Milestone 7) stays possible. Refund idempotency keys are `refund-<deposit session id>-<attempt>`, attempt counting previous refund rows for that deposit.

**`payment_events`**: every webhook event processed.

| Column | Type | Notes |
| --- | --- | --- |
| `provider`, `event_id` | text, not null, primary key together | Stripe's `evt_…` id. |
| `type` | text, not null | |
| `received_at` | timestamptz, default now | |

No payload is stored: it would hold the customer's email and card details we don't need.

**Settings**: one new key, `payment_hold_minutes: 10`, added to `DEFAULT_SETTINGS` (the seed adds missing keys on every start, so existing databases get it). It must be a whole number from 1 to 25, so the hold always ends before the Stripe form's own 31-minute expiry and the server is always the one that closes it (Claude's call). `deposit_amount_pence` must be a whole number from 30 (Stripe's minimum for GBP) to 100000. `free_cancellation_hours` is used by the refund rule. Any of them missing or invalid gives 503 on the endpoints that need it.

## Payment provider

Payment calls sit behind one interface, `PaymentProvider` in `app/payments/`, so tests use a fake, demo mode uses a demo, and nothing else imports `stripe`:

```python
class PaymentProvider(Protocol):
    name: str  # "stripe" or "demo"
    def start_checkout(self, *, reference: str, amount_pence: int, customer_email: str,
                       description: str, idempotency_key: str) -> CheckoutStarted: ...
        # CheckoutStarted(session_ref, client_secret)
    def get_checkout(self, session_ref: str) -> CheckoutState: ...
        # CheckoutState(status: "open" | "complete" | "expired", paid: bool,
        #               payment_intent_ref: str | None, client_secret: str | None)
    def close_checkout(self, session_ref: str) -> bool: ...
        # True if it is now closed; False if it had already completed (a payment got in)
    def refund(self, *, payment_intent_ref: str, amount_pence: int,
               idempotency_key: str) -> RefundStarted: ...
        # RefundStarted(refund_ref, status: "pending" | "succeeded" | "failed")
```

The signatures are the shape, not the exact names: the builder may adjust them.

**`StripeProvider`** uses the official `stripe` Python package (new backend dependency, pinned).

- Checkout Session: `ui_mode` embedded, `mode` payment, one line item in GBP with the deposit amount and a description like "Deposit for booking 7K3Q-M2PX, Tue 18 Nov 08:30", `payment_method_types ["card"]`, `redirect_on_completion "never"` (the page listens for completion instead of being redirected), `customer_email`, `client_reference_id` and `metadata.reference` set to the booking reference, and `expires_at` 31 minutes ahead (Stripe's minimum is 30).
- Every create call sends a Stripe idempotency key: `deposit-<booking reference>-<n>` and `refund-<deposit session id>-<n>`. A retried call can't make a second session or a second refund. Keys must be unique across every database sharing the Stripe account (Stripe keeps them for 24 hours), so they use the random reference and Stripe's own session id, never row ids. (Corrected during the build: row ids made every fresh CI database send `deposit-1-0` and get an IdempotencyError.)
- Network timeout of 10 seconds. Any Stripe error becomes a `PaymentUnavailable` exception.
- The Stripe API version is pinned in code, so a Stripe-side default change can't alter behaviour.
- Check the current Stripe docs when building: Stripe renames `ui_mode` values and event names now and then.

**`DemoProvider`**: no network. Its sessions are just the `payments` row (`provider = 'demo'`, `provider_ref` `demo_<random>`). "Paying" is a demo-only endpoint (below). Refunds succeed immediately.

**Which one runs**: `stripe` when `STRIPE_SECRET_KEY` is set, otherwise `demo`. When `ENVIRONMENT=production` and no key is set, the API **refuses to start**. A test checks this. The provider is a FastAPI dependency, so tests override it with a fake that records calls and can be told to fail.

**Configuration** (environment variables, added to `AppConfig` and `.env.example`, passed through by `docker-compose.yml`): `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`. All optional and blank in `.env.example`. The API logs which provider it started with, never a key.

## Holds during payment

The Milestone 4 rules stay: "expired" is still `status = 'held' AND hold_expires_at <= now`, and confirm-style changes still lock the booking row.

- **Starting payment** moves `hold_expires_at` to `now + payment_hold_minutes`, under the row lock, only if the hold hasn't expired.
- **Closing the Stripe form when a hold ends.** Whenever a held booking with an `open` deposit is released — by `DELETE /api/holds/{reference}`, by the worker's sweep, or by a late checkout call finding it expired — the server calls `close_checkout`. The worker also retries this for any `open` deposit whose booking is no longer `held` (a previous close failed), every cycle, so the Stripe form is closed within about a minute at worst.
- **If `close_checkout` returns False** (the customer paid in the same moment), the server runs the completion handler for that session straight away, so the customer gets their booking or their refund without waiting for the webhook.
- **The worker** gains this second job in `run_once`. Each Stripe call is separate: one failing is logged and doesn't stop the others. Because the worker now handles money, it gets `restart: unless-stopped` in Compose (a Milestone 4 deferred minor).

## Completing a payment

One function, `complete_deposit(session, provider, session_ref, now)`, is the only path to a paid booking. The webhook, the status poll and the demo endpoint all call it. It is idempotent:

1. Find the `payments` row by `session_ref`. Unknown → do nothing (log it).
2. Lock the booking row. If the deposit row is already `paid`, do nothing.
3. Ask the provider for the session (`get_checkout`). Not paid → do nothing. **The webhook's own copy of the session is not trusted on its own; the state is re-read from Stripe**, which also makes out-of-order messages harmless.
4. Mark the deposit `paid`, store `payment_intent_ref`. Then, by the booking's state:
   - **`held`** (even past its hold time, as long as nothing has released it): its reservation is still active, so confirm: `status = 'confirmed'`, `deposit_status = 'paid'`, `confirmed_at = now`.
   - **`expired`**: try to take the time back by setting its reservation active again inside a savepoint. If the overlap constraint allows it, confirm as above. If not, someone else has the time: refund (below), `deposit_status = 'refunded'`, booking stays `expired`.
   - **Anything else** (already confirmed through another path, cancelled): do nothing more.

**Refund**: `refund_deposit(session, provider, deposit_payment, reason)` creates the refund row with status from the provider and sets `deposit_status` to `refund_pending`, `refunded` or `refund_failed` to match. The partial unique index makes a second live refund of the same deposit impossible. If the provider call fails, the exception rolls the transaction back, so the webhook returns 500 and Stripe retries it, with the same idempotency key.

**The cancellation rule** (pure function in `app/payments/rules.py` or beside the booking rules): `deposit_refundable(start_at, now, free_cancellation_hours, by)`. A customer cancelling at least `free_cancellation_hours` before `start_at` gets a refund; exactly at the boundary counts as in time. Later than that, no refund. A cancellation by the garage always refunds. **`cancel_booking(session, provider, booking, now, by)`** sets `cancelled`, frees the reservation, and refunds when the rule says so and the deposit is `paid`. No route calls it yet.

## API

All public, no login. 422s keep the single-string `detail` shape from Milestone 4.

**`GET /api/booking-policy`** gains `payment_hold_minutes`, `deposit_amount_pence`, and `payment`: `{"provider": "stripe", "publishable_key": "pk_test_…"}` or `{"provider": "demo"}`. The page gets the publishable key at runtime, so the frontend image is built without keys.

**`POST /api/holds/{reference}/confirm` is replaced by `POST /api/holds/{reference}/checkout`**, with the same body (token and details) and the same field rules.

- 404 for an unknown reference or wrong token, 410 for an expired hold (releasing it there and then), as confirm did.
- Saves the details, moves the hold to `payment_hold_minutes`, creates the deposit (`provider.start_checkout`) and its `payments` row, commits.
- **200** `{"client_secret": "…" | null, "demo_session": "demo_…" | null, "expires_in_seconds": 600, "amount_pence": 2000}`. The countdown restarts from `expires_in_seconds`.
- **A repeat call** (double tap, retry after a dropped connection) with an `open` deposit returns the same session (`get_checkout` gives its client secret again) and doesn't extend the hold again. Details sent on a repeat are ignored.
- **Already confirmed** → **409** `{"detail": "This booking is already paid"}`.
- **503** `{"detail": "Payment is unavailable right now — please try again or call us"}` when the provider fails or a setting is broken. Nothing is saved: the hold keeps its old expiry.
- The Stripe call happens while holding the booking row lock, with the 10-second timeout. That briefly holds up a sweep of that one row, which is acceptable at this garage's size (Claude's call).

**`POST /api/holds/{reference}/status`** with `{"hold_token": "…"}` (POST, so the token stays out of URLs and logs):

- `{"status": "held"}` while waiting. If the deposit is `open`, it first calls `complete_deposit`, so a booking confirms even when the webhook hasn't arrived (or, locally, can't arrive).
- `{"status": "confirmed", "summary": {…}}`: the Milestone 4 summary plus `deposit_paid_pence`.
- `{"status": "expired", "refunded": true | false}`.
- 404 as above. Throttling is Milestone 9's job; the page polls once a second for at most 30 seconds.

**`DELETE /api/holds/{reference}`** keeps its behaviour, and also closes an open Stripe form (see "Holds during payment"). If closing reveals a payment that got in, the booking may end up confirmed, and the endpoint returns the existing 409 "already confirmed".

**`POST /api/stripe/webhook`**

- Reads the raw body and checks the `Stripe-Signature` header with `STRIPE_WEBHOOK_SECRET` (the `stripe` package's verifier, which also rejects old timestamps). Bad or missing signature → **400**. No secret configured → **503**.
- Inserts `(provider, event_id, type)` into `payment_events` with `ON CONFLICT DO NOTHING` **in the same transaction as the handling**. Already there → **200**, nothing else. If handling fails, the whole transaction rolls back, the event isn't recorded, Stripe retries.
- Handles:
  - `checkout.session.completed` and `checkout.session.async_payment_succeeded` → `complete_deposit`.
  - `checkout.session.expired` → mark the deposit `expired` if it's still `open`. The booking is left to the hold rules.
  - `refund.updated` (and `charge.refund.updated` if that is what the pinned API version sends) → find the refund row and **re-read the refund's status from the provider** (not the event body), then update the row and `deposit_status`. **If the row doesn't exist yet** (Stripe can send this before our transaction that created the refund commits), return **503 without recording the event**, so Stripe retries it shortly.
  - Anything else → recorded, 200, ignored.
- Never confirms from the event body alone (see step 3 above).

**`POST /api/demo/checkout/{demo_session}`** with `{"outcome": "pay" | "decline"}`. **Only registered when the provider is `demo`**; otherwise it doesn't exist (404). `pay` marks the session paid and calls `complete_deposit`; `decline` returns 402 `{"detail": "Your card was declined (demo)"}` and changes nothing.

**Layering** as before: routes in `app/api/`, rules and the completion logic in `app/payments/` and `app/bookings/`, database access in repositories, `now` from `utc_now`.

## Frontend

Claude's calls.

- New dependencies: `@stripe/stripe-js` and `@stripe/react-stripe-js`. Stripe.js loads from `js.stripe.com`, as Stripe requires.
- **The details step** sends `/checkout` instead of `/confirm`. The `Hold` state gains the checkout result. BookPage's step gains a third kind, `paying`, holding the hold and the checkout.
- **The payment step** (`PaymentStep` component): the read-only summary, the countdown restarted from the checkout's `expires_in_seconds`, and either `EmbeddedCheckoutProvider` + `EmbeddedCheckout` with the client secret (stripe), or the demo box with **Pay £20 (demo)** and **Decline card (demo)** buttons (demo). Stripe's `onComplete` starts the status poll; it never navigates by itself.
- **Release on leaving** stays as Milestone 4 built it (`unreleased` ref, pagehide, unmount). A confirmed booking is never released, and the poll seeing `confirmed` clears `unreleased` before navigating.
- **On the payment step, the countdown, Change time and Change services await the release** and then make one `/status` call before deciding what to show (journey steps 5 and 6). `DELETE`'s 409 means a payment got in. Unmount and pagehide stay fire-and-forget.
- **The countdown reaching zero while the poll is running** waits for the poll's answer, like Milestone 4's confirm reply wins over the countdown.
- `loadStripe` is called once per publishable key, outside render.
- Unit tests replace the Stripe components with a stub that renders a "Pay" button calling `onComplete`, so no test loads Stripe.

## Testing

**Unit (pytest)**: `deposit_refundable` at, one second before and one second after the boundary, and for garage cancellations; the provider choice (key set / not set / production without key refuses); settings bounds for `payment_hold_minutes` and `deposit_amount_pence`; `StripeProvider` sends the parameters above (patch the `stripe` calls and assert their arguments, including idempotency keys and `expires_at`).

**Integration (Testcontainers PostgreSQL, fake provider)**:

- Migration `0006` upgrades and downgrades; existing confirmed bookings become `waived`; the new checks reject a confirmed booking with `unpaid`, a second open deposit, and a second refund of one deposit.
- `/checkout`: 200 shape, details saved, hold moved to 10 minutes, payment row with the setting's amount; a repeat returns the same session without extending; 404, 410, 409, 422 per field, 503 when the provider fails (and nothing saved).
- **Success**: a signed `checkout.session.completed` confirms the booking and marks it paid.
- **Failure**: a session the provider reports unpaid confirms nothing; a declined demo payment changes nothing; the hold then expires normally and the worker closes the session.
- **Duplicate**: the same event twice → one confirmation, one `payment_events` row, the second returns 200 having done nothing.
- **Out of order**: `checkout.session.expired` arriving after `completed` leaves the booking confirmed; a refund update before the refund row exists gives 503 and isn't recorded, and the same event sent again after the row exists updates it.
- **Refunds**: a refund the provider reports `pending` then `succeeded` (via the update event) ends `refunded`; one reported `failed` ends `refund_failed`, and a second refund of that deposit is then allowed by the index.
- **Late payment**: hold expired and released, time still free → confirmed. Time taken by someone else → refunded once, booking stays expired, `status` says `refunded: true`. Run the completion twice → still one refund.
- **Payment racing release**: `DELETE` while the provider's close reports "already completed" → booking confirmed (or refunded), never charged with nothing.
- Webhook: bad signature 400, no secret 503, unknown session 200 and ignored, a failure inside handling rolls back so the event can be retried.
- `/status` confirms through the provider when no webhook came.
- Worker: `run_once` closes open deposits of released holds and retries a failed close next cycle.
- Demo endpoint absent (404) when the provider is stripe.
- `cancel_booking`: refund when in time, none when late, always for the garage; a booking with no paid deposit cancels without a refund call.

Signed webhook requests are built in the tests with the test secret and the same HMAC scheme Stripe uses, from small JSON fixtures in `backend/tests/fixtures/stripe/` shaped like real events (ids and amounts only, no personal data).

**Frontend (Vitest, RTL)**: Continue to payment shows the busy state; the payment step shows the summary, the countdown from the new seconds, and the demo or stubbed Stripe box by `payment.provider`; completing starts polling and goes to the booked page on `confirmed`; the 30-second fallback message; the refunded message; countdown at zero while polling waits for the answer; leaving during payment releases the hold; the countdown reaching zero, or Change time, when the release reveals a payment that got in shows the booked page (or the refunded message), not "you haven't been charged".

**End to end (Playwright)**: the Milestone 4 test now pays: in Stripe's embedded form it enters an email, the card `4242 4242 4242 4242`, any future expiry, any CVC and a postcode, presses Pay, and sees the booked page with the deposit line. Locators use labels where Stripe provides them, so small form changes don't break it. If `STRIPE_PUBLISHABLE_KEY` isn't a test key, the test fails at the start with a clear message rather than silently using demo mode.

**Manual checklist** (in the setup guide): a declined card (`4000 0000 0000 0002`) shows Stripe's error; a card that asks for a 3-D Secure code (`4000 0025 0000 3155`) works inside the form; letting the payment step run out closes the form; the webhook appears in the Stripe dashboard as delivered.

## CI

- The `compose` job gets `STRIPE_SECRET_KEY` and `STRIPE_PUBLISHABLE_KEY` from GitHub repository secrets. It **fails with a clear message if either is missing**, so a misconfigured repo can't pass on demo mode.
- It installs a pinned Stripe CLI release, gets the webhook secret with `stripe listen --print-secret`, starts `stripe listen --forward-to localhost:8000/api/stripe/webhook` in the background, and starts Compose with that secret.
- Secrets aren't given to workflows from forks or to Dependabot PRs, so those runs of the `compose` job will fail. That is accepted for a single-owner repo, and noted in the README.
- The `backend` and `frontend` jobs need no keys.

## Stripe setup guide

A new `docs/stripe-setup.md`, linked from the README, written for someone who has never used Stripe: create a free account (no business details needed for test mode); find the test-mode publishable and secret keys; put them in `.env`; install the Stripe CLI and log in; run `stripe listen --forward-to localhost:8000/api/stripe/webhook` and copy its `whsec_…` into `.env` (optional locally: the status poll confirms without it); restart Compose; the test cards; adding the two keys as GitHub repository secrets for CI; the manual checklist. It says plainly that test keys move no money and that live keys must never go in `.env` files committed anywhere.

## Review focus

1. **Only `complete_deposit` confirms**, and only after re-reading the session from the provider. No path trusts the browser or the webhook body.
2. **Idempotency everywhere money moves**: duplicate events, repeated `/checkout`, completion reached from webhook, poll and close at once, and refunds (database index plus Stripe idempotency key).
3. **No paid deposit is lost**: every interleaving of payment, hold expiry, worker sweep and `DELETE` ends in a confirmed booking or a refund.
4. **Secrets**: the secret and webhook keys never appear in responses, logs, the frontend bundle, fixtures or the repository; the webhook verifies the signature on the raw body.
5. **Demo mode can't leak**: absent in production (startup refuses), absent in CI (the job fails without keys), and its endpoint doesn't exist when Stripe is configured.

## Housekeeping

- Branch `milestone5-deposit-payments` off an up-to-date `main`, merged through a PR.
- New dependencies: `stripe` (backend), `@stripe/stripe-js` and `@stripe/react-stripe-js` (frontend), the Stripe CLI in CI only.
- Two Milestone 4 deferred minors are fixed because this milestone touches them: the busy state on the submit button, and `restart: unless-stopped` on the worker. The others stay deferred.
- README: the payment step, demo mode versus real Stripe, a link to the setup guide, and the CI secrets note. SPEC.md's security checklist item on idempotent webhooks gets ticked when this merges.

## Left to the builder

- Exact module, function, component and test names, following the existing layout.
- The exact Stripe parameter and event names, checked against Stripe's current docs and the pinned API version.
- The wording of messages not fixed above, and the styling within the existing `App.css` look.
- How the payment step splits into components.
