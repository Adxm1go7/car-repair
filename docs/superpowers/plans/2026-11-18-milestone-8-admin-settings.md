# Milestone 8: Admin Settings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admins edit services, bays, bay types, dated opening-hours timetables and the contact details from a Settings page. A change that would clash with existing bookings is refused with those bookings listed, and every change is audited.

**Architecture:** Opening hours move into timetables (`timetables` + per-timetable days and breaks). One repository function answers "which hours apply on this date?", and free times, the staff schedule and the public API all use it. Settings rules and clash checks live in a new `app/settings/` package. They sit behind admin-only routers under `/api/staff/settings`. A PostgreSQL advisory lock makes booking writes (shared) take turns with clash-checked admin changes (exclusive). The React Settings page lives at `/staff/settings/*` in the existing staff app.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, React + TypeScript + React Router + Vitest, Playwright.

**Spec:** [docs/superpowers/specs/2026-11-18-milestone-8-admin-settings-design.md](../specs/2026-11-18-milestone-8-admin-settings-design.md). Read it before starting. This plan doesn't repeat its reasons, screens or copy unless a step needs the exact value.

## Global Constraints

- Every settings route is under `/api/staff/settings`, admin only (401 without a session, 403 for staff). `"/api/staff/settings"` joins `ADMIN_STAFF_PREFIXES` in `app/staff/deps.py`. Writes need the Milestone 7 Origin check.
- **Bookings that count** in any clash check have status `held` (and not `expired_hold(now)`), `pending_approval`, `confirmed` or `in_progress`.
- **409 clash body** (bays and hours): `{"detail": "clashes", "bookings": [{"reference": str, "start": <garage-local ISO>, "bay": <bay name>, "held": bool}]}`, sent as a `JSONResponse`. Nothing is saved, and no audit entry is written.
- **Timetables:** the first starts on `2000-01-01`. A new one starts **tomorrow at the earliest** (garage-local `garage_timezone`), and `starts_on` is unique. Only future timetables (`starts_on > today`) can be edited or deleted, and `starts_on` itself is never edited.
- **Hours clash rule:** a booking clashes if, on its garage-local start date, the day is closed, it starts before opening, ends after closing, or overlaps a break. The bay buffer is not part of it.
- **Services:**
  - name: 1–100 characters, unique (case-insensitive)
  - category: 1–50 characters
  - description: 1–500 characters
  - duration: 15–480 minutes, a multiple of 15
  - price from: ≥ 0 pence; price to: null, or ≥ from
  - bay type and `approval_mode` (`instant` | `needs_approval`): set only on create
  - slug: made once from the name, ≤ 64 characters, never changed
- **Bays:** name 1–100 characters, unique (case-insensitive). Slug made once. Bay type: name 1–100 characters, unique, never renamed.
- **Contact:** `garage_contact` = `{name, address, phone, email}`. Name 1–100 characters, address 1–200 characters; phone and email go through `clean_phone` / `clean_email`.
- **Audit actions:**
  - `service.create|update|hide|show|move` (entity `service`)
  - `bay.create|rename|out_of_use|back_in_use` (`bay`)
  - `bay_type.create` (`bay_type`)
  - `hours.create|update|delete` (`timetable`)
  - `contact.update` (`setting`, entity id `0`)
- **Advisory lock key:** the constant `HOURS_AND_BAYS_LOCK = 0x6761726167` in `app/settings/lock.py`.
- No booking-rule setting (window, cut-off, cancellation, deposit, reminder, grid, buffer, holds) becomes editable.
- All DB access goes through a `Session` from `get_session`, the worker's session, or the command's session.
- Commit messages are `area - what`: one line, no body, no AI attribution.
- Backend checks before each commit (in `backend/`): `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`. Frontend (in `frontend/`): `npm test`, `npm run lint`, `npm run typecheck`.

## Review Focus

