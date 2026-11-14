# Milestone 6: Email and Booking Links — Design

Nov 14, 2026 · Adam Ornoch

Spec: [docs/SPEC.md](../../SPEC.md), "Build order" item 6 and "Core user flows" flow 4. Builds on Milestone 5 ([design](2026-11-14-milestone-5-deposit-payments-design.md)).

## Intent

After paying, a customer gets an email with a private link to their booking. The link opens the booking with no login. From there they can cancel it while they are still inside the free-cancellation window, and get their deposit back. **Customers cannot reschedule.** The garage wants to be phoned for a different time, so the page steers people towards calling rather than cancelling and rebooking. Two days before the visit, the customer gets a reminder.

Emails are queued in the database in the same transaction as the change that causes them, and the worker sends them. Sending mail never slows down or breaks a booking, and an email is never lost because a process restarted.

**Done when** flow 4 (as changed below) passes end to end in CI: pay → the confirmation email arrives in Mailpit → open its link → cancel → the cancellation email arrives and the deposit is refunded. Integration tests also show that an expired, wrong or already-used link fails safely and changes nothing.

## Change to the spec

Adam decided that **customers cannot reschedule** (Nov 14). Update `docs/SPEC.md` as part of this milestone:

- Decisions log, "Customers": the token link lets them view or cancel one booking. To change the time, they phone the garage.
- Flow 4: remove "or reschedule". Step 2 becomes "cancel while inside the policy window, and the deposit is refunded" (drop "or forfeited": a customer can't cancel inside the window). Outside the window, the page shows the phone number (unchanged).
- Features "In v1": token self-service is "view and cancel". Emails: remove "reschedule" as a customer email. The garage-initiated change email stays (Milestone 7).
- Open questions: tick "Reschedule rules", answered as "no customer rescheduling".
- Domain model: add `BookingLink` (below). `EmailLog` gains the queue fields.

## Goals

- **Email sending behind an interface** (`EmailSender`): SMTP to Mailpit locally, and a fake in tests. SMS can be added later beside it (spec).
- **An `email_log` table that is both the queue and the send log.** Each row is one email, with status `queued` → `sent`, or `failed` after several tries.
- **Three emails**, each with an HTML and a plain-text version (Jinja2, HTML autoescaped):
  - **Confirmation**: queued when a booking becomes confirmed by its deposit (`complete_deposit`, every path: webhook, poll, demo, late payment that gets its time back). It includes the booking link.
  - **Cancellation**: queued when the customer cancels from the link. It says whether the deposit is being refunded.
  - **Reminder**: queued by the worker `reminder_hours_before` (48, a new setting) before the start, for confirmed bookings only. It includes the booking link.
- **Booking links**: a random token, stored only as a hash in a new `booking_links` table, that opens one booking and expires.
- **The booking page** at `/booking/:reference`: view, cancel inside the window, and the phone number everywhere else.
- **A customer cancel endpoint** that calls the existing `cancel_booking(..., by="customer")` in [service.py](../../../backend/app/payments/service.py).
- **An e2e test** for flow 4 that reads the emails from Mailpit's API.

## Non-goals

- **Customer rescheduling.** See above.
- **Garage-initiated cancel or move emails, and "car ready"** (Milestone 7, which needs the staff screens). The email machinery built here should make them a template plus one queue call.
- **Emails for needs-approval bookings and enquiries** (Milestone 8).
- **An email when a late payment is refunded automatically** (the time had gone). The customer is told on the page, as now. *Claude's call*: it's rare, and it can be added later as one more template.
- **Resending a lost link** ("email me my link again"). The customer phones the garage.
- **A hosted email provider and its settings** (Milestone 10). SMTP settings are environment variables, so switching later is configuration only.
- **Rate limiting the link endpoints** (Milestone 9). The tokens are 256-bit random values, so guessing one isn't practical.
- Branding the emails beyond the garage name and contact details from settings.

## Anti-goals

These would make the milestone a failure even if the happy path works:

- **A booking fails, rolls back or slows down because email is down.** Sending happens only in the worker.
- **An email is queued for a change that was rolled back**, or a committed change loses its email. The queue row is written in the same transaction.
- **A plain token is stored anywhere**: in the database (including the queued email), in the logs, or in server access logs through a query string.
- **A link opens or changes any booking other than its own**, or still changes anything after it has expired.
- **A customer cancels inside the 24 hours from the link**, or gets a refund the rule doesn't allow.
- **The same reminder is sent twice** for one booking. A database constraint prevents it.
- **Garage name, phone or colours are hardcoded** in the emails or the page. They come from settings or `/api/garage` (see the multi-garage direction).

## Decisions made with Adam

1. **No customer rescheduling.** Adam wants customers who need a different time to talk to the garage. After a cancellation the page shows the phone number, not a "book again" button, and the cancel confirmation tells people to call if they only want to move the booking.
2. **Include the reminder email** in this milestone.
3. **Email is queued in a database table and sent by the worker** (chosen over sending right after the response with FastAPI background tasks, and over a Celery/RQ job queue with Redis).

## Approaches considered for sending email

| Approach | Trade-off |
| --- | --- |
| **Queue table, sent by the worker (chosen)** | Never lost, never blocks a booking, rolled back with its change, and it doubles as the spec's send log. Emails go out after a short delay. |
| FastAPI background tasks after the response | Instant and less code, but lost on a restart, no natural retry, and reminders need the worker anyway. |
| Celery or RQ with Redis | The standard setup at scale. Adds a service to Compose, CI and hosting, which is too much for one garage. |

## The customer's experience

### Booking page `/booking/:reference#t=<token>`

The token is in the URL **fragment**, so it never reaches the server's access logs or another site's `Referer` header. The page reads it and posts it to the API. *Claude's call.*

```text
  Your booking  ABCD-EFGH
  Sat 21 Nov, 09:30 – 11:00
  Full service, MOT
  Car: AB12 CDE · Ford Focus
  Deposit: £20 paid

  Need a different time? Call us on 01234 567890
  and we'll sort it out.

  [ Cancel booking ]
```

What the page shows depends on the booking:

| State | Shown |
| --- | --- |
| Confirmed, more than `free_cancellation_hours` before the start (exactly at the boundary counts, as in `deposit_refundable`) | Summary, the "call us for a different time" line, and **Cancel booking** |
| Confirmed, inside the window | Summary and "To change or cancel, please call us on …". No cancel button. |
| Cancelled | Summary, marked cancelled, with the deposit state ("refund on its way" for `refund_pending`, "refunded", or "kept" when no refund was due), plus the phone number |
| In progress, completed, no show | Summary, its state and the phone number. Nothing can be changed. (Staff set these states in Milestone 7.) |
| Link wrong, expired or missing | A safe message, "This link isn't valid any more. Please call us on …", with no booking details |

The page doesn't trust its own clock for the window. The API says whether cancelling is allowed.

**Cancel step.** Pressing *Cancel booking* opens a confirmation in the page:

> Cancel your booking on Sat 21 Nov at 09:30? You'll get your £20 deposit back.
> If you just need a different time, please call us on 01234 567890 instead and we can move it for you.
> [ Yes, cancel it ]  [ Keep my booking ]

After cancelling, the page shows the cancelled state above. If the refund can't be started because Stripe is unreachable, nothing changes and the page says "We couldn't cancel just now. Please try again, or call us on …".

### Emails

Each email has a subject, an HTML version and a plain-text version. All of them include the reference, date and time in garage-local time, the services, the car, and the garage's name, phone and address from `garage_contact`.

- **Confirmation**: "Your booking is confirmed", the £20 deposit paid and the balance due at the garage, the booking link, and "you can cancel free of charge until {start − 24h}; after that, please call".
- **Reminder**: "See you on {day}", the booking link and the phone number. *Claude's call*: at 48 hours before, the customer still has about a day to cancel for free, so the email says until when.
- **Cancellation**: "Your booking is cancelled", whether the deposit is being refunded, and the phone number to book again.

## Data model

Migration `0007`. Both tables go through `get_session`, like everything else.

### `booking_links`

| Column | Notes |
| --- | --- |
| `id` | |
| `booking_id` | FK to bookings |
| `token_hash` | SHA-256 of the token, unique. The existing `hash_token` / `token_matches` in [rules.py](../../../backend/app/bookings/rules.py) are reused. |
| `expires_at` | The booking's `end_at` + 7 days (*Claude's call*, so the customer can still look it up after the visit) |
| `created_at` | |

