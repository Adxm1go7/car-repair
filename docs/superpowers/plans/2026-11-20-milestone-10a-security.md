# Milestone 10a: Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rate limits and a honeypot on the public forms, security headers, CI dependency and image scans, and four leftover security fixes, with no change to any flow.

**Architecture:**
- **Rate limits:** attempts are counted in a new `request_counts` table by a FastAPI dependency, `limited(action)`. It records the row and commits it before the route runs, and raises `TooManyAttempts` when the visitor is over the limit. An app-wide handler turns that into a 429.
- **Honeypot:** an optional `website` field on three public bodies.
- **Headers:** they live in `frontend/nginx.conf`, plus `nosniff` set by the API itself.
- **Scans:** a new CI job.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, pytest; React 19 + TypeScript, Vitest; nginx; GitHub Actions (pip-audit, npm audit, Trivy); Playwright.

**Spec:** [docs/superpowers/specs/2026-11-20-milestone-10a-security-design.md](../specs/2026-11-20-milestone-10a-security-design.md)

## Global Constraints

- **Limits per visitor IP:**
  - `hold`: 30 per 15 min
  - `pay`: 10 per 15 min, shared by checkout and paying from the link
  - `request`: 5 per 60 min
  - `enquiry`: 5 per 60 min
  - `link`: 30 per 15 min, cancel only
- **Never limited:** `POST /holds/{ref}/status`, `DELETE /holds/{ref}`, `POST /bookings/{ref}/view`, the demo checkout and the staff routes.
- **Limits apply only when `config.environment in ("test", "production")`.** In development, no check runs and no row is written.
- **429 reply:** body `{"detail": "Too many attempts. Please wait a few minutes and try again."}`, with header `Retry-After: <whole seconds, at least 1>`.
- **Counting:** every attempt under the limit is recorded, whether the route then succeeds or not. A refused attempt is not recorded. The row is committed before the route's own work, so a later rollback can't undo it.
- **Honeypot field:** `website`, optional. When it's filled in:
  - **Enquiry:** 201 with the usual body, but nothing is stored or emailed.
  - **Checkout and request:** 422 `{"detail": "Please check your details and try again."}`, with the hold unchanged.
  - Either way it's logged at warning level with the route and IP, never the contents.
- **NUL message:** "Please remove unusual characters".
- **Id bound:** `Path(ge=1, le=2_147_483_647)`.
- **Commits:** one short title, "area - what", with no body and no attribution.
- **Windows:** write files as UTF-8 with LF line endings. Bash heredocs often break here, so write scripts with the Write tool.
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

1. **A rate-limited attempt whose route then fails** (for example, a taken slot gives 409) must still count, and the next attempts must see it. Pinned in Task 2 (`test_failed_attempt_still_counts`).
2. **A visitor at the limit on one action** must still be able to use another action, and another IP must not be affected. Pinned in Task 2 (`test_limits_are_per_action_and_ip`).
3. **An honest customer who leaves the honeypot empty, or whose client doesn't send it at all,** must be unaffected. An empty string counts as not filled in. Pinned in Task 3 (`test_empty_honeypot_is_ignored`).
4. **The Stripe form under the new content policy** must still load and pay. Pinned in Task 6, where flows 1, 2 and 4 run against the rebuilt stack.
5. **Development mode** must write no `request_counts` rows at all, so a long local session can never fill the table or trip a limit. Pinned in Task 1 (`test_development_records_nothing`).

---

### Task 1: The counter, its table, and the test environment

**Files:**
- Create: `backend/app/limits.py`, `backend/app/models/request_count.py`, `backend/migrations/versions/0012_request_counts.py`
- Modify:
  - `backend/app/models/__init__.py`
  - `backend/app/worker.py` (housekeeping calls `delete_old_counts`)
  - `backend/tests/conftest.py` (every `AppConfig(...)` in the client fixtures gets `environment="test"`)
- Test: create `backend/tests/unit/test_limits_rule.py` and `backend/tests/integration/test_limits.py`; modify `test_worker.py`