1. **A timetable change on or next to a clock-change weekend.** Free times and the staff day view use the new timetable's hours, at the right wall-clock times, from its first day. Pinned in Task 2 (`test_free_times_switch_timetable_across_clock_change`).
2. **Deleting a future timetable** when the one before it closes a day that now has bookings is refused and lists them, even though deleting "removes" hours. Pinned in Task 8 (`test_delete_refused_when_previous_hours_clash`).
3. **A hold past its time but not yet released** neither blocks an admin change nor gets revived into an out-of-use bay. Pinned in Task 4 (`test_expired_hold_does_not_count`) and Task 5 (`test_late_payment_into_out_of_use_bay_is_refunded`).
4. **Clearing a service's "price to"** by sending `null` clears it, while leaving the field out leaves it alone. Pinned in Task 6 (`test_patch_price_to_null_clears_it`).
5. **The booking day strip** across a timetable that closes a weekday: the days before the change stay bookable, and the days after are closed. Pinned in Task 3 (`bookable days follow the timetable in force on each date`).

---

## File map

| File | Responsibility |
| --- | --- |
| `backend/migrations/versions/0009_create_timetables.py` | Timetables; re-key hours and breaks |
| `backend/app/models/catalogue.py` | `Timetable`; `OpeningHours`/`OpeningHoursBreak` gain `timetable_id` |
| `backend/app/repositories/hours.py` | Which hours apply on a date |
| `backend/app/settings/lock.py` | Shared/exclusive advisory lock |
| `backend/app/settings/clashes.py` | Pure fit rule; clash queries |
| `backend/app/settings/slugs.py` | Slug-making |
| `backend/app/settings/services.py`, `bays.py`, `hours.py`, `contact.py` | Rules + audit for each area |
| `backend/app/api/staff_settings.py` | The admin settings routes |
| `frontend/src/staff/settings/*` | Settings page, tabs, clash list |

---

### Task 1: Timetable tables, migration and seed

**Files:**
- Create: `backend/migrations/versions/0009_create_timetables.py`
- Modify: `backend/app/models/catalogue.py`, `backend/app/models/__init__.py`, `backend/app/seed.py`
- Test: `backend/tests/integration/test_migrations.py`, `test_seed.py`, `test_catalogue_constraints.py`

**Interfaces:**
- Produces:
  - `Timetable(id, starts_on: date unique, created_by: int | None → staff_users, created_at)`, with `days: list[OpeningHours]`.
  - `OpeningHours` keyed by `(timetable_id, weekday)`. `OpeningHoursBreak` gains `timetable_id`, with a composite FK `(timetable_id, weekday)` → `opening_hours` (`ON DELETE CASCADE`). Existing checks are kept.
  - `FIRST_TIMETABLE_STARTS: Final = date(2000, 1, 1)` in `app/models/catalogue.py`.

- [ ] **Step 1: Write failing tests:**
  - `test_upgrade_moves_hours_into_first_timetable`: rows inserted at 0008 come out at 0009 under one timetable on `2000-01-01`, breaks included.
  - `test_downgrade_with_one_timetable_restores_hours`
  - `test_downgrade_refuses_with_two_timetables`: raises, and the message contains `"more than one timetable"`.
  - `test_seed_creates_first_timetable` (an empty DB gets one timetable with the demo hours; re-running adds nothing).
  - `test_timetable_start_is_unique`
  - `test_deleting_a_timetable_deletes_its_days_and_breaks`
- [ ] **Step 2: Run** `uv run pytest -q tests/integration/test_migrations.py tests/integration/test_seed.py tests/integration/test_catalogue_constraints.py` → FAIL.
- [ ] **Step 3: Implement.** Copy constraint text into the migration rather than importing models, as 0008 does. Downgrade: `raise RuntimeError("Can't downgrade: more than one timetable exists")` when the count is above 1.
- [ ] **Step 4: Run** → PASS, then the full backend checks. Any existing test that inserts `OpeningHours` directly gets a `timetable_id` (add a `make_timetable(session, starts_on, days)` helper to `tests/factories.py`).
- [ ] **Step 5: Commit** `git commit -m "backend - opening hours timetables"`

---

### Task 2: Hours in force for free times and the staff schedule

**Files:**
- Create: `backend/app/repositories/hours.py`
- Modify: `backend/app/repositories/availability.py`, `backend/app/schedule/view.py`
- Test: `backend/tests/integration/test_hours_in_force.py`, `test_staff_schedule_api.py`