**Why a separate table rather than a column on `bookings`:** the plain token must never be stored, so the queued email can't hold a link. Instead, the **worker creates a fresh token when it sends** an email that needs a link, writes its hash here, and puts the plain token into that one email only. The confirmation and the reminder each get their own token, and both work. `hold_token_hash` stays as it is, for the hold.

Looking a link up: find the row by `hash_token(token)` (a unique index makes this one lookup), check `expires_at > now` and that the reference in the URL matches the booking. Any failure gets the same "not valid" response, so a guess learns nothing.

### `email_log`

| Column | Notes |
| --- | --- |
| `id` | |
| `template` | `confirmation`, `reminder` or `cancellation` (check constraint, extended in later milestones) |
| `booking_id` | FK to bookings (nullable, ready for enquiry emails in Milestone 8) |
| `recipient` | The address at queue time |
| `status` | `queued`, `sent` or `failed` |
| `attempts` | How many sends have been tried |
| `next_attempt_at` | When the worker may try next. A queued row is due when this is at or before now. |
| `last_error` | Short text of the last failure, without the message body |
| `created_at`, `sent_at` | |

A **partial unique index on `(booking_id, template)` where `template = 'reminder'`** makes a second reminder for the same booking impossible. Confirmation and cancellation happen once per booking because of the status changes that cause them. Storing no body is intentional: the email is rendered at send time from the booking, so the link token never touches the database and the content can't go stale. Mailpit holds the rendered copies for debugging.

