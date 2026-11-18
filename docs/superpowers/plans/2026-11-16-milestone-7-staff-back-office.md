# Milestone 7: Staff Back Office — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Staff and admins log in, see a shared day and week schedule of every bay, book phone customers, move, cancel and block time, set job status, and every change is audited. Admins also manage staff accounts and read the audit log.

**Architecture:** Server-side sessions in Postgres behind an `HttpOnly` cookie. All staff routes sit under `/api/staff`, split into a public router (login, forgot and set password) and protected routers whose router-level dependencies check the session and, for admin routes, the role. Booking changes reuse the existing availability engine, `reserve`, `cancel_booking` and the email outbox. Each change locks the booking, writes one `audit_entries` row and queues any email in the same transaction. The staff pages are React routes under `/staff` in the existing app.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, `argon2-cffi` (new), Jinja2, React + TypeScript + React Router + Vitest, Playwright, Mailpit.

**Spec:** [docs/superpowers/specs/2026-11-16-milestone-7-staff-back-office-design.md](../specs/2026-11-16-milestone-7-staff-back-office-design.md). Read it before starting. This plan doesn't repeat its reasons, screens or copy unless a step needs the exact value.

## Global Constraints

- Every `/api/staff` route except `POST /login`, `POST /forgot-password` and `POST /set-password` requires a valid session (401 otherwise). Admin routes also require `role == "admin"` (403 otherwise). The role is read from the database on every request.
- Every `POST`, `PATCH` and `DELETE` under `/api/staff` (the public three included) needs an `Origin` header in the allowed origins, or it gets 403. The allowed origins are `PUBLIC_BASE_URL` plus `http://localhost:5173` when `ENVIRONMENT=development`.
- Never stored in plain text anywhere (database, `email_log`, logs): passwords, session tokens, password-link tokens. Tokens use `new_hold_token()` and are stored as `hash_token()` (both in `app/bookings/rules.py`).
- Passwords: argon2id via `argon2-cffi` `PasswordHasher()` defaults; **minimum 8 characters**, maximum 200, no other rules.
- Cookie: `staff_session`, `HttpOnly`, `SameSite=Strict`, `Path=/api/staff`, `Secure` when `PUBLIC_BASE_URL` starts with `https://`.
- Sessions: end after **7 days unused** or **30 days** from creation. `last_used_at` is written at most once a minute.
- Throttle: **10 failures for one email** or **20 for one IP** in the last **15 minutes** → refused with the same 401 as a wrong password.
- Password links: invite **72 hours**, reset **1 hour**, single use, in the URL fragment `/staff/set-password#t=<token>`. Issuing one deletes the user's other unused tokens.
- Login errors are one message, `Email or password is wrong`, for every cause. The forgot-password reply is always 202 `If that address has an account, we've emailed a link`.
- There is always at least one active admin.
- Every staff change writes exactly one `audit_entries` row in the same transaction. Every email is queued with the existing pattern (in the caller's transaction, sent by the worker).
- Staff free times (moves and phone bookings): the same engine, cut-off 0, no booking-window limit. Hours, breaks, blocks, other bookings, bay type and bay buffer all apply.
- Phone bookings: `source = "phone"`, `deposit_status = "not_required"`, email optional. A booking without an email never has an email queued, and never raises because of it.
- No-show keeps the deposit and the time, and sends no email.
- Times shown to staff are garage-local (`garage_timezone`).
- All DB access goes through a `Session` from `get_session` (routes), the worker's session, or the command's session. No `garage_id`.
- Commit messages are `area - what` (for example `backend - staff tables`), one line, no body.
- Backend checks before each commit (in `backend/`): `uv run pytest -v`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`. Frontend (in `frontend/`): `npm run lint`, `npm run typecheck`, `npm test`.

## Review Focus

1. **A phone booking with no email that is later moved, cancelled by the garage, or reaches reminder time.** Nothing raises and nothing is queued. Pinned in Task 9 (`test_phone_booking_without_email_survives_move_cancel_and_reminders`).
2. **Two staff acting on the same booking at once** (one moves it while the other cancels it, or both press Start job). The booking row lock serialises them, and the second gets 409 rather than a half-applied change. Pinned in Task 10 (`test_move_and_cancel_at_once_one_wins`).
3. **A block over the buffer after a booking** (the booking ends 10:00 and the block starts 10:05 with a 15-minute buffer). It's refused and lists that booking, rather than failing with a 500 from the exclusion constraint. Pinned in Task 11 (`test_block_in_a_bookings_buffer_lists_it`).
4. **The Vite dev server** (`http://localhost:5173`) logging in locally. The Origin check lets it through in development only. Pinned in Task 3 (`test_dev_origin_allowed_only_in_development`).
5. **A removed admin's open tab**: their next request gets 401, and the page goes to the login screen instead of showing a broken schedule. Pinned in Task 3 (`test_removed_user_cookie_is_401`) and Task 13 (`redirects to login on a 401 from any call`).

---

## File map

| File | Responsibility |
| --- | --- |
| `backend/migrations/versions/0008_create_staff_back_office.py` | All new tables and the changed columns and checks |
| `backend/app/models/staff.py` | `StaffUser`, `StaffSession`, `PasswordToken`, `LoginAttempt` |
| `backend/app/models/audit.py` | `AuditEntry` |
| `backend/app/models/block.py` | `Block` |
| `backend/app/staff/passwords.py` | Hashing and the password rule |
| `backend/app/staff/sessions.py` | Create, find and end sessions |
| `backend/app/staff/throttle.py` | Login-attempt counting |
| `backend/app/staff/links.py` | Password tokens |
| `backend/app/staff/accounts.py` | Invite, role, remove, restore, reset; the last-admin rule |
| `backend/app/staff/audit.py` | `record_audit` |
| `backend/app/staff/deps.py` | `current_staff`, `require_admin`, `check_origin` |
| `backend/app/create_admin.py` | The first-admin command |
| `backend/app/schedule/availability.py` | Staff free times |
| `backend/app/schedule/view.py` | Loading the schedule |
| `backend/app/schedule/phone.py` | Phone bookings |
| `backend/app/schedule/changes.py` | Move, garage cancel, status |
| `backend/app/schedule/status_rules.py` | Pure job-status rules |
| `backend/app/schedule/blocks.py` | Create and remove blocks |
| `backend/app/api/staff_auth.py`, `staff_team.py`, `staff_schedule.py`, `staff_bookings.py`, `staff_blocks.py`, `staff_audit.py` | Routes |
| `backend/app/email/templates/{moved,garage_cancellation,staff_invite,password_reset}.{txt,html}.j2` | New emails |
| `frontend/src/staff/` | Every staff page, its API calls and types |
| `e2e/tests/staff.ts`, `e2e/tests/staff-schedule.spec.ts`, `e2e/tests/garage-change.spec.ts` | Flows 5 and 6 |

---

### Task 1: Tables and models

**Files:**
- Create: `backend/migrations/versions/0008_create_staff_back_office.py`, `backend/app/models/staff.py`, `backend/app/models/audit.py`, `backend/app/models/block.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/models/booking.py`, `backend/app/models/reservation.py`, `backend/app/models/email.py`, `backend/tests/factories.py`
- Test: `backend/tests/integration/test_staff_constraints.py`, `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Produces (the column lists are the design's "Data model" section; only what it doesn't pin is listed):
  - `STAFF_ROLES = ("admin", "staff")`, `PASSWORD_PURPOSES = ("invite", "reset")`, `BOOKING_SOURCES = ("online", "phone")`.
  - `StaffUser`: `email` String(254) unique; `password_hash: str | None` String(200); `active` default true; `last_login_at: datetime | None`.
  - `StaffSession.token_hash`, `PasswordToken.token_hash`: String(64), unique.
  - `LoginAttempt`: `email: str` String(254), `ip: str` String(45), `succeeded: bool`, `at: datetime`.
  - `Block`: `start_at`, `end_at`, `note` String(200), `all_bays`, `created_by` (FK staff_users), `created_at`, `removed_at: datetime | None`, `reservations` relationship.
  - `AuditEntry`: `staff_user_id: int | None` (null only for the `create_admin` command), `action` String(40), `entity_type` String(20), `entity_id: int`, `booking_reference: str | None` String(9), `before` / `after` JSONB nullable, `reason: str | None` Text, `at`.
  - `Booking` gains `source: str` (server default `online`), `created_by: int | None` (FK staff_users), `status_changed_at: datetime | None`. `DEPOSIT_STATUSES` gains `"not_required"`.
  - `Reservation` gains `block_id: int | None` (FK blocks), `block` relationship.
  - `EMAIL_TEMPLATES` gains `"moved"`, `"garage_cancellation"`, `"staff_invite"`, `"password_reset"`. `EmailLog` gains `staff_user_id: int | None` (FK staff_users), `context: dict[str, Any] | None` (JSONB), `staff_user` relationship. Widen `template` to String(30).
  - Checks: `confirmed_has_deposit` allows `paid`, `waived`, `not_required`; new `not_required_only_by_phone` (`deposit_status <> 'not_required' OR source = 'phone'`); `confirmed_has_details` drops `customer_email` when `source = 'phone'`; `block_reservation_has_block` (`kind <> 'block' OR block_id IS NOT NULL`); `email_has_one_subject` (`(booking_id IS NULL) <> (staff_user_id IS NULL)`); role, purpose and source value checks.

- [ ] **Step 1: Write failing tests** in `test_staff_constraints.py`:
  - `test_staff_email_is_unique`, `test_unknown_role_is_rejected`
  - `test_not_required_deposit_needs_phone_source` (an online confirmed booking with `not_required` → `IntegrityError`)
  - `test_phone_booking_may_have_no_email` (confirmed, `source="phone"`, `customer_email=None`, `deposit_status="not_required"` → flushes)
  - `test_online_confirmed_booking_still_needs_email`
  - `test_block_reservation_needs_a_block`
  - `test_email_log_needs_exactly_one_subject` (neither → error; both → error)
  - `test_existing_bookings_become_online` (in `test_migrations.py`: upgrade to 0007, insert a booking row, upgrade to head, `source == "online"`)

  And in `test_migrations.py`: `test_downgrade_to_0007_drops_staff_tables`.
- [ ] **Step 2: Run** `cd backend; uv run pytest tests/integration/test_staff_constraints.py tests/integration/test_migrations.py -v` → FAIL (imports).
- [ ] **Step 3: Implement** the models and migration `0008` (revises `0007`, value lists copied as strings as in `0007`). Add `uv add argon2-cffi` now, so `make_staff` can be written in Task 2.
- [ ] **Step 4: Run** the same command → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git add backend; git commit -m "backend - staff, block and audit tables"`

---

### Task 2: Passwords, sessions, throttle and audit

**Files:**
- Create: `backend/app/staff/__init__.py`, `passwords.py`, `sessions.py`, `throttle.py`, `audit.py`
- Modify: `backend/tests/factories.py` (`make_staff`)
- Test: `backend/tests/unit/test_passwords.py`, `backend/tests/integration/test_staff_sessions.py`, `backend/tests/integration/test_throttle.py`

**Interfaces:**
- Produces:
  - `passwords.py`: `MIN_PASSWORD_LENGTH = 8`, `MAX_PASSWORD_LENGTH = 200`; `clean_password(value: str) -> str` (raises `ValueError("Your password must be at least 8 characters")` or `"... at most 200 characters"`; doesn't strip); `hash_password(password: str) -> str`; `password_matches(password: str, stored: str | None) -> bool` (False for None; never raises).
  - `sessions.py`: `IDLE_LIMIT = timedelta(days=7)`, `SESSION_CAP = timedelta(days=30)`, `TOUCH_EVERY = timedelta(minutes=1)`; `create_session(session: Session, user: StaffUser, now: datetime) -> str` (returns the plain token, sets `user.last_login_at`); `find_session_user(session: Session, token: str, now: datetime) -> StaffUser | None` (None if unknown, idle, past the cap, or the user is inactive; touches `last_used_at`); `end_session(session, token) -> None`; `end_all_sessions(session, user_id: int) -> None`; `delete_expired_sessions(session, now) -> int`.
  - `throttle.py`: `EMAIL_LIMIT = 10`, `IP_LIMIT = 20`, `WINDOW = timedelta(minutes=15)`; `is_locked(session, email: str, ip: str, now) -> bool`; `record_attempt(session, email: str, ip: str, succeeded: bool, now) -> None`; `delete_old_attempts(session, now) -> int` (older than 1 day). `email` is lowercased and stripped before storing and counting.
  - `factories.make_staff(session, *, role="staff", email="sam.staff@example.com", password="correct horse", active=True, name="Sam Staff") -> StaffUser`, flushed.
  - `audit.py`: `record_audit(session: Session, staff: StaffUser | None, action: str, entity_type: str, entity_id: int, *, before: dict[str, Any] | None = None, after: dict[str, Any] | None = None, reason: str | None = None, booking_reference: str | None = None, now: datetime) -> AuditEntry` (adds and flushes, no commit).

- [ ] **Step 1: Write failing tests.**
  - Unit: `test_password_of_7_is_refused_and_8_accepted`, `test_password_matches_after_hash`, `test_password_matches_none_is_false`, `test_password_matches_garbage_hash_is_false`.
  - Sessions: `test_new_session_finds_its_user`, `test_token_is_stored_hashed` (no row has the plain token), `test_session_idle_7_days_is_gone` (`now + 7 days` → None; `now + 7 days − 1 s` → user), `test_session_past_30_days_is_gone_even_when_used` (touched every day), `test_inactive_user_session_is_none`, `test_end_all_sessions`, `test_last_used_written_at_most_once_a_minute`.
  - Throttle: `test_tenth_failure_locks_the_email` (9 failures → unlocked; 10 → locked), `test_lock_ends_after_15_minutes`, `test_twenty_failures_from_one_ip_lock_it`, `test_email_case_doesnt_dodge_the_lock` (`"Sam@X.com"` and `"sam@x.com"` count together), `test_successes_dont_count`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_passwords.py tests/integration/test_staff_sessions.py tests/integration/test_throttle.py -v` → FAIL.
- [ ] **Step 3: Implement** the four modules and `make_staff`. `password_matches` catches `argon2.exceptions.VerificationError` and `InvalidHashError`.
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - staff passwords, sessions and login throttle"`

---

### Task 3: Login API, route guards and sample accounts

**Files:**
- Create: `backend/app/staff/deps.py`, `backend/app/api/staff_auth.py`
- Modify: `backend/app/main.py`, `backend/app/config.py`, `backend/app/seed.py`, `backend/app/demo_data.py`, `backend/app/worker.py` (session and attempt clean-up in the holds step), `backend/tests/conftest.py`
- Test: `backend/tests/integration/test_staff_login_api.py`, `backend/tests/integration/test_staff_route_guards.py`, `backend/tests/integration/test_seed.py`

**Interfaces:**
- Consumes: Task 2.
- Produces:
  - `deps.py`: `COOKIE_NAME = "staff_session"`; `current_staff(request: Request, session: SessionDep, now: NowDep) -> StaffUser` (401 `Please log in`); `require_admin(user: Annotated[StaffUser, Depends(current_staff)]) -> StaffUser` (403 `Admins only`); `check_origin(request: Request) -> None` (403 `Request refused` for a write method whose `Origin` isn't allowed); `StaffDep = Annotated[StaffUser, Depends(current_staff)]`, `AdminDep = Annotated[StaffUser, Depends(require_admin)]`; `client_ip(request: Request) -> str` (`request.client.host`, or `"unknown"`); `set_session_cookie(response: Response, token: str, config: AppConfig) -> None`.
  - `AppConfig.allowed_origins` property, per Global Constraints.
  - Routers: `staff_auth.public_router` (`dependencies=[Depends(check_origin)]`) and `staff_auth.router` (`dependencies=[Depends(check_origin), Depends(current_staff)]`), both mounted at prefix `/api/staff`. Later tasks add their routers with the same dependencies, or `Depends(require_admin)` for admin ones.
  - `POST /api/staff/login` `{email, password}` → 200 `StaffMeOut {id, name, email, role}` and sets the cookie. It records the attempt, checks `is_locked` **before** checking the password, and gives 401 `Email or password is wrong` for every failure.
  - `POST /api/staff/logout` → 204, ends the session, clears the cookie. `GET /api/staff/me` → `StaffMeOut`.
  - `PUBLIC_STAFF_PATHS = {"/api/staff/login", "/api/staff/forgot-password", "/api/staff/set-password"}` in `deps.py`, for the guard test.
  - `DEMO_STAFF` in `demo_data.py`: `admin@example.test` / `demo-admin-pass` (admin, "Alex Admin") and `staff@example.test` / `demo-staff-pass` (staff, "Sam Staff"). `seed()` inserts them (on conflict do nothing) unless `get_config().environment == "production"`. Make that check a parameter: `seed(session, *, sample_accounts: bool = False)`, with `main()` passing `environment != "production"`, so existing callers are unchanged.
  - conftest: `staff_client` and `admin_client` fixtures, each an `api_client` already logged in as a `make_staff` user, with the `Origin` header set to `http://localhost:8080` on every request.

- [ ] **Step 1: Write failing tests.**
  - Login: `test_login_sets_an_httponly_strict_cookie`, `test_wrong_password_unknown_email_and_inactive_all_give_the_same_401`, `test_locked_email_gets_401_even_with_the_right_password`, `test_logout_ends_the_session`, `test_me_returns_the_user`, `test_secure_cookie_when_base_url_is_https`.
  - Guards (`test_staff_route_guards.py`):
    - `test_every_staff_route_needs_a_session`: walk `app.routes`, take each `APIRoute` whose path starts `/api/staff` and isn't in `PUBLIC_STAFF_PATHS`, fill path parameters (`{reference}` → `ABCD-EFGH`, `{user_id}` and `{block_id}` → `1`), and for each method send `{}` with a good `Origin` and no cookie. Assert 401. It must find at least one route, so the test can't pass empty.
    - `test_expired_session_cookie_is_401`, `test_removed_user_cookie_is_401`
    - `test_staff_get_403_on_every_admin_route`: the same walk, over the routes whose dependencies include `require_admin` (inspect `route.dependant`), with a staff cookie.
    - `test_write_without_origin_is_403`, `test_write_with_foreign_origin_is_403`, `test_dev_origin_allowed_only_in_development`
  - Seed: `test_seed_adds_sample_accounts`, `test_seed_without_sample_accounts_adds_none`, `test_sample_password_logs_in`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_staff_login_api.py tests/integration/test_staff_route_guards.py tests/integration/test_seed.py -v` → FAIL.
- [ ] **Step 3: Implement** the deps, routes, config property, seed change and worker clean-up (`delete_expired_sessions`, `delete_old_attempts` in `run_once`). Check that FastAPI runs a router-level dependency before body validation, so `{}` gets 401, not 422. The guard test proves it.
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - staff login, route guards and sample accounts"`

---

### Task 4: Password links, staff emails and the first-admin command

**Files:**
- Create: `backend/app/staff/links.py`, `backend/app/create_admin.py`, templates `staff_invite` and `password_reset` (`.txt.j2`, `.html.j2`)
- Modify: `backend/app/email/message.py`, `backend/app/email/render.py`, `backend/app/email/queue.py`, `backend/app/email/outbox.py`, `backend/app/api/staff_auth.py`
- Test: `backend/tests/integration/test_password_links.py`, `backend/tests/integration/test_outbox.py`, `backend/tests/unit/test_render_email.py`

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces:
  - `EmailTemplate` gains the four new names (`moved` and `garage_cancellation` are rendered in Task 10).
  - `links.py`: `LINK_LIFETIME = {"invite": timedelta(hours=72), "reset": timedelta(hours=1)}`; `issue_password_token(session, user: StaffUser, purpose: Literal["invite", "reset"], now) -> str` (deletes the user's other unused tokens); `use_password_token(session, token: str, now) -> StaffUser | None` (marks it used; None if unknown, used, expired, too long (over 100 characters) or the user is inactive); `set_password_url(base_url: str, token: str) -> str` → `{base}/staff/set-password#t={token}`.
  - `queue_staff_email(session, template: Literal["staff_invite", "password_reset"], user: StaffUser) -> EmailLog`.
  - `@dataclass(frozen=True) StaffEmailContext: name: str; garage: dict[str, str]; link_url: str; valid_for: str` (`"72 hours"` or `"1 hour"`); `render_staff_email(template, to, context) -> OutgoingEmail`. Subjects: `You've been invited to {garage name} bookings` and `Reset your password`.
  - In `send_due_emails`, a row with `staff_user_id`: skipped if the user is inactive; otherwise issue the token (`invite` for `staff_invite`, `reset` for `password_reset`) in the send transaction, render, send. A failed send rolls the token back, as booking links do.
  - `POST /api/staff/forgot-password` `{email}` → always 202. It records a failed attempt for the throttle, and if not locked and an active user has that email, queues `password_reset` and commits. It does **not** clear the password.
  - `POST /api/staff/set-password` `{token, password}` → 400 `This link isn't valid any more` or 422 for a bad password; on success it sets `password_hash`, ends all sessions, creates a new one, sets the cookie, and returns `StaffMeOut`.
  - `python -m app.create_admin --name NAME --email EMAIL`: creates an active admin with no password (or exits 1 with "already exists"), writes `record_audit(staff=None, action="staff.invite", ...)`, issues an `invite` token, commits, and prints `Set the password within 72 hours: <url>`. No email.

- [ ] **Step 1: Write failing tests.**
  - `test_invite_email_link_sets_password_and_logs_in` (queue → `send_due_emails` with `FakeSender` → pull the token from the sent text → `POST /set-password` → 200 with a cookie → `GET /me` 200)
  - `test_set_password_link_works_once`, `test_reset_link_expires_after_one_hour`, `test_invite_link_lasts_72_hours`, `test_new_link_cancels_the_old_one`
  - `test_set_password_ends_other_sessions`
  - `test_forgot_password_is_202_for_unknown_and_known_emails` (only the known one queues), `test_forgot_password_keeps_the_old_password_working`, `test_forgot_password_counts_towards_the_lock`
  - `test_staff_email_for_removed_user_is_skipped` (outbox)
  - `test_no_plain_token_in_email_log_or_password_tokens`
  - `test_create_admin_prints_a_working_link` (call `main(["--name", ..., "--email", ...])` with `capsys`, then set the password through the API)
  - Unit: `test_staff_invite_html_escapes_name`, `test_reset_says_one_hour`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_password_links.py tests/integration/test_outbox.py tests/unit/test_render_email.py -v` → FAIL.
- [ ] **Step 3: Implement.** `create_admin.main(argv: list[str] | None = None) -> int` uses `argparse` and its own engine from `get_config()`.
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - password links, staff emails and create_admin"`

---

### Task 5: Team management API

**Files:**
- Create: `backend/app/staff/accounts.py`, `backend/app/api/staff_team.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_staff_team_api.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces (admin router, prefix `/api/staff/team`):
  - `class LastAdmin(Exception)`, `class EmailTaken(Exception)`.
  - `invite_staff(session, admin, name: str, email: str, role: str, now) -> StaffUser` (queues `staff_invite`, audits `staff.invite`).
  - `update_staff(session, admin, user: StaffUser, *, role: str | None, active: bool | None, now) -> None`. Removing (`active=False`) clears `password_hash` and ends all sessions; restoring (`active=True`) queues `staff_invite`; each audits `staff.role`, `staff.remove` or `staff.restore`. Removing or demoting the last active admin raises `LastAdmin`. Lock all admin rows (`FOR UPDATE`) before counting, so two admins removing each other at once can't both succeed.
  - `admin_reset_password(session, admin, user, now) -> None`: clears `password_hash`, ends sessions, queues `password_reset`, audits `staff.reset_password`.
  - `GET /` → `list[TeamMemberOut {id, name, email, role, state}]`, where `state` is `"invited" | "active" | "reset_sent" | "removed"` (removed if inactive; invited if no password and the user has never logged in; reset sent if no password and they have; otherwise active).
  - `POST /` `{name, email, role}` → 201 (409 `That email already has an account`); `PATCH /{user_id}` `{role?, active?}` → 200 (409 `The garage needs at least one admin`; 404); `POST /{user_id}/reset-password` → 202.
  - Audit `before`/`after` hold `name, email, role, active` only.

- [ ] **Step 1: Write failing tests:** `test_invite_queues_email_and_audits`, `test_invite_duplicate_email_is_409` (case-insensitive), `test_role_change_applies_on_next_request` (a demoted admin's next `GET /team` is 403), `test_remove_ends_sessions_and_old_password_fails`, `test_restore_sends_a_new_link_and_old_password_still_fails`, `test_admin_reset_locks_out_until_the_link_is_used`, `test_last_admin_cannot_be_removed_or_demoted`, `test_two_admins_removing_each_other_leaves_one` (two threads, own sessions), `test_states_on_the_team_list`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_staff_team_api.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - team management for admins"`

---

### Task 6: Staff free times

**Files:**
- Create: `backend/app/schedule/__init__.py`, `backend/app/schedule/availability.py`
- Modify: `backend/app/repositories/availability.py`, `backend/app/repositories/reservations.py`
- Test: `backend/tests/integration/test_staff_availability.py`, `backend/tests/integration/test_reserve.py`

**Interfaces:**
- Produces:
  - In `repositories/availability.py`: `day_availability_for(session, infos: Sequence[ServiceInfo], day: date, now: datetime, policy: Policy, *, exclude_reservation_id: int | None = None) -> DayAvailability`. The existing `day_availability` becomes a thin wrapper over it, with behaviour unchanged.
  - `reserve(..., bay_id: int | None = None)`: when given, only that bay is tried, and `SlotUnavailable` is raised if the slot's `bay_ids` don't include it.
  - `schedule/availability.py`: `staff_policy(session) -> Policy` (`load_policy` with `cutoff_minutes=0`); `infos_for_services(services: Sequence[Service]) -> list[ServiceInfo]`; `infos_for_booking(booking: Booking) -> list[ServiceInfo]` (durations from `booking.items`, bay type from `item.service.required_bay_type_id`); `staff_free_times(session, infos, day, now, *, exclude_reservation_id=None) -> DayAvailability`.

- [ ] **Step 1: Write failing tests:** `test_staff_can_book_inside_the_cutoff` (now 09:00, a 09:30 slot is offered), `test_staff_times_ignore_the_booking_window` (a day 90 days out has slots), `test_moving_ignores_its_own_reservation` (10:00–11:00 booking; 10:30 is offered when excluded and not otherwise), `test_booking_durations_come_from_items` (an item of 30 minutes on a 60-minute service gives slots up to 30 minutes before closing), `test_blocks_and_breaks_still_apply`, and in `test_reserve.py` `test_reserve_in_a_chosen_bay` and `test_reserve_in_a_bay_the_slot_doesnt_have_is_unavailable`. The existing public availability and reserve tests must still pass unchanged.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_staff_availability.py tests/integration/test_reserve.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - staff free times and reserving a chosen bay"`

---

### Task 7: Schedule and availability API

**Files:**
- Create: `backend/app/schedule/view.py`, `backend/app/api/staff_schedule.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_staff_schedule_api.py`

**Interfaces:**
- Consumes: Task 6.
- Produces (staff router):
  - `GET /api/staff/schedule?from=YYYY-MM-DD&days=1..7` → `ScheduleOut { bays: [{id, slug, name, bay_type}], days: [{date, open, close, breaks: [{start, end}]}], items: [ScheduleItemOut] }`. `open` and `close` are `"HH:MM"` or null.
  - `ScheduleItemOut { kind: "booking" | "block", bay_id, start, end, reference?, status?, registration?, services?, source?, has_email?, block_id?, note? }`, where start and end are garage-local ISO with offset (`local_iso` from `app/api/holds.py`). A booking's end is its real end (without the buffer). Bookings in `held` status are included with `status: "held"`. Cancelled and expired bookings are left out, and so are removed blocks.
  - `GET /api/staff/availability?services=a&services=b&date=` → the same body as the public `/api/availability` (reuse its output model), from `staff_free_times`. It uses `resolve_services` but **allows needs-approval services**, and refuses mixed bay types with 422 as the public route does.
  - 422 for `days` outside 1–7 or a bad date.

- [ ] **Step 1: Write failing tests:** `test_schedule_lists_bookings_and_blocks_per_bay`, `test_schedule_leaves_out_cancelled_and_expired`, `test_schedule_shows_held_as_held`, `test_schedule_week_has_seven_days_with_hours`, `test_schedule_times_are_local_across_clock_change` (a booking on 2027-03-28 10:00 BST shows `+01:00`), `test_schedule_days_out_of_range_is_422`, `test_staff_availability_allows_needs_approval_service`, `test_staff_availability_is_inside_the_cutoff`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_staff_schedule_api.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - staff schedule and availability endpoints"`

---

### Task 8: Job status rules (pure)

**Files:**
- Create: `backend/app/schedule/status_rules.py`
- Test: `backend/tests/unit/test_status_rules.py`

**Interfaces:**
- Produces:
  - `Action = Literal["start", "complete", "no_show", "undo_start", "undo_complete", "undo_no_show", "move", "cancel"]`
  - `UNDO_LIMIT = timedelta(hours=24)`
  - `booking_actions(status: str, start_at: datetime, status_changed_at: datetime | None, now: datetime) -> list[Action]`, following the design's job-status table: `move` and `cancel` only for `confirmed`; `no_show` only when `now >= start_at`; undo of `complete` and `no_show` only within `UNDO_LIMIT` of `status_changed_at`.
  - `ACTION_TARGET: dict[Action, str]` for the status actions (`start` → `in_progress`, `undo_start` → `confirmed`, and so on).
  - `starts_on_another_day(start_at: datetime, now: datetime, zone: ZoneInfo) -> bool` (for the "Start it now?" question).

- [ ] **Step 1: Write failing tests:** one per table row, plus `test_no_show_not_before_start` (`now = start − 1 s` → absent; `now = start` → present), `test_undo_complete_until_24_hours` (at 24 h → present; 24 h + 1 s → absent), `test_nothing_for_cancelled_or_held`, `test_another_day_uses_garage_local_dates` (23:30 UTC on 28 Mar 2027 is 29 Mar in London).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_status_rules.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "backend - job status rules"`

---

### Task 9: Phone bookings

**Files:**
- Create: `backend/app/schedule/phone.py`, `backend/app/api/staff_bookings.py`
- Modify: `backend/app/bookings/service.py`, `backend/app/email/queue.py`, `backend/app/email/reminders.py`, `backend/app/email/templates/confirmation.*.j2`, `backend/app/email/templates/cancellation.*.j2`, `frontend/src/manage/ManageBookingPage.tsx` (no deposit line for `not_required`), `backend/app/main.py`
- Test: `backend/tests/integration/test_phone_bookings.py`, `backend/tests/integration/test_queue_email.py`, `backend/tests/unit/test_render_email.py`, `frontend/src/manage/ManageBookingPage.test.tsx`

**Interfaces:**
- Consumes: Tasks 2, 3, 6.
- Produces:
  - `bookings/service.py`: `insert_with_reference(session, make: Callable[[str], Booking]) -> Booking`, the reference-retry loop taken out of `create_hold` (which then uses it, with behaviour unchanged).
  - `queue_email(...) -> EmailLog | None`: returns None and queues nothing when `booking.customer_email` is None. Replace `test_queue_email_needs_a_recipient` with `test_queue_email_without_recipient_queues_nothing`. `queue_due_reminders` also filters `Booking.customer_email.is_not(None)`.
  - `@dataclass(frozen=True) PhoneDetails`: the same fields as `CustomerDetails`, with `email: str | None`.
  - `create_phone_booking(session, staff: StaffUser, services: Sequence[Service], start: datetime, bay_id: int, details: PhoneDetails, now) -> Booking`: `reserve(..., cutoff_minutes=0, bay_id=bay_id)`, then a `confirmed` booking with `source="phone"`, `deposit_status="not_required"`, `created_by=staff.id`, `confirmed_at=now`, items snapshotted as in `create_hold`. It queues `confirmation` when there's an email and audits `booking.create`. It raises `SlotUnavailable`, and the window isn't checked.
  - `POST /api/staff/bookings` (staff router) `{services, start, bay_id, name, phone, email?, registration, make, model, notes?}` (the same `clean_*` validators as `CheckoutIn`, with email optional and `""` treated as None) → 201 `{reference}`. 409 `That time has just been taken`; 422 for mixed bay types.
  - Templates: a `not_required` booking's confirmation has no deposit line, and its cancellation has no deposit line.

- [ ] **Step 1: Write failing tests:**
  - `test_phone_booking_with_email_is_confirmed_and_emailed` (`source`, `deposit_status`, `created_by`, one `confirmation` row, one `booking.create` audit entry)
  - `test_phone_booking_without_email_queues_nothing`
  - `test_phone_booking_into_a_taken_time_is_409`
  - `test_phone_booking_allows_needs_approval_service`
  - `test_phone_booking_mixed_bay_types_is_422`
  - `test_phone_booking_inside_the_cutoff_is_allowed`
  - `test_phone_booking_without_email_survives_move_cancel_and_reminders` (write it now against `queue_due_reminders`, then extend it with move and cancel in Task 10)
  - Unit: `test_no_deposit_line_for_not_required` (confirmation and cancellation)
  - Frontend: `shows no deposit line for a phone booking`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_phone_bookings.py tests/integration/test_queue_email.py tests/unit/test_render_email.py -v` and `cd ../frontend; npm test` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then both sets of checks.
- [ ] **Step 5: Commit** `git commit -m "backend - phone bookings without a deposit"`

---

### Task 10: Booking detail, move, garage cancel and status

**Files:**
- Create: `backend/app/schedule/changes.py`, templates `moved` and `garage_cancellation` (`.txt.j2`, `.html.j2`)
- Modify: `backend/app/api/staff_bookings.py`, `backend/app/email/render.py`, `backend/app/email/outbox.py`, `backend/app/email/queue.py` (an optional `context` argument)
- Test: `backend/tests/integration/test_staff_booking_changes.py`, `backend/tests/integration/test_phone_bookings.py`, `backend/tests/unit/test_render_email.py`

**Interfaces:**
- Consumes: Tasks 6, 8, 9.
- Produces:
  - `queue_email(session, template, booking, context: dict[str, Any] | None = None) -> EmailLog | None`.
  - `EmailContext` gains `reason: str | None = None`, `previous_start: datetime | None = None`, `previous_end: datetime | None = None`, `previous_bay: str | None = None`, filled from `email_log.context` (ISO strings) in the outbox. `_APPLIES_TO` gains `moved` → `confirmed` and `garage_cancellation` → `cancelled`. `_HAS_LINK` gains `moved`.
  - Subjects: `Your booking has moved — {reference}` and `We've had to cancel your booking — {reference}`. The body copy follows the design's "Emails" section.
  - `changes.py`: `class NotAllowed(Exception)` (with `.detail: str`); `move_booking(session, staff, reference: str, start: datetime, bay_id: int, reason: str | None, now) -> Booking`; `garage_cancel(session, provider, staff, reference, reason, now, free_cancellation_hours: int) -> Booking`; `change_status(session, staff, reference, action: Action, now, zone) -> Booking`. Each locks the booking first (`get_booking_for_update`), raises `LookupError` for an unknown reference and `NotAllowed` for an action not in `booking_actions`, audits, and doesn't commit.
  - Move: free times from `staff_free_times(..., exclude_reservation_id=booking.reservation_id)` with `infos_for_booking`; the chosen start must be a slot that includes `bay_id`, or it raises `SlotUnavailable`. Update `reservation.bay_id` and `during` (with the buffer, in UTC, as `reserve` does) inside a savepoint, catching the exclusion and deadlock codes as `reserve` does → `SlotUnavailable`. Then set `booking.start_at` and `end_at`, set every `BookingLink.expires_at` for the booking to the new `end_at + LINK_VALID_AFTER_END`, and queue `moved` with context `{reason, previous_start, previous_end, previous_bay}`. The same start and bay → `NotAllowed("no_change")`.
  - Garage cancel: `cancel_booking(..., by="garage")`, then queue `garage_cancellation` with `{reason}`. `PaymentUnavailable` propagates.
  - Status: sets `status` and `status_changed_at = now`; audits `booking.status` with before and after.
  - Routes (staff router): `GET /api/staff/bookings/{reference}` → `StaffBookingOut {reference, status, source, start, end, bay: {id, name}, services, registration, make, model, customer_name, customer_phone, customer_email, notes, deposit_status, actions: list[Action], starts_on_another_day: bool, history: [{at, text}]}`. The history is the booking's audit entries, oldest first, with text like `Moved from Tue 17 Nov 09:00 by Sam Staff — "Lift broken"`. Online bookings get a first line `Booked online` at `confirmed_at`.
  - `GET /api/staff/bookings/{reference}/move-options?date=` → the availability body.
  - `POST /api/staff/bookings/{reference}/move` `{start, bay_id, reason?}`; `POST /api/staff/bookings/{reference}/cancel` `{reason?}`; `POST /api/staff/bookings/{reference}/status` `{action}`. Each returns `StaffBookingOut`. 404 unknown; 409 with the detail (`not_allowed`, `no_change`, `taken`); 503 `We couldn't cancel just now` on `PaymentUnavailable`, rolled back.
  - Reasons: optional, trimmed, at most 500 characters, and `""` treated as None.

- [ ] **Step 1: Write failing tests:**
  - `test_move_updates_booking_reservation_links_and_audits` (and one `moved` email with the context)
  - `test_move_into_a_taken_time_is_409_and_changes_nothing`
  - `test_move_later_same_morning_overlapping_itself`
  - `test_move_same_time_and_bay_is_no_change`
  - `test_move_of_in_progress_booking_is_409`
  - `test_customer_cancel_after_move_uses_new_start` (moved to 20 hours ahead → the customer link's `can_cancel` is false)
  - `test_garage_cancel_refunds_audits_and_emails` (and the queued reminder is skipped at send)
  - `test_garage_cancel_with_stripe_down_changes_nothing` (no audit, no email)
  - `test_status_start_complete_and_undo`, `test_no_show_before_start_is_409`, `test_no_show_keeps_deposit_and_reservation`
  - `test_move_and_cancel_at_once_one_wins` (two threads with their own sessions and a `threading.Barrier`; one succeeds, the other gets `NotAllowed`)
  - `test_history_names_the_staff_member_and_reason`
  - extend `test_phone_booking_without_email_survives_move_cancel_and_reminders`
  - Unit: `test_moved_email_shows_old_and_new_time_and_reason`, `test_garage_cancellation_without_reason`, `test_reason_is_html_escaped`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_staff_booking_changes.py tests/integration/test_phone_bookings.py tests/unit/test_render_email.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - staff move, cancel and job status"`

---

### Task 11: Blocks

**Files:**
- Create: `backend/app/schedule/blocks.py`, `backend/app/api/staff_blocks.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_blocks.py`

**Interfaces:**
- Produces:
  - `class BlockClashes(Exception)` with `.bookings: list[Booking]` and `.blocks: list[Block]`.
  - `create_block(session, staff, bay_id: int | None, start: datetime, end: datetime, note: str, now) -> Block`. `bay_id=None` means every active bay, with `all_bays=True`. It first selects active reservations in those bays whose `during` overlaps `[start, end)`, and raises `BlockClashes` if there are any. It then inserts one `kind="block"` reservation per bay in a savepoint; an exclusion violation there (a race) re-runs the clash query and raises `BlockClashes`. Audits `block.create`.
  - `remove_block(session, staff, block_id, now) -> None`: sets `removed_at`, makes its reservations inactive, audits `block.remove`. `LookupError` if unknown or already removed.
  - `POST /api/staff/blocks` `{bay_id: int | null, start, end, note}` → 201 `{id}`. 422 for `end <= start`, a blank note, a note over 200 characters, or a block longer than 31 days. 409 `{detail: "clashes", bookings: [{reference, start, bay}], blocks: [{id, note}]}`.
  - `DELETE /api/staff/blocks/{block_id}` → 204.

- [ ] **Step 1: Write failing tests:** `test_block_one_bay`, `test_block_all_bays_makes_one_reservation_each`, `test_block_over_a_booking_lists_it`, `test_block_in_a_bookings_buffer_lists_it`, `test_block_over_a_held_booking_lists_it`, `test_block_over_another_block_lists_it`, `test_removed_block_frees_the_time` (public availability offers it again), `test_public_availability_skips_blocked_time`, `test_block_end_before_start_is_422`, `test_blocks_are_audited`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_blocks.py -v` → FAIL.
- [ ] **Step 3: Implement.** The 409 body is a `JSONResponse`, not an `HTTPException`, so it can carry the lists.
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - blocked time"`

---

### Task 12: Audit log API

**Files:**
- Create: `backend/app/api/staff_audit.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_staff_audit_api.py`

**Interfaces:**
- Produces (admin router): `GET /api/staff/audit?from=&to=&staff=&reference=&page=1` → `{entries: [{at, staff_name, action, entity_type, entity_id, booking_reference, before, after, reason}], page, has_more}`. Newest first, 50 a page, with `from`/`to` as garage-local dates (inclusive). `staff_name` is `"Setup"` for a null user.

- [ ] **Step 1: Write failing tests:** `test_audit_is_newest_first_50_a_page`, `test_audit_filters_by_staff_reference_and_dates`, `test_setup_entries_show_setup`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_staff_audit_api.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - audit log for admins"`

---

### Task 13: Staff shell and login pages

**Files:**
- Create: `frontend/src/staff/api.ts`, `types.ts`, `StaffApp.tsx`, `StaffLayout.tsx`, `LoginPage.tsx`, `ForgotPasswordPage.tsx`, `SetPasswordPage.tsx`, `staff.css`, and a `.test.tsx` for each page plus `StaffApp.test.tsx`
- Modify: `frontend/src/main.tsx` or `frontend/src/App.tsx` (route `/staff/*` to `StaffApp` **before** the catalogue load)

**Interfaces:**
- Consumes: Tasks 3–4 endpoints.
- Produces:
  - `api.ts`: `staffRequest<T>(path: string, init?: RequestInit): Promise<StaffResult<T>>`, where `StaffResult<T> = { ok: true; data: T } | { ok: false; kind: 'unauthorised' } | { ok: false; kind: 'forbidden' } | { ok: false; kind: 'conflict'; body: unknown } | { ok: false; kind: 'error'; detail: string | null }`. Paths are relative to `/api/staff`, and the default `credentials: 'same-origin'` is kept. Plus `login`, `logout`, `fetchMe`, `forgotPassword`, `setPassword`.
  - `StaffApp`: loads `/me` once and provides `{ me, refresh }` through `StaffContext`. Any `unauthorised` result anywhere navigates to `/staff/login?next=<path>`. Routes as in the design's "Front end" section. Staff on `/staff/team` or `/staff/audit` see `You don't have access to this page`.
  - `StaffLayout`: the top bar (garage name, Day, Week, Team and Audit for admins only, the user's name, Log out).

- [ ] **Step 1: Write failing tests:** `logs in and returns to next`, `shows one error for a wrong login`, `redirects to login on a 401 from any call`, `forgot password always shows the same message`, `set password reads the token from the fragment and logs in`, `set password with a bad link shows the invalid message`, `staff see no Team or Audit links`, `staff opening team see the access message`, `staff pages do not wait for the catalogue` (with the catalogue fetch mocked to never resolve, `/staff/login` still renders).
- [ ] **Step 2: Run** `cd frontend; npm test` → FAIL.
- [ ] **Step 3: Implement.** Every page works at 360px, and buttons are at least 44px tall.
- [ ] **Step 4: Run** → PASS, then the frontend checks.
- [ ] **Step 5: Commit** `git commit -m "frontend - staff login and layout"`

---

### Task 14: Day and week schedule

**Files:**
- Create: `frontend/src/staff/schedule/DayView.tsx`, `WeekView.tsx`, `layout.ts`, `useSchedule.ts`, with tests `DayView.test.tsx`, `WeekView.test.tsx`, `layout.test.ts`

**Interfaces:**
- Consumes: `GET /schedule` (Task 7).
- Produces:
  - `layout.ts`: `placeItems(day: ScheduleDay, items: ScheduleItem[], zone: string): PlacedItem[]` (each with `bayId`, `topMinutes`, `heightMinutes` from the day's earliest opening) and `dayRange(day: ScheduleDay): { startMinutes: number; endMinutes: number }`.
  - `useSchedule(from: string, days: 1 | 7)` re-fetches every 30 seconds while `document.visibilityState === 'visible'`.
  - `DayView` at `/staff?date=` (defaults to today, garage-local) shows the grid at 700px and wider and the per-bay list with bay tabs below that. `WeekView` at `/staff/week?date=` shows Monday to Sunday. Both have **+ New booking** and **+ Block time** links (to `/staff/bookings/new?date=` and `/staff/blocks/new?date=`).
  - Item labels: a booking shows its time, registration, services and status (with `Phone booking · no deposit` and `No email, phone only` where they apply). A held booking shows `Being booked` and isn't a link. A block shows its note.

- [ ] **Step 1: Write failing tests:** `placeItems` (a 09:30–10:30 item on an 08:00 day → top 90, height 60; a clock-change day stays correct), `day view groups by bay and links bookings`, `day view on a narrow screen shows bay tabs` (mock `matchMedia`), `held booking is not a link`, `week view starts on Monday`, `prev and next change the date`, `refreshes after 30 seconds` (fake timers).
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the frontend checks.
- [ ] **Step 5: Commit** `git commit -m "frontend - staff day and week schedule"`

---

### Task 15: Booking detail, status, move and cancel

**Files:**
- Create: `frontend/src/staff/booking/BookingDetailPage.tsx`, `MovePanel.tsx`, `CancelPanel.tsx`, `TimePickerGrid.tsx`, with tests
- Modify: `frontend/src/staff/api.ts`

**Interfaces:**
- Consumes: Task 10 endpoints. `TimePickerGrid` takes `slots` (the availability body) and `onPick(start: string, bayId: number)`, and Task 16 reuses it.
- Produces: `/staff/bookings/:reference`, laid out as the design's sketch, with only the buttons in `actions`.
  - Start job asks `This job is booked for {day}. Start it now?` when `starts_on_another_day` is true.
  - Move: a date, then `TimePickerGrid`, an optional reason, and a confirm step with the copy `Have you called the customer? They'll be emailed the new time.` (or `They have no email, so remember to tell them.` when there's none).
  - Cancel: an optional reason and a confirm step. A 503 shows `We couldn't cancel just now. Please try again.`
  - A 409 `taken` shows `That time has just been taken` and reloads the times. A 409 `not_allowed` reloads the booking.

- [ ] **Step 1: Write failing tests:** `shows only the allowed buttons`, `start on another day asks first`, `move picks a time and bay and confirms`, `move into a taken time reloads the times`, `cancel shows the 503 message`, `history lists entries`, `phone booking without email warns on move`.
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the frontend checks.
- [ ] **Step 5: Commit** `git commit -m "frontend - staff booking detail, move and cancel"`

---

### Task 16: Phone booking and block forms

**Files:**
- Create: `frontend/src/staff/forms/NewBookingPage.tsx`, `NewBlockPage.tsx`, with tests
- Modify: `frontend/src/staff/api.ts`

**Interfaces:**
- Consumes: `GET /api/catalogue` (the existing `fetchCatalogue`, for the service list, including needs-approval services), `GET /api/staff/availability`, `POST /api/staff/bookings`, `POST /api/staff/blocks`, `DELETE /api/staff/blocks/{id}`, `TimePickerGrid` (Task 15). The field checks reuse `frontend/src/booking/validation.ts`, with email optional.
- Produces:
  - `/staff/bookings/new?date=` as the design's sketch, with the note `No deposit is taken for phone bookings.`. On success it goes to the new booking's detail page.
  - `/staff/blocks/new?date=&bay=`: bay select (with `All bays`), start and end date and time, and a required note. A 409 lists the bookings in the way, each linking to its detail page, with `Call these customers and move or cancel their bookings first.`
  - A block item on the day view opens a small panel with **Remove block** (add it to `DayView` here).

- [ ] **Step 1: Write failing tests:** `books a phone customer without an email`, `email is optional but checked when given`, `mixed bay types show the API message`, `block form lists clashing bookings with links`, `block note is required`, `remove block asks to confirm and refreshes`.
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the frontend checks.
- [ ] **Step 5: Commit** `git commit -m "frontend - phone booking and block forms"`

---

### Task 17: Team and audit pages

**Files:**
- Create: `frontend/src/staff/admin/TeamPage.tsx`, `AuditPage.tsx`, with tests
- Modify: `frontend/src/staff/api.ts`

**Interfaces:**
- Consumes: Tasks 5 and 12 endpoints.
- Produces:
  - `/staff/team`: a list showing each person's state (`Invited`, `Active`, `Reset sent`, `Removed`), an invite form (name, email, role), and per-person buttons for role, Remove or Restore, and Send password reset, each with a confirm step. A 409 shows its detail.
  - `/staff/audit`: filters (from, to, staff, reference) and a paged list, each row showing the time, name, a readable action, the reference and the reason.

- [ ] **Step 1: Write failing tests:** `invites a staff member`, `duplicate email shows the message`, `last admin message on remove`, `reset asks to confirm`, `audit filters by reference and pages`.
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the frontend checks.
- [ ] **Step 5: Commit** `git commit -m "frontend - team and audit pages"`

---

### Task 18: Flows 5 and 6 end to end, and the spec update

**Files:**
- Create: `e2e/tests/staff.ts`, `e2e/tests/staff-schedule.spec.ts`, `e2e/tests/garage-change.spec.ts`
- Modify: `docs/SPEC.md`, `README.md`
- Test: the two spec files

**Interfaces:**
- Consumes: the sample accounts (Task 3), `chooseMotSlot`, `enterDetails`, `payInStripe`, `londonDate` (`e2e/tests/booking.ts`), `waitForEmail` (`e2e/tests/mailpit.ts`).
- Produces: `staff.ts` with `loginAs(page: Page, who: 'admin' | 'staff'): Promise<void>`.

- [ ] **Step 1: Write the end-to-end tests:**
  - `staff-schedule.spec.ts`, **flow 5**, following the design's E2E list:
    1. The staff user adds a phone booking without an email, for MOT on the first day with a free time (from tomorrow, via the staff availability).
    2. It appears on that day's view.
    3. They block Bay 1 for an hour the same day, with the note `Lift broken (e2e)`.
    4. They open the booking, press Start job (accepting the question), then Complete job.
    5. The admin logs in, and the audit page filtered by the booking's reference shows `Sam Staff` for the create, start and complete entries.
    6. Clean up by removing the block.
  - `staff-schedule.spec.ts`: `staff see no Team or Audit links and team shows the access message`.
  - `garage-change.spec.ts`, **flow 6**:
    1. A customer books and pays (as `self-service.spec.ts` does), with a unique email.
    2. The staff user moves the booking to another free time on the same day or the next free day, with the reason `Lift broken`.
    3. The `Your booking has moved` email arrives, containing the new time and `Lift broken`. Its link page shows the new time.
    4. Staff cancel the booking.
    5. The `We've had to cancel your booking` email arrives, and the customer's page shows `refund on its way` or `refunded`.
- [ ] **Step 2: Run** `docker compose up --build -d --wait`, then `cd e2e; npx playwright test` → the new tests pass, and the existing ones still pass.
- [ ] **Step 3: Update `docs/SPEC.md`** with every bullet in the design's "Changes to the spec" section, and add the sample logins and `create_admin` to `README.md`.
- [ ] **Step 4: Run** every check (backend, frontend, and e2e again) → all pass.
- [ ] **Step 5: Commit** `git add e2e docs/SPEC.md README.md; git commit -m "e2e - flows 5 and 6; spec and readme for the back office"`