**Interfaces:**
- Consumes: Task 1 models.
- Produces:
  - `@dataclass(frozen=True) class WeekdayHours: open: time | None; close: time | None; breaks: tuple[tuple[time, time], ...]`. Closed when `open` is None. `CLOSED: Final = WeekdayHours(None, None, ())`.
  - `week_of(timetable: Timetable) -> dict[int, WeekdayHours]`: weekday 0–6 → hours. A missing weekday row means `CLOSED`.
  - `timetable_on(session, day: date) -> Timetable`: the latest `starts_on <= day`, with days and breaks loaded.
  - `hours_on(session, days: Sequence[date]) -> dict[date, WeekdayHours]`: one query for the timetables involved, not one per day.
- [ ] **Step 1: Write failing tests:**
  - `test_timetable_on_picks_latest_started` (before, on and after a start date)
  - `test_hours_on_spans_two_timetables`
  - `test_free_times_follow_the_new_timetable` (public availability on each side of a change)
  - `test_free_times_switch_timetable_across_clock_change`: a timetable starting Sun 29 Mar 2026 with Sunday open 10:00–12:00; the first slot is 10:00 local, which is 09:00Z.
  - `test_schedule_days_follow_timetables` (the `days` in `GET /api/staff/schedule` across a change)
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement.** `day_availability_for` and `load_schedule` read `hours_on` instead of `OpeningHours` by weekday. The engine's own `DayHours` stays as it is.
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - hours in force on each date"`

---

### Task 3: Public opening hours by timetable

**Files:**
- Modify: `backend/app/api/catalogue.py`, `frontend/src/catalogue/types.ts`, `api.ts`, `openToday.ts`, `frontend/src/booking/days.ts`, `frontend/src/App.tsx`, `frontend/src/booking/BookPage.tsx`, `frontend/src/testing/fixtures.ts`
- Test: `backend/tests/integration/test_catalogue_api.py`; `frontend/src/catalogue/openToday.test.ts`, `frontend/src/booking/days.test.ts`, `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: Task 2 `timetable_on`; `load_booking_window_days`.
- Produces:
  - `GET /api/opening-hours` → `{"timetables": [{"starts_on": "YYYY-MM-DD", "days": [OpeningDayOut × 7]}]}`. It lists the timetable in force today, then every one starting on or before `today + booking_window_days`, oldest first. `OpeningDayOut` is unchanged.
  - Frontend `type Timetable = { starts_on: string; days: OpeningDay[] }`.
  - `hoursOn(timetables: Timetable[], date: string): OpeningDay`.
  - `bookableDays(today, windowDays, timetables: Timetable[])` and `openTodayText(timetables, now, timeZone)` take timetables.
- [ ] **Step 1: Write failing tests:**
  - backend: `test_opening_hours_lists_current_and_upcoming_timetables`, `test_opening_hours_omits_timetables_beyond_the_window`
  - frontend: `bookable days follow the timetable in force on each date` (Saturday open before 1 Dec, closed after)
  - frontend: `open today uses today's timetable`
  - frontend: `home page shows new hours from a date` (renders "New hours from Tue 1 Dec" and that week)
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the backend and frontend checks.
- [ ] **Step 5: Commit** `git commit -m "public - opening hours from a date"`

---

### Task 4: Clash rules and queries

**Files:**
- Create: `backend/app/settings/__init__.py`, `backend/app/settings/clashes.py`
- Test: `backend/tests/unit/test_hours_fit.py`, `backend/tests/integration/test_clash_queries.py`

**Interfaces:**
- Consumes: Task 2 `WeekdayHours`, `week_of`, `hours_on`.
- Produces:
  - `fits(hours: WeekdayHours, start: datetime, end: datetime) -> bool`: pure; `start` and `end` are garage-local.
  - `COUNTING_STATUSES: Final = ("held", "pending_approval", "confirmed", "in_progress")`.
  - `bookings_in_bay(session, bay_id: int, now: datetime) -> list[Booking]`: counting bookings in that bay ending after `now`, ignoring `expired_hold(now)`.
  - `bookings_outside(session, first: date, last: date | None, week: Mapping[int, WeekdayHours], zone: ZoneInfo, now: datetime) -> list[Booking]`: counting bookings whose local start date is in `[first, last)` and that don't `fits` `week[that date's weekday]`.
  - `@dataclass class Clash: reference: str; start: str; bay: str; held: bool`, plus `clash_body(bookings, zone) -> dict` producing the 409 body from Global Constraints.
- [ ] **Step 1: Write failing tests:**
  - unit: `test_fits_inside_hours`, `test_starts_before_opening`, `test_ends_after_closing`, `test_overlaps_break`, `test_touching_a_break_fits`, `test_closed_day_never_fits`
  - integration: `test_bookings_in_bay_counts_each_status` (cancelled, expired, completed and no-show excluded), `test_expired_hold_does_not_count`, `test_bookings_outside_respects_range_end`, `test_clash_body_shape`
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - clash checks for settings"`