### New setting

`reminder_hours_before`: 48, added to `DEFAULT_SETTINGS`, read through a helper like `load_free_cancellation_hours`. Existing databases get it from the seed command, which inserts missing keys.

## Sending

- **`queue_email(session, template, booking)`**: adds a `queued` row and flushes. No commit. It's called from `complete_deposit` when it confirms a booking, and from the customer cancel service.
- **The worker gets an email step**, run every `EMAIL_INTERVAL_SECONDS` (default 5). The hold release and payment closing keep running every `WORKER_INTERVAL_SECONDS`. The builder decides the loop structure. For each due row (`FOR UPDATE SKIP LOCKED`, oldest first, small batches), it:
  1. loads the booking, and for linked templates creates a `booking_links` row;
  2. renders the template;
  3. sends it through `EmailSender`;
  4. marks the row `sent` and commits, one row at a time.

  A failed send rolls back the link, increments `attempts`, stores `last_error`, and pushes `next_attempt_at` back (for example 1, 5, 15, 60 minutes). After 5 attempts the row is marked `failed` and logged as an error. Because the commit comes after the send, a crash between them can send an email twice. That's accepted: it's at-least-once delivery, and a duplicate confirmation is harmless.
- **Reminders are queued by the worker**: confirmed bookings where `start_at − reminder_hours_before ≤ now < start_at`, `confirmed_at < start_at − reminder_hours_before` (booked earlier than that), and no reminder row yet. The unique index is the real guard. If a booking is cancelled before its queued reminder goes out, the reminder is not sent (see "Left to the builder").
- **`EmailSender` protocol**: `send(message)`. `SmtpSender` uses the standard library `smtplib`. The builder decides whether it runs blocking in the worker thread (fine at this volume). Tests use a fake that records messages, and one integration test sends to a real Mailpit container or SMTP stub.
- **Configuration** (environment): `SMTP_HOST`, `SMTP_PORT` (already passed to the api; now also to the worker), `SMTP_FROM` (for example `bookings@example.test`), and `PUBLIC_BASE_URL` (for example `http://localhost:8080`), used to build the link. Username, password and TLS settings are left for Milestone 10.

## API

Both endpoints are POST, with the token in the JSON body, so it isn't in a URL.

