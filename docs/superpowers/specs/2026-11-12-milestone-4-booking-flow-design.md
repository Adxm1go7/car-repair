# Milestone 4: Booking Flow with Slot Hold — Design

Nov 12, 2026 · Adam Ornoch

Spec: [docs/SPEC.md](../../SPEC.md), "Build order" item 4 and "Core user flows" flow 1. Builds on Milestone 3 ([design](2026-11-11-milestone-3-availability-design.md), [plan](../plans/2026-11-11-milestone-3-availability.md)).

## Intent

A customer can book instant services from their phone, with no account: tick the services, pick a day and a time, get that time held for them while they type their details, and confirm. This is the first time the site *does* something rather than shows something, and the first time real reservations land in the table that Milestone 3 protects.

Payment and email are deliberately left out. Milestone 5 turns "Confirm booking" into "Pay £20 deposit", and Milestone 6 sends the confirmation email. This milestone builds the booking record and the hold they will both hang off.

**Done when** flow 1 passes end to end in a real browser (a Playwright test against the Compose stack, run in CI), without payment, and an expired hold is released both by the worker and on the spot when someone else wants the slot.

## Goals

- A **`bookings` table** and a **`booking_items` table**. Each booking links to one reservation, and its items snapshot each service's name, price and duration.
- **`POST /api/holds`**: reserve a slot for some services and return a hold the browser can confirm.
- **`POST /api/holds/{reference}/confirm`**: attach the customer's details and car, and confirm the booking.
- **`DELETE /api/holds/{reference}`**: release your own hold when you go back to change the time.
- **Expired holds are released**: a **worker** process runs every minute, and the hold endpoint also releases expired holds before it reserves. Availability ignores expired holds even before they're released.
- A small **`GET /api/booking-policy`** so the page knows how many days ahead it may offer.
- **The public site's booking flow**: tick boxes on the services page, a time picker, a details form with a countdown, and a "you're booked" page.
- The project's **first end-to-end test** (Playwright), run in the CI `compose` job.

## Non-goals

- **Payment** of any kind (Milestone 5). Bookings go straight from held to confirmed.
- **Emails and the token link** (Milestone 6). The booking has no customer token yet.
- **Needs-approval services** (Milestone 8). They can't be ticked on the services page and the API refuses them.
- **Staff screens** (Milestone 7). Bookings can be seen only in the database for now.
- **Rate limiting, honeypot or CAPTCHA** on the forms (Milestone 9).
- Showing which days are fully booked before the customer taps them. Each day is loaded when tapped.

## Anti-goals

These would make the milestone a failure even if the happy path works:

- **A slot can be held or booked twice**, through any path. The Milestone 3 constraint stays the authority.
- **An expired hold keeps a slot from someone else.** That includes the gap before the worker runs.
- **A hold can be confirmed after it expires**, or by someone without its secret.
- **A confirmed booking can be released** by the worker, the hold-cancel endpoint, or the expiry sweep.
- **The countdown trusts the browser's clock** for when the hold ends, so a phone whose clock is five minutes out shows the wrong time left.
- **Hold length, booking window or cut-off hardcoded**, in the backend or the frontend.
- **Times shown in the browser's timezone** rather than the garage's.

## Decisions made with Adam

Adam approved the four-screen flow in the mockup. The details of it were Claude's suggestion:

1. **Services page**: the existing page gains a tick box on each instant service, and a sticky bar ("Choose a time · 2 services · 4h 30m") that leads to the time picker. Needs-approval services show "Needs approval — call us" and no tick box.
2. **Pick a time**: a horizontal strip of days from today to the end of the booking window, with closed days greyed out. Tapping a day loads its times, grouped into morning (before 12:00) and afternoon, each showing start and finish. With mixed bay types the page says the services must be booked separately and links back.
3. **Details**: choosing a time holds it straight away. A banner shows the held time and a countdown. The form asks for name, phone, email, registration, make, model and optional notes, then "Confirm booking". If the hold runs out, the page says the time was released and returns to the time picker.
4. **Booked**: the time, services, car, a short reference and the garage phone number.

Behind it: a worker releases expired holds every minute, the server treats an expired hold as gone even before then, and only the browser that made the hold can confirm it.

## Data model

All Claude's calls. Migration `0004`.