---

### Task 5: The hours-and-bays lock, and bookings that come back

**Files:**
- Create: `backend/app/settings/lock.py`
- Modify: `backend/app/repositories/reservations.py` (`reserve`), `backend/app/schedule/changes.py` (`move_booking`, `change_status`), `backend/app/payments/service.py` (`_take_time_back`)
- Test: `backend/tests/integration/test_settings_lock.py`, `test_complete_deposit.py`, `test_staff_booking_changes.py`

**Interfaces:**
- Consumes: Task 2 `hours_on`; Task 4 `fits`.
- Produces:
  - `lock_shared(session) -> None` (`pg_advisory_xact_lock_shared`) and `lock_exclusive(session) -> None` (`pg_advisory_xact_lock`), both on `HOURS_AND_BAYS_LOCK`.
  - `reserve`, `move_booking` and `_take_time_back` call `lock_shared` first.
  - `_take_time_back` returns `False` (the payment is then refunded, by the existing path) when the bay is out of use or the booking doesn't `fits` the hours in force on its local date.
  - `change_status` raises `NotAllowed` for `undo_no_show` / `undo_complete` when the booking's bay is out of use.
- [ ] **Step 1: Write failing tests:**
  - `test_exclusive_waits_for_shared` (two connections: the exclusive lock blocks until the shared transaction commits)
  - `test_late_payment_into_out_of_use_bay_is_refunded`: hold, expire, bay set inactive, pay late → refund, no confirmed booking.
  - `test_late_payment_outside_new_hours_is_refunded`
  - `test_undo_no_show_refused_in_out_of_use_bay` (409 `not_allowed`)
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the full backend checks (the existing hold and reserve concurrency tests must still pass).
- [ ] **Step 5: Commit** `git commit -m "backend - lock booking writes against settings changes"`

---

### Task 6: Services API

**Files:**
- Create: `backend/app/settings/slugs.py`, `backend/app/settings/services.py`, `backend/app/api/staff_settings.py`
- Modify: `backend/app/main.py`, `backend/app/staff/deps.py` (`ADMIN_STAFF_PREFIXES`)
- Test: `backend/tests/unit/test_slugs.py`, `backend/tests/integration/test_settings_services_api.py`, `test_staff_route_guards.py`

**Interfaces:**
- Produces:
  - `make_slug(name: str, taken: Collection[str]) -> str`: lowercase; runs of non-alphanumerics become `-`; trimmed; at most 64 characters; `-2`, `-3`… added on a collision. An empty result becomes `item`.
  - `router = APIRouter(prefix="/staff/settings", dependencies=[Depends(check_origin), Depends(require_admin)])`, which Tasks 7–9 add routes to.
  - `ServiceAdminOut {id, slug, name, category, description, duration_minutes, price_from_pence, price_to_pence, bay_type_id, bay_type, approval_mode, active, sort_order}`.
  - `GET /services` (all, by `sort_order, id`); `POST /services` → 201; `PATCH /services/{id}` (`name, category, description, duration_minutes, price_from_pence, price_to_pence, active`; a field left out stays unchanged, while `price_to_pence: null` clears it); `POST /services/{id}/move {"direction": "up"|"down"}` → 200 with the full list. Moving at either end changes nothing and writes no audit entry.
  - Name taken → 409 `{"detail": "That name is already used"}`. A bad field → 422.
