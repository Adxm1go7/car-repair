# Milestone 10b: Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Error pages, JSON logs, an axe accessibility check, an availability load test, a privacy note and a 12-month retention job, and SPEC.md's checklist fully ticked with evidence. No booking flow changes.

**Architecture:**
- **Logs:** a stdlib `logging.Formatter` subclass in `app/logs.py`, installed on the root logger by `configure_logging()`, called by both the API factory and the worker. A pure-ASGI middleware writes one `app.request` line per request.
- **Retention:** `app/privacy/retention.py`, called once a day from the worker loop. It writes placeholders in place and marks rows with a new `details_removed_at` column.
- **Frontend:** one `ErrorBoundary` class component, two not-found pages, a `/privacy` page and a `CustomerFooter`.
- **Checks:** a new Playwright spec using `@axe-core/playwright`, and a hand-run httpx load script.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, pytest; React 19 + TypeScript, react-router, Vitest + Testing Library; Playwright + `@axe-core/playwright`; httpx (already a backend dependency).

**Spec:** [docs/superpowers/specs/2026-11-20-milestone-10b-polish-design.md](../specs/2026-11-20-milestone-10b-polish-design.md)

## Global Constraints

- **Log line keys:** always `time` (UTC ISO 8601), `level`, `logger`, `message`; plus every `extra=` field; plus `error` (traceback string) when there's an exception.
- **Request line:** logger `app.request`, message `"request"`, fields `method`, `path` (never the query string), `status`, `duration_ms` (int), `request_id` (32 hex chars, also sent as `X-Request-ID`).
- **Worker job line:** logger `app.worker`, message `"job finished"`, fields `job` (`"reminders"`, `"email"`, `"holds"`, `"retention"`), `count`, `duration_ms`. Logged only when something was handled. A failure logs `log.exception` with `job`.
- **No customer email, phone, token or query string in any log line.**
- **Retention cutoff:** `RETAIN_FOR: Final = timedelta(days=365)`, and the job runs every `RETENTION_INTERVAL: Final = timedelta(hours=24)`, first at worker start.
- **Placeholders:** `REMOVED: Final = "removed"` for name, phone, email, enquiry description, audit reasons, enquiry `decline_reason` and email `recipient`. `REMOVED_REGISTRATION: Final = "REMOVED"`. Booking `notes`, email `context` and `last_error` become NULL. A field is replaced only where it was set (non-NULL). Car make and model are kept.
- **Audit keys blanked** inside `before`/`after`: `name`, `phone`, `email`, `registration`, `notes`, `description`, `customer_name`, `customer_phone`, `customer_email`, `car_registration`.
- **Never touched by retention:** bookings in `held`, `pending_approval`, `awaiting_deposit`, and email rows with status `queued`.
- **Axe:** tags `wcag2a`, `wcag2aa`; fail on impact `serious` or `critical`.
- **Load test defaults:** 50 users, 30 seconds, base URL `http://localhost:8080`.
- **Commits:** one short title, "area - what", with no body and no attribution.
- **Windows:** write files as UTF-8 with LF line endings, using the Write/Edit tools.
- **Backend checks:**
  ```
  cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
  ```
- **Frontend checks:** from PowerShell in `e:\WORK_FOLDER_OF_FOLDERS\car-repair\frontend`:
  ```
  npm run lint; npm run typecheck; npm test
  ```
- **e2e:** from PowerShell in the repo root:
  ```
  docker compose up -d --build --wait
  cd e2e; npx playwright test
  ```

## Review Focus

1. **A request whose handler raises** (an unhandled 500) must still get exactly one `app.request` line, with status 500 and the error logged once. Pinned in Task 1 (`test_failed_request_is_logged_once`).
2. **The Stripe webhook's raw body** must reach the route unchanged through the new middleware, so signatures still verify. Pinned in Task 1 by the existing `test_stripe_webhook.py` passing unchanged. The middleware must be pure ASGI and must not read the body.
3. **A phone booking with no email, or an abandoned hold with no details,** must keep its NULLs, and the blanked row must still satisfy `confirmed_has_details`. Pinned in Task 2 (`test_null_fields_stay_null`, `test_blanked_confirmed_booking_is_valid`).
4. **A booking that ended 11 months ago, or one still waiting,** must be untouched, and so must its enquiry. Pinned in Task 2 (`test_recent_and_waiting_are_untouched`).
5. **A blanked booking opened in the staff pages** must render "removed" without crashing (for example, a `tel:` link to "removed", or an email link). Pinned in Task 2 (`test_staff_booking_detail_shows_removed`), which hits the staff booking detail API, and checked by eye in Task 5's axe run of a booking detail page.