**`bookings`**

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | Never shown publicly. |
| `reference` | text, unique, not null | 8 characters from `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (no 0/O, 1/I/L), shown as `XXXX-XXXX`. Generated with `secrets`. Used in URLs and shown to the customer. It isn't a secret; the hold token is. |
| `reservation_id` | FK → `reservations.id`, unique, not null | The bay and the occupied range (including the buffer) live there. |
| `status` | text, not null | Check `IN ('held', 'pending_approval', 'confirmed', 'in_progress', 'completed', 'cancelled', 'no_show', 'expired')`, all the spec's statuses, so later milestones need no migration for them. This milestone uses `held`, `confirmed` and `expired`. |
| `start_at`, `end_at` | timestamptz, not null | The customer-facing start and real end (no buffer), from `ReserveResult`. Check `start_at < end_at`. |
| `hold_expires_at` | timestamptz, nullable | Set while `held`. Check: `status <> 'held' OR hold_expires_at IS NOT NULL`. |
| `hold_token_hash` | text, nullable | SHA-256 hex of the hold token. Check: `status <> 'held' OR hold_token_hash IS NOT NULL`. Kept after confirming, so a repeated confirm can be recognised (see API). |
| `customer_name`, `customer_phone`, `customer_email`, `car_registration`, `car_make`, `car_model` | text, nullable | Empty while held. Check: when `status = 'confirmed'`, all six are not null. |
| `notes` | text, nullable | |
| `created_at` | timestamptz, default now | |
| `confirmed_at` | timestamptz, nullable | |

- Index on `(status, hold_expires_at)` for the expiry sweep.
- **`deposit_status`** and the customer **token hash** for the email link are left for Milestones 5 and 6, which add them with their own migrations.

**`booking_items`**

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `booking_id` | FK → `bookings.id`, `ON DELETE CASCADE`, not null | |
| `service_id` | FK → `services.id`, not null | |
| `service_name` | text, not null | Snapshot. |
| `price_from_pence`, `price_to_pence` | integer, `price_to_pence` nullable | Snapshot. Same checks as `services`. |
| `duration_minutes` | integer, not null, > 0 | Snapshot. |
| `position` | integer, not null | The order the customer picked them in. Unique per booking. |

**Settings**: none new. The hold uses the existing `slot_hold_minutes` (10). It must be a whole number from 1 to 1440, or the hold endpoint gives 503.

## Holds and expiry

**A hold is a booking in status `held`, with an active reservation.** These rules keep it honest:

- **"Expired"** means `status = 'held' AND hold_expires_at <= now`. That single rule lives in one repository function, and everything else uses it.
- **Releasing** an expired hold sets the booking to `expired` and its reservation's `active` to false, in one transaction. The row is kept as history. The function is `release_expired_holds(session, now) -> int` and returns how many it released. It updates only rows that match the expired rule at that moment, so a hold that was just confirmed is never touched.
- **Availability ignores expired holds** even before they're released. `day_availability` leaves out reservations whose booking is expired by the rule above, using the `now` it's given. Without this, the slot would look taken for up to a minute after its hold ran out.
- **Creating a hold releases expired holds first**, in the same transaction, before calling `reserve()`. This matters because the exclusion constraint can't know about time: an expired hold's reservation is still `active` until something flips it, and would make the insert fail.
- **The worker** is a new Compose service, `worker`, built from the backend image with the command `python -m app.worker`. It calls `release_expired_holds` with the real time every `WORKER_INTERVAL_SECONDS` (environment variable, default 60), commits, and logs the count when it's above zero. It stops cleanly on SIGTERM. It uses a plain loop, not a scheduler library. Milestone 6's reminders can move it to one if they need it. One cycle is a function, `run_once(session, now) -> int`, so it can be tested without the loop.
- **Confirming** locks the booking row (`SELECT … FOR UPDATE`) and checks the status and expiry under that lock, with `now` from the request. The worker's update and the confirm can't both win: whichever gets the row first decides.

**The hold token**: 32 random bytes from `secrets.token_urlsafe`, returned once in the hold response and stored only as a SHA-256 hash. The browser keeps it in memory (React state), so reloading the page loses the hold and it expires normally. Compare hashes with `hmac.compare_digest`.

## API

All public, no login. Every 422 has a **string** `detail` (see "Housekeeping").

**`GET /api/booking-policy`** → `200 {"booking_window_days": 60, "slot_hold_minutes": 10}`. 503 when either setting is missing or invalid.

**`POST /api/holds`**

```json
{ "services": ["full-service", "front-brake-pads"], "start": "2026-11-12T08:30:00+00:00" }
```

- Validates `services` exactly as `GET /api/availability` does: same rules, same messages, same limits (move the checks into one shared function rather than copying them). It also **rejects needs-approval services** ("This service needs approval — please call us").
- `start` must be an ISO datetime **with an offset** (422 without one). Its local date in the garage timezone must pass the same today/booking-window checks as availability.
- Releases expired holds, then calls `reserve()` with the services' ids in the customer's order.
- **201**:

```json
{
  "reference": "7K3Q-M2PX",
  "hold_token": "…",
  "expires_at": "2026-11-12T08:40:00+00:00",
  "expires_in_seconds": 600,
  "start": "2026-11-12T08:30:00+00:00",
  "end": "2026-11-12T13:00:00+00:00",
  "services": [{ "slug": "full-service", "name": "Full service", "duration_minutes": 180, "price_from_pence": 21900, "price_to_pence": null }]
}
```

  Times are garage-local with offset, formatted like availability. **`expires_in_seconds` is what the countdown uses**: the page counts down from it using its own timer, so a wrong phone clock doesn't matter.

- **422** `{"detail": "These services can't be booked together — please book them separately"}` when they need different bay types. The route checks this before reserving, so the customer isn't told the time was "taken".
- **409** `{"detail": "That time has just been taken"}` on `SlotUnavailable`. That includes a start that isn't one of the day's slots, such as one off the grid. The client only ever sends starts it was offered, so the most likely cause is a race.
- **503** when a needed setting is missing or invalid.

**`POST /api/holds/{reference}/confirm`**

```json
{
  "hold_token": "…",
  "name": "Sam Driver", "phone": "07700 900123", "email": "sam@example.com",
  "registration": "ab12 cde", "make": "Ford", "model": "Focus", "notes": ""
}
```

- **404** `{"detail": "Booking not found"}` when the reference is unknown **or the token doesn't match**, so the endpoint never reveals whether a reference exists.
- **410** `{"detail": "Your hold has expired"}` when the booking is held but past `hold_expires_at`, or already `expired`. If it's past its time but still `held`, the endpoint releases it there and then.
- **200** with the booking summary when confirmed. **If it's already confirmed and the token matches, it returns 200 with the same summary and changes nothing**, so a double tap or a retry after a dropped connection is safe.
- Summary shape: `reference`, `status`, `start`, `end`, `services` (as above, from the snapshots), `registration`, `make`, `model`.

**Field rules** (Claude's call; the frontend checks the same rules before sending, and the server is the authority). Leading and trailing whitespace is trimmed before checking, and empty optional notes become null:

| Field | Rule | Stored as |
| --- | --- | --- |
| name | 1–100 characters | as typed |
| phone | 7–20 characters, only digits, spaces, `+`, `(`, `)`, `-`, with at least 7 digits | as typed |
| email | ≤ 254 characters, one `@`, a dot in the part after it, no spaces | lower-cased |
| registration | 2–8 letters or digits after removing spaces | upper-case, spaces removed |
| make, model | 1–50 characters each | as typed |
| notes | ≤ 1000 characters, optional | as typed |

No new dependency for email checking. It's a sanity check, not proof that the address works; Milestone 6's email does that.

**`DELETE /api/holds/{reference}`** with body `{"hold_token": "…"}` → **204**. It releases a `held` booking: status `expired`, reservation inactive. It's idempotent: an already-expired hold also gives 204. Unknown reference or wrong token → 404. A confirmed booking → **409** `{"detail": "This booking is already confirmed"}`, and nothing changes. The page calls it when the customer presses "Change time" on the details step, so their own hold doesn't hide the slot from them.

**Layering**, as in Milestones 2 and 3: routes in `app/api/holds.py` do validation and HTTP. The hold, confirm and release rules live in a service module (`app/bookings/`) that calls the repositories. `now` always comes from the `utc_now` dependency.

## Frontend

All Claude's calls.

- **Routing**: add `react-router` (library mode, one new dependency). Routes are `/` for the services page, `/book?services=a&services=b` for the time picker and details steps, and `/booked/:reference` for the confirmation. nginx already sends unknown paths to `index.html`.
- **Selections** live in the URL of `/book`, so a reload of the time picker works. "Change services" goes to `/?services=…`, which pre-ticks those boxes.
- **The details step and the hold** are state inside the `/book` page, not their own URL. A reload there loses the hold, which then expires normally.
- **The confirmation page** gets the summary from navigation state. On a direct visit or reload, with no state, it shows "Your booking reference is XXXX-XXXX. Call us if you need to change it." with the phone number. There is no public GET for a booking until Milestone 6's token link.
- **The day strip** is built from `/api/booking-policy` and the opening hours already loaded, with "today" worked out in the garage timezone. Closed weekdays are disabled. The first open day is selected on arrival.
- **Times** are formatted in the garage timezone, using `Intl.DateTimeFormat` with `timeZone` set to the garage's zone, like the Milestone 2 "open today" code.
- **If the hold call returns 409**, the page reloads that day's times and shows "Sorry, someone just took that time." The 410 on confirm, and the countdown reaching zero, both return to the time picker with "Your hold ran out, so we released that time." The customer's typed details are kept in state, so they don't have to type them again.
- **Accessibility**: real `<input type="checkbox">` and `<button>` elements, labels on every field, errors linked with `aria-describedby`, and the countdown announced politely (`aria-live="polite"`) only at 5 minutes, 1 minute and expiry, not every second.

## Testing

**Unit (pytest)**: the field rules (each boundary), reference generation (alphabet and length), and the "expired" rule at exactly `hold_expires_at` (expired) and one second before (not).

**Integration (Testcontainers PostgreSQL)**:

- Migration `0004` upgrades and downgrades. The check constraints reject a held row with no expiry or token hash, and a confirmed row with missing details.
- `POST /api/holds`: 201 shape, items snapshot the service values, a reservation exists. 409 when the slot is taken, and for a start not on the grid. 422 for every availability validation case, mixed bay types, a needs-approval service, and a start with no offset. 503 with a broken `slot_hold_minutes`.
- **Two holds race for the MOT bay's only slot** with separate connections and a barrier: one 201, one 409. Several rounds, like Milestone 3.
- **Expired hold freed on the spot**: hold at `now`, then with `now + hold + 1s` the slot appears in availability, and a second `POST /api/holds` for it succeeds, before any worker runs. The first booking ends up `expired` with its reservation inactive.
- Confirm: 200 and the stored values (normalised registration, lower-cased email). A repeat confirm gives 200 and changes nothing. A wrong token or unknown reference gives 404. A late confirm gives 410 and releases the hold. Each field rule gives 422.
- **Confirm racing the sweep**: with the hold one second from expiry, run the confirm and `release_expired_holds` on separate connections. The booking ends up either confirmed with an active reservation, or expired with an inactive one, never a mix.
- `release_expired_holds` leaves confirmed bookings and unexpired holds alone. `run_once` returns the count.
- `DELETE`: 204, idempotent, 404 on a wrong token, and 409 for a confirmed booking.
- `GET /api/booking-policy` shape and 503.

**Frontend (Vitest, React Testing Library)**: ticking services updates the bar's count and total. Needs-approval services have no tick box. The day strip disables closed days and starts on today in the garage timezone, tested with a `now` just after midnight UTC on a BST date. Times show in garage time. The countdown runs from `expires_in_seconds` with fake timers and returns to the picker at zero. A 409 shows the "just taken" message. The form shows field errors and keeps typed values after a hold runs out.

**End to end (Playwright, Chromium only)**: in a new `e2e/` folder at the repository root, with its own `package.json`. Against the running Compose stack at `http://localhost:8080`: tick one instant service, open the time picker, choose the first offered time on the first day that has one, fill in the form, confirm, and see the reference on the booked page. Then check the API: the same time is no longer offered. In CI it runs in the `compose` job after the smoke checks, with the Playwright report uploaded as an artifact on failure.