- [ ] **Step 1: Write failing tests:**
  - `test_slug_from_name`, `test_slug_collision_gets_a_number`, `test_slug_trimmed_to_64`
  - `test_add_service_goes_last_and_shows_publicly`
  - `test_add_needs_approval_service`
  - `test_duplicate_name_is_409` (case-insensitive)
  - `test_duration_must_be_15_minute_steps` (422 for 50 and for 495)
  - `test_patch_leaves_out_fields_alone`, `test_patch_price_to_null_clears_it`
  - `test_patch_cannot_change_bay_type_or_approval_mode` (extra fields refused, 422)
  - `test_hide_and_show` (the public list follows; an existing booking is untouched)
  - `test_move_swaps_neighbours`, `test_move_at_the_end_is_a_no_op`
  - `test_editing_price_leaves_existing_booking_items`
  - `test_each_change_is_audited`
  - the route-guard walk finds `/api/staff/settings/services` as admin-only
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement.** Use `model_fields_set` for PATCH. Hide and show are `PATCH {active}`, audited as `service.hide` / `service.show`.
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - services settings"`

---

### Task 7: Bays and bay types API

**Files:**
- Create: `backend/app/settings/bays.py`
- Modify: `backend/app/api/staff_settings.py`, `backend/app/schedule/view.py`, `backend/app/api/staff_schedule.py`
- Test: `backend/tests/integration/test_settings_bays_api.py`, `test_settings_bays_concurrency.py`, `test_staff_schedule_api.py`

**Interfaces:**
- Consumes: Task 4 `bookings_in_bay`, `clash_body`; Task 5 `lock_exclusive`; Task 6 `make_slug`, `router`.
- Produces:
  - `BayAdminOut {id, slug, name, bay_type_id, bay_type, active}` and `BayTypeOut {id, slug, name}`.
  - `GET /bays`, `POST /bays {name, bay_type_id}` → 201, `PATCH /bays/{id} {name?, active?}`.
  - `GET /bay-types`, `POST /bay-types {name}` → 201.
  - `active: false` takes `lock_exclusive`, then refuses with the 409 clash body if `bookings_in_bay` is non-empty.
  - `extend_all_bay_blocks(session, bay: Bay, now) -> None`: runs on add and on `active: true`. For each `Block` with `all_bays`, `removed_at IS NULL` and `end_at > now`, it inserts `kind="block"` reservations for this bay over `[max(start_at, now), end_at)`, minus that bay's existing active reservations.
  - The schedule's `bays` also include out-of-use bays that have items in the range. Its `BayOut` gains `active: bool`.
- [ ] **Step 1: Write failing tests:**
  - `test_add_bay_is_bookable_at_once`, `test_rename_bay`, `test_duplicate_bay_name_is_409`
  - `test_out_of_use_refused_with_bookings_listed` (and the bay stays active, with no audit entry)
  - `test_out_of_use_lists_a_hold_as_held`
  - `test_out_of_use_with_no_bookings`: it disappears from free times.
  - `test_back_in_use_needs_no_check`
  - `test_new_bay_joins_future_all_bay_blocks`, `test_restored_bay_skips_its_own_block_time`
  - `test_add_bay_type_and_cannot_rename` (PATCH absent → 405)
  - `test_schedule_shows_out_of_use_bay_only_on_days_with_items`
  - `test_bay_changes_are_audited`
  - concurrency: `test_hold_racing_out_of_use_one_wins`, which ends in either the hold succeeding and out-of-use returning 409, or out-of-use succeeding and the hold being refused.
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - bays and bay types settings"`

---

### Task 8: Hours (timetables) API

**Files:**
- Create: `backend/app/settings/hours.py`
- Modify: `backend/app/api/staff_settings.py`
- Test: `backend/tests/integration/test_settings_hours_api.py`, `test_settings_hours_concurrency.py`