---

### Task 1: JSON logs, request lines and worker job lines

**Files:**
- Create: `backend/app/logs.py`
- Modify:
  - `backend/app/main.py` (call `configure_logging()` in `create_app`; add `RequestLogMiddleware`)
  - `backend/app/worker.py` (call `configure_logging()` in `main()`; time and log each step; `run_once` returns counts)
  - `backend/Dockerfile` (add `--no-access-log` to the uvicorn command)
  - `README.md` (the local `uvicorn` command gets `--no-access-log`; one line on JSON logs and `docker compose logs api`)
- Test: create `backend/tests/unit/test_logs.py` and `backend/tests/integration/test_request_log.py`; modify `backend/tests/integration/test_worker.py`

**Interfaces:**
- Produces:
  - `class JsonFormatter(logging.Formatter)`: `format(record) -> str` returns one JSON object per the Global Constraints. Extra fields are found by comparing `record.__dict__` with the standard `LogRecord` attribute names. Values that aren't JSON-serialisable go through `str`.
  - `configure_logging(level: int = logging.INFO) -> None`: one `StreamHandler(sys.stdout)` with `JsonFormatter` on the root logger, replacing any existing handlers. It sets `uvicorn`, `uvicorn.error` and `uvicorn.access` to `propagate=True` with no handlers of their own. It's idempotent: calling it twice leaves one handler.
  - `class RequestLogMiddleware` (pure ASGI: `__init__(self, app: ASGIApp)`, `async __call__(scope, receive, send)`). It passes through non-`http` scopes. It captures the status from `http.response.start` and appends the `X-Request-ID` header there. It logs the line in a `finally`, with status 500 if no response started.
  - `run_once(session, now, provider) -> dict[str, int]` with keys `holds_released`, `sessions_deleted`, `login_attempts_deleted`, `request_counts_deleted`, `checkouts_closed`.
  - `run_job(job: str, work: Callable[[], int]) -> None` in `app/worker.py`: times `work()`, logs the job line when the result is > 0, and logs `log.exception("job failed", extra={"job": job})` on an exception without re-raising. The holds step's `count` is `holds_released`, and the other four counts go in as extra fields.

- [ ] **Step 1: Write failing unit tests** in `test_logs.py`:
  - `test_line_is_json_with_standard_keys`: format a record with message `"hello %s"` and args `("there",)`. `json.loads` gives `message == "hello there"`, `level == "INFO"`, `logger == "t"`, and `time` ends in `+00:00`.
  - `test_extra_fields_are_included`: `extra={"job": "email", "count": 3}` gives `job` and `count` in the output.
  - `test_exception_adds_error`: inside `except`, `logger.exception(...)` gives an `error` containing `"ValueError"`, on one line (no raw newline in the output string).
  - `test_configure_twice_keeps_one_handler`.
- [ ] **Step 2: Write failing integration tests** in `test_request_log.py`, using the `client` fixture and `caplog` on `app.request`:
  - `test_request_is_logged_without_query`: `GET /api/availability?services=mot&date=2026-11-10` logs one record with `path == "/api/availability"`, an int `status`, and a 32-hex `request_id` equal to the response's `X-Request-ID`. No string field contains `"services="`.
  - `test_failed_request_is_logged_once`: mount a throwaway route that raises on a `create_app(...)` instance, call it with `TestClient(raise_server_exceptions=False)`, and assert exactly one `app.request` record with `status == 500`.
- [ ] **Step 3: Update `test_worker.py`** for `run_once`'s dict (`["holds_released"] == 1`). Add `test_run_job_logs_only_when_work_was_done` (0 gives no record; 2 gives one record with `job`, `count == 2` and an int `duration_ms`) and `test_run_job_logs_failure_and_continues`.
- [ ] **Step 4: Run the tests and see them fail.** `cd backend && uv run pytest tests/unit/test_logs.py tests/integration/test_request_log.py tests/integration/test_worker.py -q` should fail on the missing imports.
- [ ] **Step 5: Implement `app/logs.py`, the middleware, the worker changes and the Dockerfile and README edits.** Register the middleware with `app.add_middleware(RequestLogMiddleware)` after the existing ones, so it's outermost and sees the final status. Replace the worker's `"queued %d reminders"`, `"sent %d emails"` and `"released %d expired holds"` lines with `run_job`. Keep each step's own `Session` and commit.
- [ ] **Step 6: Run the backend checks.** All pass, including the unchanged `test_stripe_webhook.py`.
- [ ] **Step 7: Check by hand.** `docker compose up -d --build --wait`, then `docker compose logs api worker --tail 20`. Every line parses as JSON, and there's no uvicorn access line.
- [ ] **Step 8: Commit:** `backend - json logs`