**Interfaces:**
- Produces:
  - `RequestCount(Base)`, table `request_counts`: `id`, `action` String(30), `ip` String(45), `at` timestamptz. It has the index `ix_request_counts_action_ip_at` on `(action, ip, at)`.
  - In `app/limits.py`:
    - `Action = Literal["hold", "pay", "request", "enquiry", "link"]`
    - `LIMITS: Final[dict[Action, tuple[int, timedelta]]]`, with the Global Constraints values
    - `KEEP_FOR: Final = timedelta(days=1)`
  - `class TooManyAttempts(Exception)`, with the attribute `retry_after: int`.
  - `retry_after(oldest: datetime, window: timedelta, now: datetime) -> int`. It's pure: `max(1, ceil((oldest + window - now).total_seconds()))`.
  - `check_and_record(session, action: Action, ip: str, now: datetime) -> None`:
    - It counts the rows inside the window.
    - At or over the limit, it raises `TooManyAttempts`, with `retry_after` taken from the oldest row in the window.
    - Otherwise it adds one row and commits.
  - `limited(action: Action) -> Callable[..., None]`: a FastAPI dependency factory, taking `request: Request, session: SessionDep, now: NowDep`. It returns at once unless `request.app.state.config.environment in ("test", "production")`, and otherwise calls `check_and_record(session, action, client_ip(request), now)`.
  - `delete_old_counts(session, now) -> int`.

- [ ] **Step 1: Write the failing tests.**
  - Unit `test_retry_after`:
    - `retry_after(t, 15 min, t + 14 min 59.5 s) == 1`
    - `retry_after(t, 15 min, t) == 900`
    - it's never below 1
  - `test_under_limit_records_and_commits`: call `check_and_record` 5 times for `enquiry`, then `session.rollback()`. Five rows remain.
  - `test_at_limit_raises_and_records_nothing`:
    - The 6th `enquiry` call raises `TooManyAttempts`, with `retry_after == 3600` when all five were at `now`.
    - The row count stays 5.
  - `test_window_passes`: rows older than the window don't count.
  - `test_development_records_nothing`:
    - Build an app with `AppConfig(..., environment="development")`.
    - `POST /api/enquiries` 7 times all return 201.
    - The `request_counts` table is empty.
  - `test_worker_deletes_old_counts`: a row from 2 days ago is deleted, and a row from 1 hour ago is kept.
- [ ] **Step 2: Run them.** Expected: FAIL (import errors).
- [ ] **Step 3: Implement.**
  - Write the model and migration 0012. The downgrade drops the table.
  - Write `limits.py` and the worker call.
  - Set `environment="test"` in the conftest fixtures. If an existing test then fails because it relied on the dev-server origin, give that test `environment="development"` explicitly and ledger it.
- [ ] **Step 4: Run the backend checks.** Expected: PASS, including `test_models_match_migrations`.
- [ ] **Step 5: Commit.** `backend - request counter`

### Task 2: Limit the public routes

**Files:**
- Modify: `backend/app/main.py` (the `TooManyAttempts` handler), `backend/app/api/holds.py`, `backend/app/api/my_booking.py`, `backend/app/api/enquiries.py`
- Test: create `backend/tests/integration/test_rate_limits_api.py`

**Interfaces:**
- Consumes: Task 1's `limited`, `TooManyAttempts` and `LIMITS`.
- Produces: the 429 reply exactly as in Global Constraints.
- The dependencies are added as `dependencies=[Depends(limited("hold"))]` on:
  - `POST /holds`: `hold`
  - `POST /holds/{reference}/checkout`: `pay`
  - `POST /bookings/{reference}/pay`: `pay`
  - `POST /holds/{reference}/request`: `request`
  - `POST /enquiries`: `enquiry`
  - `POST /bookings/{reference}/cancel`: `link`

- [ ] **Step 1: Write the failing tests** (`api_client`, now running as `test`; patch `LIMITS` to small numbers where needed, so the tests stay fast).
  - `test_each_action_is_limited`, parametrized over the six routes:
    - At the limit, the next call is 429 with the exact detail.
    - `Retry-After` is a positive integer.
    - For `POST /holds`, no extra hold is created.
  - `test_refused_enquiry_stores_nothing`: the 6th enquiry is 429. There are 5 enquiries, and 5 `enquiry_received` emails are queued.
  - `test_failed_attempt_still_counts`:
    - With the `hold` limit patched to 2, two holds on a taken slot each return 409.
    - The third attempt is 429.
  - `test_limits_are_per_action_and_ip`: after `enquiry` reaches its limit:
    - `POST /holds` still works;
    - a request with a different client IP can still send an enquiry. Use TestClient's `client=("10.0.0.2", 50000)`, or set `request.scope["client"]` through a second TestClient.
  - `test_unlimited_routes`: 40 calls each to `POST /holds/{ref}/status` and `POST /bookings/{ref}/view` are never 429.
- [ ] **Step 2: Run them.** Expected: FAIL (no 429).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the backend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `backend - rate limit the public forms`