**Interfaces:**
- Consumes: Task 1 models; Task 4 `bookings_outside`, `clash_body`; Task 5 `lock_exclusive`.
- Produces:
  - `DayIn {weekday: 0–6, open: "HH:MM"|null, close: "HH:MM"|null, breaks: [{start, end}]}`. Exactly seven days, each weekday once. `open` and `close` are both set or both null, with open before close. Breaks lie inside the hours, start before end, and don't overlap one another.
  - `GET /hours` → `[{id, starts_on, state: "past"|"current"|"future", days: [...]}]`, oldest first.
  - `POST /hours {starts_on, days}` → 201. `starts_on` before tomorrow → 422 `"New hours can start tomorrow at the earliest"`; a date already used → 422 `"There are already hours from that date"`.
  - `PUT /hours/{id} {days}` and `DELETE /hours/{id}` → 204. Past or current → 409 `{"detail": "not_allowed"}`.
  - The range checked: `[starts_on, next starts_on)`. For a delete, the hours checked are the previous timetable's. All three take `lock_exclusive` before checking.
- [ ] **Step 1: Write failing tests:**
  - `test_list_marks_past_current_future`
  - `test_add_from_tomorrow`, `test_add_today_is_422`, `test_add_on_a_taken_date_is_422`
  - `test_add_refused_when_a_booking_falls_outside` (closed day / earlier closing / a new break), with the clash body and nothing saved
  - `test_add_ignores_bookings_after_the_next_timetable`
  - `test_edit_future_refused_on_clash`, `test_edit_current_is_409`
  - `test_delete_future`, `test_delete_refused_when_previous_hours_clash`
  - `test_breaks_outside_hours_or_overlapping_are_422`
  - `test_hours_changes_are_audited` (the snapshot holds all seven days)
  - concurrency: `test_hold_racing_shorter_hours_one_wins`
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - opening hours settings"`

---

### Task 9: Contact details API

**Files:**
- Create: `backend/app/settings/contact.py`
- Modify: `backend/app/api/staff_settings.py`
- Test: `backend/tests/integration/test_settings_contact_api.py`

**Interfaces:**
- Produces: `GET /contact` and `PUT /contact {name, address, phone, email}` → 200 with the saved values (cleaned). Audited as `contact.update`, entity `setting`, id `0`.
- [ ] **Step 1: Write failing tests:** `test_read_contact`, `test_save_contact_shows_on_public_garage`, `test_bad_email_or_blank_address_is_422`, `test_queued_email_sent_after_change_uses_new_details`, `test_contact_change_is_audited`.
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the full backend checks.
- [ ] **Step 5: Commit** `git commit -m "backend - contact settings"`

---

### Task 10: Settings page and the Services tab

**Files:**
- Create: `frontend/src/staff/settings/SettingsPage.tsx`, `ServicesTab.tsx`, `ServiceForm.tsx`, with tests
- Modify: `frontend/src/staff/api.ts`, `types.ts`, `StaffApp.tsx`, `StaffLayout.tsx`, `staff.css`

**Interfaces:**
- Consumes: Task 6 endpoints.
- Produces:
  - Routes `/staff/settings` (redirects to `services`) and `/staff/settings/:tab` (`services|bays|hours|contact`), inside `AdminOnly`. A **Settings** nav link for admins.
  - `api.ts`: `fetchAdminServices`, `addService`, `updateService(id, change)`, `moveService(id, direction)`.
  - `ServiceForm` takes `mode: 'add' | 'edit'`: bay type and approval mode appear only in add.
  - Prices are typed in pounds (e.g. `54.85`) and sent in pence.
- [ ] **Step 1: Write failing tests:**
  - `staff see the access message on settings`
  - `lists services with price and shown or hidden`
  - `adds a service`
  - `duplicate name shows the message`
  - `edit has no bay type or approval fields`
  - `hide asks to confirm`
  - `up and down reorder`
  - `warns when the bay type has no bay in use`
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the frontend checks.
- [ ] **Step 5: Commit** `git commit -m "frontend - settings page and services"`

---

### Task 11: Bays tab, clash list and the schedule's out-of-use bays

**Files:**
- Create: `frontend/src/staff/settings/BaysTab.tsx`, `ClashList.tsx`, with tests
- Modify: `frontend/src/staff/api.ts`, `types.ts`, `schedule/DayView.tsx`, `schedule/WeekView.tsx`, `frontend/src/testing/schedule.ts`