### Task 2: Retention job

**Files:**
- Create:
  - `backend/migrations/versions/0013_details_removed_at.py`
  - `backend/app/privacy/__init__.py`
  - `backend/app/privacy/retention.py`
- Modify:
  - `backend/app/models/booking.py`, `backend/app/models/enquiry.py` (add `details_removed_at: Mapped[datetime | None]`, timestamptz)
  - `backend/app/worker.py` (a `"retention"` step, with its own `last_retention_run` monotonic timer at `RETENTION_INTERVAL`; first run when it's `None`)
- Test: create `backend/tests/integration/test_retention.py`; extend `test_migrations.py` if it lists columns or revisions

**Interfaces:**
- Consumes: `run_job` from Task 1.
- Produces:
  - `RETAIN_FOR`, `RETENTION_INTERVAL`, `REMOVED`, `REMOVED_REGISTRATION` (Global Constraints values)
  - `remove_old_details(session: Session, now: datetime) -> int` in `app/privacy/retention.py`. It returns bookings plus enquiries blanked, and commits.
- **Selection:**
  - **Bookings:** `end_at < now - RETAIN_FOR`, `details_removed_at IS NULL`, `status NOT IN WAITING_STATUSES`.
  - **Enquiries:** `details_removed_at IS NULL` and either (`status IN ('new','declined')` and `created_at < now - RETAIN_FOR`) or (`status = 'converted'` and its booking has `details_removed_at` set after this run's booking pass).
- **Audit rows for a booking:** `entity_type = 'booking' AND entity_id = booking.id`, or `booking_reference = booking.reference`. **For an enquiry:** `entity_type = 'enquiry' AND entity_id = enquiry.id`.
- **Email rows:** `booking_id` or `enquiry_id` matches, and `status <> 'queued'`.
- Process each row with `with_for_update`, updating the JSONB with a new dict (reassign, don't mutate in place, so SQLAlchemy sees the change).

- [ ] **Step 1: Write the migration and model columns**, then run `uv run pytest tests/integration/test_migrations.py -q`. It passes, and the upgrade/downgrade round trip works.
- [ ] **Step 2: Write failing tests** in `test_retention.py`, using `db_session`, `seed`, `make_hold(status="completed"…)`, `make_enquiry`, `record_audit` and `EmailLog` rows. `NOW = datetime(2027, 12, 1, 9, tzinfo=UTC)`; old means it ended 13 months before, recent means 11 months before.
  - `test_old_booking_is_blanked`: name, phone and email are `"removed"`, the registration is `"REMOVED"`, notes are None, make and model are unchanged, and `details_removed_at == NOW`.
  - `test_audit_and_email_rows_are_blanked`: a `booking.create` entry whose `after` has `name`, `phone`, `email`, `registration`, `notes` and `services` gets the first five set to `"removed"`, with `services` unchanged. Its `reason` is `"removed"`. The sent email row gets `recipient == "removed"` and `context is None`, `last_error is None`.
  - `test_queued_email_is_skipped`: a queued email row is unchanged.
  - `test_old_unhandled_and_declined_enquiries_are_blanked`: the description and `decline_reason` are `"removed"`, and the enquiry's audit reason is `"removed"`.
  - `test_converted_enquiry_follows_its_booking`: a converted enquiry created 13 months ago whose booking ended 11 months ago is untouched. Once its booking is old too, both are blanked in one run.
  - `test_recent_and_waiting_are_untouched`: a booking that ended 11 months ago, plus an old `pending_approval` and an old `held` booking, are all unchanged.
  - `test_null_fields_stay_null`: an old expired hold with no details, and an old phone booking with `customer_email=None`, keep their NULLs.
  - `test_blanked_confirmed_booking_is_valid`: an old booking still `confirmed` is blanked and flushes without an IntegrityError.
  - `test_second_run_changes_nothing`: the second call returns 0.
  - `test_staff_booking_detail_shows_removed`: using the staff client fixture used by `test_staff_booking_changes.py`, `GET /api/staff/bookings/{ref}` on a blanked booking returns 200 with the customer name `"removed"`.
- [ ] **Step 3: Run the tests and see them fail.**
- [ ] **Step 4: Implement `remove_old_details` and the worker step.**
- [ ] **Step 5: Run the backend checks.** All pass.
- [ ] **Step 6: Commit:** `backend - 12-month retention job`

### Task 3: Error pages and error boundary

**Files:**
- Create: `frontend/src/NotFoundPage.tsx`, `frontend/src/ErrorBoundary.tsx`, `frontend/src/staff/StaffNotFoundPage.tsx`
- Modify: `frontend/src/App.tsx` (a `*` route in `CustomerApp`; wrap `App`'s `<Routes>` in `<ErrorBoundary>`), `frontend/src/staff/StaffApp.tsx:142`
- Test: `frontend/src/App.test.tsx`, `frontend/src/staff/StaffApp.test.tsx`, create `frontend/src/ErrorBoundary.test.tsx`

**Interfaces:**
- Produces:
  - `NotFoundPage(): JSX.Element`: `<main className="page">`, `<h1>Page not found</h1>`, the text "We couldn't find that page.", and links "Home" (`/`) and "Book a service" (`/book`). It sets `document.title` to `"Page not found"`, the way existing pages set theirs (match the pattern in use; if none exists, use a `useEffect`).
  - `StaffNotFoundPage(): JSX.Element`: an `<h1>Page not found</h1>` and a link "Back to today's schedule" (`/staff`).
  - `class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }>`: `getDerivedStateFromError` sets `failed`, and `componentDidCatch` calls `console.error`. The fallback is `<main className="page" role="alert">` with `<h1>Something went wrong</h1>`, the text "Sorry, something went wrong on our side. Please try again.", a "Reload" button (`window.location.reload()`), and an `<a>` "Go to home page" whose href is `/staff` when `window.location.pathname` starts with `/staff`, else `/`. It's a plain `<a>`, not a router `Link`, so it works even if the router crashed.

- [ ] **Step 1: Write failing tests:**
  - **App.test:** `renderApp('/no-such-page')` shows the heading "Page not found" and the links Home and "Book a service".
  - **StaffApp.test:** a logged-in render at `/staff/nope` shows the heading "Page not found" and the link to `/staff`.
  - **ErrorBoundary.test:**
    - a child that throws gives the heading "Something went wrong", with the thrown message absent from the document; `console.error` is stubbed, and the stub was called;
    - a non-throwing child renders normally.
- [ ] **Step 2: Run the frontend checks and see the new tests fail.**
- [ ] **Step 3: Implement the three components and the routes.**
- [ ] **Step 4: Run the frontend checks.** All pass.
- [ ] **Step 5: Commit:** `frontend - error pages`

### Task 4: Privacy note and footer

**Files:**
- Create: `frontend/src/PrivacyPage.tsx`, `frontend/src/CustomerFooter.tsx`
- Modify:
  - `frontend/src/App.tsx` (the `/privacy` route; render `<CustomerFooter />` after `CustomerApp`'s `<Routes>`)
  - the booking details form and the enquiry form (a link "How we use your details" to `/privacy`, next to the submit button)
  - `frontend/src/App.css` (footer styles)
- Test: create `frontend/src/PrivacyPage.test.tsx`; add one assertion each to the booking details and enquiry form tests

**Interfaces:**
- Produces:
  - `PrivacyPage({ garage }: { garage: Garage }): JSX.Element`, using the same `Garage` type the other pages take. It has an `<h1>Privacy</h1>` and short sections covering the spec's seven points, in this order:
    - demo with fake data
    - what we collect
    - why
    - who sees it
    - outside services: the email provider; Stripe for deposits, "we never see your card details"
    - how long: "We remove your personal details 12 months after your appointment, or 12 months after an enquiry we didn't book in."
    - contact: the garage's phone (`telHref`) and email
  - `CustomerFooter(): JSX.Element`: a `<footer>` with a `Link` "Privacy" to `/privacy`. It's outside each page's `<main>`.

- [ ] **Step 1: Write failing tests:**
  - PrivacyPage renders the heading, the 12-month sentence and the garage phone and email from `GARAGE`.
  - `renderApp('/')` has a "Privacy" link to `/privacy`.
  - The booking details and enquiry forms each have the link "How we use your details".
- [ ] **Step 2: Run the frontend checks and see them fail.**
- [ ] **Step 3: Implement the page, the footer, the routes and the form links.**
- [ ] **Step 4: Run the frontend checks.** All pass.
- [ ] **Step 5: Commit:** `frontend - privacy note and footer`

### Task 5: Accessibility check and fixes

**Files:**
- Modify: `e2e/package.json` and `e2e/package-lock.json` (`npm install -D @axe-core/playwright`, exact version pinned like `@playwright/test`)
- Create: `e2e/tests/accessibility.spec.ts`
- Modify: whatever frontend files axe flags, along with their Vitest tests if markup they assert on changes

**Interfaces:**
- Consumes: `chooseMotSlot`, `fillDetails`/`enterDetails`, `payInStripe` from `e2e/tests/booking.ts`; `loginAs`, `referenceFromUrl` from `e2e/tests/staff.ts`; the Mailpit helper the way `self-service.spec.ts` uses it to get a booking link.
- Produces: `async function expectNoSeriousViolations(page: Page, name: string): Promise<void>`, local to the spec. It runs `new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()` and filters for `serious`/`critical`. It fails with a readable list (rule id, help text and targets) so a CI failure says what to fix.

- [ ] **Step 1: Write the spec.**
  - **Customer test:** `/`; `/book` after choosing a slot, and again on the details step; `/enquiry`; `/privacy`; `/no-such-page`; and the my-booking page from a real link after one paid booking (as `self-service.spec.ts` does).
  - **Staff test:** login; then `/staff` (day schedule), one booking detail page, and `/staff/settings/services`, logged in as admin.
  - Call `expectNoSeriousViolations` once per page state.
- [ ] **Step 2: Rebuild and run only this spec.** `npx playwright test accessibility`. Record every violation it reports.
- [ ] **Step 3: Fix each violation in the real markup or CSS** (labels, names, contrast, landmarks, heading order). Disable a rule only for a proven false alarm, with `.disableRules([...])` and a comment saying why. Update the Vitest tests the fixes touch.
- [ ] **Step 4: Run the frontend checks, rebuild, and run the full e2e suite.** Everything passes.
- [ ] **Step 5: Commit:** `e2e - accessibility check and fixes`. If the fixes are large, commit them first as `frontend - accessibility fixes`.

### Task 6: Load test script and README result

**Files:**
- Create: `backend/scripts/load_availability.py`
- Modify: `README.md` (a new "Load test" section after "End-to-end test")

**Interfaces:**
- Produces:
  - `percentile(sorted_ms: list[float], p: float) -> float` (nearest-rank)
  - `async def run(base_url: str, users: int, seconds: float) -> Result`, where `Result` is a dataclass with `requests: int`, `errors: int`, `latencies_ms: list[float]` and `elapsed: float`
  - `main()` with argparse: `--base-url` (default `http://localhost:8080`), `--users` (50), `--seconds` (30)
  - Before the run, it reads `/api/services` for the first service's slug and `/api/opening-hours` for the next open day, then calls `/api/availability?services=<slug>&date=<day>`. Non-2xx responses count as errors.
  - It prints: requests, req/s, errors, p50, p95 and p99 in ms.
- The script lives outside `app/`. Make sure `ruff` and `mypy` cover it or deliberately exclude it, matching how `pyproject.toml` treats non-`app` code.

- [ ] **Step 1: Write a failing unit test** in `backend/tests/unit/test_load_script.py`: `percentile([10, 20, 30, 40], 50) == 20` and `percentile([10, 20, 30, 40], 99) == 40`. Import it via `importlib` from the scripts path if `scripts` isn't a package.
- [ ] **Step 2: Implement the script.** Run the backend checks; all pass.
- [ ] **Step 3: Run it against the local stack.** `docker compose up -d --build --wait`, then `cd backend && uv run python scripts/load_availability.py`. Record the output.
- [ ] **Step 4: Write the README section:**
  - the command;
  - the printed result;
  - the date, the machine (CPU, RAM, Windows + Docker Desktop), and that the run was against the local Compose stack;
  - one sentence noting that the availability lookup isn't rate-limited, so the numbers are unthrottled.
- [ ] **Step 5: Commit:** `backend - availability load test`

### Task 7: Checklist with evidence, SPEC and README

**Files:**
- Modify: `docs/SPEC.md`, `README.md`

- [ ] **Step 1: Find the evidence for every checklist line.** For each, grep the tests for the test that proves it, and note `file::test_name`. For non-test items, note the file instead: CI scans (`.github/workflows/...`), secrets (`.gitignore`, `.env.example`), mobile-first (the responsive CSS files and their media queries, per Adam's ruling). If a line isn't actually true, fix it here when it's small, or stop and raise it with Adam.
- [ ] **Step 2: Edit SPEC.md:**
  - tick each line and append ` — proven by: <pointers>`;
  - split the CORS line into a ticked "CORS and security headers" and an unticked "HTTPS in the deployed environment (Milestone 11)";
  - mark Build order 10b done the way 10a is marked.
- [ ] **Step 3: Edit README.md.** Add short notes on the privacy page (`/privacy`) and the retention job (12 months, daily, blanks rather than deletes), if Tasks 1 and 6 didn't already cover them.
- [ ] **Step 4: Run the backend checks, the frontend checks and the full e2e suite one last time.** Everything passes.
- [ ] **Step 5: Commit:** `docs - checklist evidence for 10b`