## Review focus

1. **The gap between expiry and release**: availability, the hold endpoint and confirm all use the same "expired" rule and the same injected `now`, and nothing reads the real clock except `utc_now` and the worker.
2. **Confirm versus sweep**: the row lock really serialises them, and the sweep's update re-checks the status, so a just-confirmed booking can't be expired.
3. **Token handling**: the token is never stored or logged in plain text, the comparison is constant-time, and a wrong token gives the same 404 as an unknown reference.
4. **Countdown and timezone on the page**: the countdown uses `expires_in_seconds`, never the phone's clock, and the day strip's "today" is the garage's, around midnight and on clock-change days.
5. **Idempotency**: a double-tapped "Confirm booking", or a "Change time" after the hold already expired, gives the friendly result, not an error.

## Housekeeping

- Work goes on a new branch, `milestone4-booking-flow`, off an up-to-date `main`, and merges through a PR.
- **Two deferred minors from the Milestone 3 review** are fixed here, because this milestone is the first to call them from a public route:
  - `reserve()` raises `ValueError` on **duplicate service ids**, instead of silently merging them and giving a shorter job.
  - **422 responses get one shape**: an exception handler turns FastAPI's request-validation errors into `{"detail": "<field>: <message>"}`, using the first error. Existing tests that expect the list shape are updated.
- New dependencies: `react-router` in the frontend, and `@playwright/test` in `e2e/`. Nothing new in the backend.
- The README's Quick start gains the booking page (`http://localhost:8080`), how to run the end-to-end test, and the worker in the list of services.

## Left to the builder

- Exact module, function, component and test names, as long as they follow the existing layout.
- How the time picker and the form split into components.
- The visual styling, within the existing `App.css` look.
- The wording of messages that aren't fixed above.