### Task 3: The honeypot

**Files:**
- Modify: `backend/app/api/holds.py` (`CheckoutIn`, and the request body if it's separate), `backend/app/api/enquiries.py`
- Test: create `backend/tests/integration/test_honeypot_api.py`

**Interfaces:**
- Produces: `website: str | None = None` on `CheckoutIn`, the request body and `EnquiryIn`.
  - `is_bot(website: str | None) -> bool` in `app/api/validation.py`. It's true when `website` holds anything other than whitespace.
  - Logging: `log.warning("honeypot filled on %s from %s", route, ip)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_enquiry_honeypot_pretends`: 201 with `{"email": ...}`. No enquiry row and no `email_log` row.
  - `test_checkout_honeypot_refused`: 422 with the exact detail. The hold is still `held`, with no customer details saved and no payment created.
  - `test_request_honeypot_refused`: the same, for a needs-approval hold.
  - `test_empty_honeypot_is_ignored`: `website: ""`, `website: "  "` and no `website` key at all each succeed normally.
  - `test_honeypot_logs_no_contents`: `caplog` holds one warning naming the route, and the warning doesn't contain the submitted name or the `website` value.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** The honeypot is checked after `limited`, so the attempt still counts, and before any other work.
- [ ] **Step 4: Run the backend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `backend - honeypot on the public forms`

### Task 4: Leftover fixes and the API's nosniff

**Files:**
- Modify:
  - `backend/app/bookings/rules.py`
  - `backend/app/enquiries/rules.py`
  - `backend/app/api/staff_enquiries.py`, `staff_blocks.py`, `staff_settings.py`, `staff_team.py`, and any other route with an `int` path parameter
  - `backend/app/api/staff_settings.py` (`DayIn` and the break times)
  - `backend/app/config.py`
  - `backend/app/main.py` (a middleware that adds `X-Content-Type-Options: nosniff`)
- Test: `backend/tests/unit/test_booking_rules.py`, `test_enquiry_rules.py`, `test_config.py`; create `backend/tests/integration/test_input_hardening_api.py`

**Interfaces:**
- Produces:
  - `reject_control_chars(value: str) -> str` in `app/bookings/rules.py`. It raises `ValueError("Please remove unusual characters")` when `"\x00" in value`. Every `clean_*` and `clean_description` calls it first.
  - `ResourceId = Annotated[int, Path(ge=1, le=2_147_483_647)]` in `app/api/validation.py`, used for every `int` path parameter.

- [ ] **Step 1: Write the failing tests.**
  - `test_nul_refused`, parametrized: `clean_name("Sam\x00")`, `clean_make_or_model`, `clean_notes`, `clean_description` and `clean_registration` each raise "Please remove unusual characters".
  - `test_nul_in_public_forms_is_422`: `POST /api/enquiries` with `\x00` in the description gives 422 with `description: Please remove unusual characters`. Checkout with `\x00` in the name gives 422.
  - `test_out_of_range_ids_are_422`: `GET /api/staff/enquiries/99999999999`, `/0` and `DELETE /api/staff/blocks/99999999999` (as staff) each give 422, never 500.
  - `test_hours_refuse_zone_and_seconds`: an admin `PUT` of hours with `"open": "08:00+01:00"`, or with `"open": "08:00:30"`, gives 422.
  - `test_production_needs_webhook_secret`: `AppConfig(environment="production", stripe_secret_key="sk_test_x", stripe_publishable_key="pk_test_x")` raises a ValidationError mentioning `STRIPE_WEBHOOK_SECRET`. With `stripe_webhook_secret="whsec_x"` it builds.
  - `test_api_sends_nosniff`: `GET /api/health` has `X-Content-Type-Options: nosniff`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the backend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `backend - input hardening fixes`

### Task 5: Frontend: the honeypot fields and the 429 messages

**Files:**
- Modify:
  - `frontend/src/booking/DetailsForm.tsx`, `booking/api.ts`, `booking/types.ts` (if the body type lives there)
  - `frontend/src/enquiry/EnquiryPage.tsx`, `enquiry/api.ts`
  - `frontend/src/manage/ManageBookingPage.tsx`, `manage/api.ts`
  - `frontend/src/staff/enquiries/EnquiryPage.tsx` (a non-number id shows "No such enquiry.")
- Test: `DetailsForm.test.tsx`, `TimePicker` (via `BookPage.test.tsx`), `enquiry/EnquiryPage.test.tsx`, `manage/ManageBookingPage.test.tsx`, `manage/PayDeposit.test.tsx`, `staff/enquiries/EnquiryPage.test.tsx`

**Interfaces:**
- Produces:
  - A `Honeypot` component in `frontend/src/booking/Honeypot.tsx`, rendered like this:
    ```tsx
    <div className="visually-hidden" aria-hidden="true">
      <label htmlFor="field-website">Leave this empty</label>
      <input id="field-website" name="website" tabIndex={-1} autoComplete="off" ... />
    </div>
    ```
  - Its value is sent as `website` with `startCheckout`, `sendRequest` and `sendEnquiry`.
- Constant: `TOO_MANY = 'Too many attempts. Please wait a few minutes and try again.'` (the server's text). It's the fallback when a 429 has no detail.

- [ ] **Step 1: Write the failing tests.**
  - For each limited form, a 429 with the server's detail shows that detail:
    - Time picker (`createHold`): the notice shows it.
    - Details step, both pay and request: the alert shows it.
    - Enquiry form: the alert shows the detail, not "couldn't send".
    - Pay from the link: the problem text shows it.
    - Cancel from the link: the detail shows, not the generic cancel failure.
  - `the honeypot is hidden and empty`: an element with name `website` exists inside an `aria-hidden` container, it has `tabIndex -1`, and the POST body has `website: ''`.
  - `a filled honeypot is sent`: typing into it with `fireEvent.change` sends that value.
  - Staff `/staff/enquiries/abc` shows "No such enquiry." and makes no fetch.
- [ ] **Step 2: Run them.** Expected: FAIL for the enquiry, cancel, honeypot and staff-id tests. The others already pass, which pins today's behaviour; note which in the ledger.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the frontend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `frontend - honeypot and rate limit messages`

### Task 6: Security headers, CI scans, spec and README

**Files:**
- Modify: `frontend/nginx.conf`, `.github/workflows/ci.yml`, `docs/SPEC.md` (tick the two checklist items), `README.md` (a short "Security" paragraph)
- Create: `.trivyignore` (empty, with a comment on how to add an entry and its reason)

- [ ] **Step 1: Write the headers.**
  - Add the design's `add_header ... always` lines to the `server` block.
  - nginx drops server-level `add_header`s in any `location` that has its own `add_header`. So keep every header at server level, or repeat them in that location through a shared `include` file.
  - `location = /index.html` (and the SPA fallback) adds `Cache-Control: no-cache`.
- [ ] **Step 2: Check them locally.**
  - Run `docker compose up -d --build --wait`, then `curl -sI http://localhost:8080/` and `curl -sI http://localhost:8080/api/health`.
  - Expected: both list `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy` and `Permissions-Policy`.
- [ ] **Step 3: Run the whole e2e suite.** Expected: all 9 pass.
  - If Stripe's form is blocked, open the browser console in a headed run (`npx playwright test instant-booking --headed`), find the refused origin, and add it to the narrowest directive Stripe documents. Ledger each addition.
  - A known Stripe "Pay" click flake may need one rerun. Note it if so.
- [ ] **Step 4: Add the CI checks.**
  - In the `compose` job, after `docker compose up`, add a step that runs `curl -sI http://localhost:8080/` and greps for each header.
  - Add a `scan` job:
    - **Python:** check out, set up uv, run `uv export --frozen --no-dev --format requirements-txt > req.txt` in `backend`, then `uvx pip-audit -r req.txt --strict`.
    - **npm:** set up Node, then `npm ci` and `npm audit --omit=dev --audit-level=high` in `frontend` and in `e2e`.
    - **Images:** `docker compose build api web`, then `aquasecurity/trivy-action`, pinned to a release tag, once per image, with `severity: HIGH,CRITICAL`, `ignore-unfixed: true`, `exit-code: 1` and `trivyignores: .trivyignore`. The image names come from `docker compose config --images`.
  - If the `main` branch protection should require `scan`, that's the user's setting to change. Say so at the end; don't change it.
- [ ] **Step 5: Run the scans locally where possible.**
  - `uvx pip-audit` and both `npm audit`s.
  - Fix any finding by upgrading, if that's simple, and run the tests again.
  - Otherwise, stop and tell the user (Global Constraints: "the user decides").
- [ ] **Step 6: Update SPEC.md and README.**
  - SPEC: tick "Rate limiting and a honeypot or CAPTCHA on the booking and enquiry forms" and "Dependency and container image scanning in CI".
  - README: one short paragraph on the limits (off in development), the honeypot, the headers and the scan job.
- [ ] **Step 7: Commit.** `ci - security headers and scans; spec and readme`