- **`POST /api/bookings/{reference}/view`**, body `{ "token": "..." }` → the summary (as on the booked page), the status, the deposit status, `can_cancel` (bool), `refund_if_cancelled` (bool) and `free_cancellation_until` (garage-local). Wrong, expired or mismatched link → **404** "This link isn't valid".
- **`POST /api/bookings/{reference}/cancel`**, body `{ "token": "..." }`. Locks the booking. Only `confirmed` bookings inside the window can be cancelled: otherwise **409** with a reason the page can show (`too_late`, `not_cancellable`). It calls `cancel_booking(by="customer")` and `queue_email("cancellation")`, then commits. If `PaymentUnavailable` is raised, it rolls back and returns **503**, and nothing changes. A repeated cancel of an already cancelled booking returns **409 `not_cancellable`** and changes nothing. That's the "used link fails safely" case.

## Testing

- **Unit**: the cancel-allowed rule at and around the boundary; link expiry; template rendering (HTML escaping of a name such as `<script>`, garage-local times across a clock change, refund and no-refund wording); retry backoff.
- **Integration** (real Postgres, injected clock):
  - confirming a booking queues exactly one confirmation, on every confirm path, and a rolled-back confirm queues none;
  - the worker sends queued mail, creates a link, and marks the row sent;
  - a failing sender retries, then marks the row `failed`;
  - reminder queuing: booked well ahead (queued once, even over many cycles), booked inside 48 hours (never), cancelled (skipped);
  - view and cancel with a good, wrong, expired and other-booking token;
  - cancel inside the window (409, no change), cancel twice (409), refund unavailable (503, no change, no email queued);
  - the refund happens and the deposit status moves on.
- **Frontend** (Vitest): each page state in the table above, the confirm dialog, the 409 and 503 messages, and a missing `#t=` fragment.
- **E2E** (Playwright, CI through the real Stripe test form as today): book and pay → poll Mailpit's API (`http://localhost:8025/api/v1/...`) for the confirmation sent to the test's unique address → open the link → cancel → the cancellation email arrives → the page shows the refund. One more short test opens a made-up link and sees the safe message. The reminder isn't in e2e: it's covered by integration tests with the clock.

## Left to the builder

- How the worker runs the two intervals (one loop with a short tick, or two timers).
- What happens to a queued reminder whose booking was cancelled: a `skipped` status, or checking the booking status at send time and marking it so. Either way it must not be sent and must still be visible in the log.
- The retry delays and the attempt limit (around 5).
- The email's visual layout. Keep it simple, with inline styles, and use the garage's details from settings.
- **Claude's calls from the review** (settled, not open):
  - Deposit and refund wording on the page, in the cancel dialog and in the emails comes only from `deposit_status` and `refund_if_cancelled`, never assumed. So a `waived` booking (dev data from before migration 0006) gets no "£20 back" line.
  - `refund_failed` is shown as "We'll be in touch about your refund", with the phone number, on the page and in the cancellation email.
  - Any queued email whose booking is no longer in a state it applies to (a reminder or confirmation for a cancelled booking) isn't sent and stays visible in the log. The same rule covers staff cancellations in Milestone 7.
  - The flow 4 e2e test books a day at least two days ahead, so the cancel button shows. After cancelling, it accepts "refund on its way" or "refunded", because the refund webhook may arrive later.
- Whether the booked page (`/booked/:reference`) mentions "we've emailed you a link to manage your booking".
- File layout, following the existing `api / services / repositories` pattern (likely `app/email/` for the sender, templates and queue).
- Adding `jinja2` to the backend dependencies.

## Deferred minors carried from Milestone 5

These aren't part of this milestone unless they get in the way. They're listed so they aren't lost: a retried checkout create can hit `IdempotencyError`; the worker and close ignore `payment.provider` after switching between demo and Stripe; Stripe mode with a null `client_secret` falls back to the demo box; production should refuse to start without `STRIPE_WEBHOOK_SECRET` (Milestone 10); e2e doesn't assert that webhooks arrive; `demo_pay` reads the status before the lock; and from Milestone 4: the picker returns to the first open day after expiry, a stale "today" past midnight, and a raw field name on a non-form 422.
