# Milestone 10b: Polish — Design

Nov 20, 2026 · Adam Ornoch

Spec: [docs/SPEC.md](../../SPEC.md), "Security, reliability and privacy checklist" and "Build order" item 10b. Builds on 10a (PR #11). It changes no booking flows.

## Intent

The app is a portfolio piece that must show professional standards. 10b is the last polish before deployment (Milestone 11), kept **basic, nothing too extensive or niche** (Adam, Nov 20). SPEC.md says 10b is done when the checklist is fully ticked, so every item below exists to make a checklist line true and provable.

**Done when:**
- An unknown address on either site shows a proper "page not found" page, and a crash in either site shows a "something went wrong" screen instead of a blank page.
- Every API log line and every worker log line is one JSON object, with one line per request.
- An automated accessibility check passes on the main pages, in CI.
- A load test of the availability lookup has been run and its result is in the README.
- A privacy note page exists, and a daily worker job blanks customer details 12 months on.
- Every checklist line in SPEC.md is ticked with a "proven by" pointer, except HTTPS, which moves to M11 (below).

## Goals

- A visitor who mistypes an address or hits a bug still sees the garage's site and a way back.
- Logs a machine can search, and that never contain a customer's email or phone.
- Pages that work with a keyboard and a screen reader, checked automatically so they stay that way.
- One honest number for how the availability lookup holds up.
- Old customer data doesn't stay forever.

## Non-goals

- Log shipping, dashboards, metrics or tracing. Logs go to standard output only.
- A full accessibility audit or manual screen-reader testing. Axe plus fixes for what it finds.
- Load testing in CI, or of any other endpoint.
- Deleting rows, a customer "delete my data" request flow, or a cookie banner. The app sets no tracking cookies.
- A styled backend error page. The API already returns JSON errors.
- The older deferred minors from earlier milestones.

## Anti-goals

- A log line that leaks a customer's email, phone or token. Query strings are never logged.
- A cleanup that breaks a database rule, the staff pages, or the audit log's history.
- A cleanup that touches a booking still in progress, or that changes anything when run twice.
- An accessibility test so strict that it fails on harmless issues, or that fixes problems by hiding content.
- A crash screen that shows a stack trace to customers.

## Decisions made with Adam

- The scope list from the end of 10a was agreed (Nov 20).
- The 12-month rule **blanks out the person** and keeps the row (Nov 20). It doesn't delete records.
- The checklist line "CORS, security headers and HTTPS settings in the deployed environment" is **split in two** (Nov 20): "CORS and security headers" is ticked in 10b, and "HTTPS in the deployed environment" is left unticked for Milestone 11.
- JSON logs use **our own small formatter on Python's standard logging** (approach A, Nov 20).
- The load test is **a short Python script using httpx** (approach A, Nov 20).
- Retention also blanks the staff-typed audit reasons and enquiry decline reasons (Nov 20).
- "Mobile-first layout" is ticked from the CSS, with no phone-width test (Nov 20).
- The rest of this design (below) was proposed by Claude and accepted by Adam as a whole ("sounds good", Nov 20). Points marked *Claude's call* were added later.

## Approaches considered

**Retention**
- **Blank out the person (chosen).** Replace the personal fields with placeholders and keep the row. Schedule history, counts, the audit trail and email history stay whole, and the database rules still hold.
- **Delete the record.** Simpler to describe, but it leaves gaps in the audit log and email log, and every foreign key (reservations, items, payments, links, enquiries) needs handling.

**JSON logs**
- **A. Own formatter on standard logging (chosen).** About 40 lines and no new dependency. The six existing loggers switch over with one setup call.
- **B. structlog.** A nicer API, but a new dependency and the existing loggers need rewriting or bridging.
- **C. python-json-logger.** A small dependency doing what A does. Owning 40 lines costs less.

**Load test**
- **A. Python script with httpx (chosen).** httpx is already a dependency, and the script lives in the repo.
- **B. Locust.** A new dependency with a web UI. Too much for one endpoint.
- **C. k6.** A second toolchain (separate binary, JavaScript) for one measurement.

## Design

### 1. Error pages (frontend)

- **Customer "page not found":** a new `*` route in `CustomerApp`'s `<Routes>` (frontend/src/App.tsx). It shows a heading "Page not found", one line of text, and links to Home (`/`) and Book (`/book`), with its own `<header>`/`<main>` like the other customer pages (there is no shared customer layout today). *Claude's call:* like every customer page, it sits behind `CustomerApp`'s catalogue load, so while the catalogue loads or fails an unknown address shows "Loading…" or the load error. That's accepted; routes aren't restructured for it.
- **Staff "page not found":** replaces the bare `<p>Page not found</p>` at frontend/src/staff/StaffApp.tsx:142, inside the staff layout, with a link back to the schedule (the staff home route).
- **"Something went wrong":** one React error boundary component (a class component, the only kind React allows), wrapped around both apps in `App.tsx`. It shows "Something went wrong", a line saying the problem wasn't the visitor's fault, a "Reload" button and a "Go to home page" link (`/staff` inside the staff site, `/` otherwise). It never shows the error text. It logs the error with `console.error`.
- Each page sets a sensible document title and has one `<h1>`.
- Tests: Vitest tests for both not-found routes and for the boundary catching a throwing child.

### 2. Structured logs (backend)

- A new module, `app/logs.py`, with a `JsonFormatter` and a `configure_logging()` function that puts the formatter on the root logger, writing to standard output. Each line is one JSON object with `time` (UTC, ISO 8601), `level`, `logger` and `message`, plus any fields passed through `extra=`. An exception adds an `error` field holding the traceback as one string.
- Both the API (at startup in `app/main.py`) and the worker (`app/worker.py` `main()`) call `configure_logging()`. The existing loggers (`uvicorn.error`, `app.worker`, `app.email`, `app.webhook`, `app.bookings`, `app.payments`) keep their names and calls, and their output simply becomes JSON. Uvicorn's own loggers are pointed at the same handler so their startup lines are JSON too. App code also logs through `uvicorn.error` (main.py, holds.py, my_booking.py, staff_bookings.py, validation.py), so those messages are part of the "no customer details" check.
- **One line per request:** a small HTTP middleware logs, through logger `app.request`, `method`, `path` (no query string), `status`, `duration_ms` and a `request_id`. The request id is a random hex string, also returned in an `X-Request-ID` response header. Uvicorn's access log is turned off (`--no-access-log`, or the equivalent in the run config) so requests aren't logged twice.
- **One line per worker job:** each step of the worker loop (reminders, email sending, the holds step `run_once`, and the new retention job) logs one line. *Claude's call:* the holds step also clears expired sessions, old login attempts and old request counts and closes stale checkouts; it logs one line for the whole step, with a count field for each of those. Each line goes through `app.worker` with `job`, `count` and `duration_ms` when it handled at least one item, and an error line when it fails. *Claude's call:* quiet runs (count 0) aren't logged, because the email step runs every few seconds and would fill the log with nothing.
- Log messages must not contain customer emails, phones or tokens. Any existing message that does is changed to use the booking reference or the enquiry id.
- Tests: the formatter's output parses as JSON with the expected fields (including with `extra` and an exception), and a request produces one `app.request` line without the query string.

### 3. Accessibility check (e2e)

- New e2e dev dependency `@axe-core/playwright`, and one new spec, `e2e/tests/accessibility.spec.ts`.
- It runs axe (WCAG 2 A and AA rules) on:
  - **customer:** home (`/`), booking (`/book`, including the slot and details steps if reachable without paying), enquiry (`/enquiry`), my-booking (`/booking/:reference` through a real link), privacy (`/privacy`), and not-found;
  - **staff:** login, the day schedule, a booking detail page, and settings.
- The test fails on any violation of impact "serious" or "critical". Every one found is fixed in this branch, in the real markup (labels, contrast, landmarks, names), never by excluding the element. A rule may be disabled only with a comment saying why it's a false alarm.
- It runs in the existing e2e CI job against the compose stack, using the helpers in `e2e/tests/booking.ts` and `staff.ts`.

### 4. Load test (script + README)

- `backend/scripts/load_availability.py`: async httpx clients hammer `GET /api/availability?services=<a seeded service>&date=<next open day>` against the local stack. Defaults: 50 concurrent users for 30 seconds. Base URL, users and duration are command-line options.
- It prints the total requests, requests per second, error count, and the p50, p95 and p99 response times.
- The availability lookup has no rate limit in any environment (10a limits only hold, pay, request, enquiry and link), so the test isn't throttled.
- It's run by hand. The README gets a short "Load test" section with the command, the result, the date and the machine it ran on. It isn't run in CI.

### 5. Privacy note (frontend)

- A public page at `/privacy` in the customer site, linked from a small footer on every customer page and next to the submit button of the booking details form and the enquiry form ("How we use your details").
- **Content, in plain words:**
  - this is a demo garage and all data in it is fake;
  - what is collected: name, phone, email, car registration, make and model, and notes or the enquiry description;
  - why: to run the booking and contact the customer about it;
  - who sees it: garage staff only;
  - outside services: the email provider for booking emails, and Stripe for deposits (we never see card details);
  - how long: personal details are removed 12 months after the appointment, or 12 months after an enquiry that wasn't booked in;
  - who to contact: the garage's phone and email from the catalogue's garage details.
- It's a static page. No backend change.
- *Claude's call:* there is no shared customer layout today; each page renders its own `<header>`/`<main>`. The footer is added as one small `CustomerFooter` component rendered once by `CustomerApp` after its `<Routes>`, outside each page's `<main>`, so no page needs refactoring.

### 6. Retention: blanking customer details after 12 months (backend)

- **Migration 0013:** adds a nullable `details_removed_at` (timestamp with time zone) to `bookings` and to `enquiries`.
- **New module** `app/privacy/retention.py` with `remove_old_details(session, now) -> int`, called once a day by the worker (a new step, tracked like the holds step with its own last-run time; interval *Claude's call:* 24 hours, first run at worker start).
- **Which bookings:** `end_at < now - 12 months`, `details_removed_at IS NULL`, and status not in the waiting statuses (`held`, `pending_approval`, `awaiting_deposit`).
- **Which enquiries:** `details_removed_at IS NULL` and either `status IN ('new', 'declined')` with `created_at < now - 12 months`, or `status = 'converted'` and its booking is being (or has been) blanked. An enquiry that was booked in follows its booking.
- **What is blanked on each:**
  - *Claude's call:* every field below is replaced only where it was set. A booking that never got details (an expired hold) keeps its NULLs;
  - `customer_name` and `customer_phone` become `"removed"`;
  - `customer_email` becomes `"removed"` where it was set (a phone booking's empty email stays empty);
  - `car_registration` becomes `"REMOVED"` (it fits the 8-character column);
  - the booking's `notes` becomes NULL; the enquiry's `description` becomes `"removed"` (the column is NOT NULL);
  - car make and model are kept, because on their own they identify no one;
  - `details_removed_at` is set to `now`.
  - Placeholders rather than NULLs mean `confirmed_has_details` and the enquiry NOT NULL columns still hold, even for a booking still marked `confirmed`.
- **Linked data, in the same transaction:**
  - **Audit log:** in every `audit_entries` row (model `AuditEntry`) for that booking (`entity_type` booking, or matching `booking_reference`) or that enquiry, any customer field in `before` or `after` (name, phone, email, registration, notes, description) is set to `"removed"`. This covers the `booking.create` entry for phone and enquiry bookings, which stores the details through `asdict(details)` in app/schedule/phone.py.
  - **Email log:** for every `email_log` row of that booking or enquiry, `recipient` becomes `"removed"`, `context` becomes NULL, and `last_error` becomes NULL (*Claude's call:* an SMTP refusal message can contain the address). *Claude's call:* the builder should check whether a queued, unsent email could still need them. With a 12-month cutoff, none can, but a queued row is skipped rather than blanked if it exists.
  - **Free text staff typed** (Adam, Nov 20): the `reason` of those audit rows and the enquiry's `decline_reason` become `"removed"` where set. The audit log keeps who did what and when, but not why.
- **Twice is a no-op:** rows with `details_removed_at` set are never picked again.
- **Staff pages:** they show the stored values as they are, so "removed" appears in place of the details. No other change, unless a page breaks on the placeholder (the builder checks the booking detail, schedule and enquiry pages).
- The job logs one line with how many bookings and enquiries it blanked.
- Tests: an old booking and enquiry are blanked, along with their audit and email rows; recent ones, waiting ones and a second run are untouched; a blanked confirmed booking still passes the database rules; a converted enquiry follows its booking.

### 7. Checklist and docs

- **SPEC.md checklist:** every line is ticked, with a short "proven by" pointer after it (a test file and test name, or a file for things that aren't tests, like the CI scans or `.gitignore`). Many items were done in earlier milestones and only need their evidence found. If an item turns out not to be true, it's fixed in this branch if small, or raised with Adam if not.
- **"Mobile-first layout"** is ticked with a pointer to the responsive CSS, with no new phone-width test (Adam, Nov 20).
- Split the CORS/headers/HTTPS line as decided above, and leave the HTTPS half unticked for M11.
- Tick Build order item 10b.
- **README:** add the load test section, a line on JSON logs (how to read them with `docker compose logs`), the privacy page, and the retention job.

## Left to the builder

- Exact wording and styling of the error pages and the privacy note, within the content listed above.
- Where the error boundary sits relative to the router, as long as both sites are covered and a link home still works.
- Which accessibility fixes are needed. That depends on what axe finds.
- The order of the tasks, and how the work is split into commits.
- Whether the request middleware is pure ASGI or Starlette's `BaseHTTPMiddleware`, as long as it doesn't break the Stripe webhook's raw body or the existing security-header middleware.