**Interfaces:**
- Consumes: Task 7 endpoints and the schedule's `active` field.
- Produces: `ClashList({ bookings: Clash[] })`, which lists each booking with its garage-local day and time, its bay, and a link to `/staff/bookings/:reference`; held ones are marked "being paid for, clears in a few minutes". Hours (Task 12) reuses it.
- [ ] **Step 1: Write failing tests:**
  - `adds a bay and a bay type`
  - `renames a bay`
  - `out of use asks to confirm and lists bookings in the way`
  - `last bay of its type warns before going out of use`
  - `puts a bay back in use`
  - `day view marks an out-of-use bay`
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the frontend checks.
- [ ] **Step 5: Commit** `git commit -m "frontend - bays settings"`

---

### Task 12: Hours tab

**Files:**
- Create: `frontend/src/staff/settings/HoursTab.tsx`, `TimetableForm.tsx`, with tests
- Modify: `frontend/src/staff/api.ts`, `types.ts`

**Interfaces:**
- Consumes: Task 8 endpoints; Task 11 `ClashList`.
- Produces: a timetable list showing "Now (since the start)" for the first timetable while it's current, and "From Tue 1 Dec" otherwise. Edit and Delete appear only on future timetables. New hours: a date that's tomorrow at the earliest, with the week prefilled from the timetable in force the day before.
- [ ] **Step 1: Write failing tests:**
  - `lists timetables with edit only on future ones`
  - `new hours prefill from the timetable before`
  - `a closed day hides its times`
  - `a clash lists the bookings and saves nothing`
  - `delete asks to confirm`
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the frontend checks.
- [ ] **Step 5: Commit** `git commit -m "frontend - opening hours settings"`

---

### Task 13: Contact tab and audit wording

**Files:**
- Create: `frontend/src/staff/settings/ContactTab.tsx`, with a test
- Modify: `frontend/src/staff/admin/AuditPage.tsx` (`describe`), `AuditPage.test.tsx`, `frontend/src/staff/api.ts`

**Interfaces:**
- Consumes: Task 9 endpoints; the audit actions in Global Constraints.
- Produces: audit wording for each action, for example:
  - "Added service MOT test"
  - "Hid service Diagnostic check"
  - "Took Bay 3 out of use"
  - "Put Bay 3 back in use"
  - "Added bay type Tyre bay"
  - "New hours from Tue 1 Dec"
  - "Changed hours from Tue 1 Dec"
  - "Deleted hours from Tue 1 Dec"
  - "Changed contact details"
- [ ] **Step 1: Write failing tests:**
  - `saves contact details`
  - `bad email shows the message`
  - `audit describes settings changes` (one assertion per action)
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the frontend checks.
- [ ] **Step 5: Commit** `git commit -m "frontend - contact settings and audit wording"`

---

### Task 14: End-to-end settings flow, spec and README

**Files:**
- Create: `e2e/tests/admin-settings.spec.ts`
- Modify: `docs/SPEC.md`, `README.md`

**Interfaces:**
- Consumes: `loginAs`, `staffSlots`, `daySchedule` (`e2e/tests/staff.ts`); `londonDate` (`e2e/tests/booking.ts`).

- [ ] **Step 1: Write the end-to-end test** `admin settings: services, a refused clash, and future hours`:
  1. Admin adds a service `E2E service <timestamp>` (general bay, 30 minutes, £10). It appears on the public home page. The admin hides it, and it's gone.
  2. As staff, make a phone booking (no email) for the first free MOT on a day at least 2 days ahead.
  3. Admin adds hours from that date with that weekday closed. The page lists the booking's reference, and the hours list is unchanged.
  4. Admin adds hours from the day after the booking with the same week. The home page shows "New hours from". The admin deletes them.
  5. Clean up: cancel the phone booking.
- [ ] **Step 2: Run** `docker compose up --build -d --wait`, then `cd e2e; npx playwright test` → the new test passes, and the existing ones still pass.
- [ ] **Step 3: Update `docs/SPEC.md`** with every bullet in the design's "Changes to the spec". Update the README's Staff back office section to mention Settings, and drop "Admin screens for editing the catalogue arrive in Milestone 8" plus the advice to edit `demo_data.py` for an existing database.
- [ ] **Step 4: Run** every check (backend, frontend, and e2e again) → all pass.
- [ ] **Step 5: Commit** `git add e2e docs/SPEC.md README.md; git commit -m "e2e - admin settings flow; spec and readme"`
