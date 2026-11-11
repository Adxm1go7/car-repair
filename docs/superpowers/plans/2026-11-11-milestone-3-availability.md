# Milestone 3: Availability Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pure, heavily tested engine answers "which start times are free for these services on this day?". A `reservations` table with a PostgreSQL exclusion constraint makes double-booking a bay impossible. A `reserve()` step and a concurrency test prove that, and `GET /api/availability` exposes the engine publicly.

**Architecture:** The engine lives in `app/availability/engine.py` as frozen dataclasses and one function, with no SQLAlchemy, FastAPI or clock imports. `app/repositories/availability.py` loads settings, services, bays, hours and reservations from the database, then calls the engine. `app/repositories/reservations.py` holds `reserve()`, which re-runs the engine and inserts inside savepoints, trusting the constraint as the final authority. The route in `app/api/availability.py` validates input, then calls the repository. "Now" comes from an overridable `utc_now` dependency.

**Tech Stack:** As in Milestones 1 and 2. The only new database feature is the `btree_gist` extension (built into PostgreSQL). No new Python dependencies.

**Spec:** [docs/superpowers/specs/2026-11-11-milestone-3-availability-design.md](../specs/2026-11-11-milestone-3-availability-design.md), which builds on [docs/SPEC.md](../../SPEC.md). Read the design doc first: it holds every rule and the reasons behind them.

## Global Constraints

- Everything from the Milestone 1 and 2 Global Constraints still applies: free tools only, no secrets, UTC timestamps, LF endings, the same versions, `main` protected.
- The branch is `milestone3-availability`. It merges through a PR.
- Grid, buffer, cut-off, window and opening hours are never hardcoded in app logic. They come from settings or tables. Defaults exist only in `DEFAULT_SETTINGS` and `app/demo_data.py`.
- The engine imports nothing from `sqlalchemy`, `fastapi` or `app.models`, and never calls `datetime.now()`.
- All stored times are UTC (`tstzrange`). All local reasoning uses the `garage_timezone` setting (`"Europe/London"`), never the server's zone.
- A booking occupies `[start, start + duration + buffer)` in its bay. Ranges are half-open `[)`, so back-to-back ranges don't overlap.
- No start inside a break. A started job runs through a break, and its end = start + duration in elapsed time.
- Starts step through local wall-clock time from opening time by `slot_grid_minutes`. A non-existent local time is skipped, and an ambiguous one uses `fold=0`.
- New settings: `slot_grid_minutes` = 30 and `bay_buffer_minutes` = 15, seeded without overwriting. That makes 9 settings in total.
- Commit messages follow the repo's style: `area - what`.

## Review Focus

1. **"Now" near midnight in summer time.** At `2026-07-01T23:30Z` it's already 2 July in London, so 1 July is in the past and 2 July is today. Pinned in Task 4.
2. **The engine and the constraint disagree about the buffer.** A start the engine offers must never be rejected by the constraint when the bay is otherwise empty, and a start whose buffer touches the next reservation must not be offered. Pinned in Task 2 (buffer tests) and Task 3 (a reserve straight after an existing booking).
3. **A stale engine view in `reserve()`.** A rival insert lands between the engine check and the insert. It must fall back to the next bay, or raise `SlotUnavailable`, and never surface as a 500 or an `IntegrityError`. Pinned in Task 3.
4. **Broken settings.** A missing, non-integer or out-of-range grid, buffer, cut-off or window, or an unknown timezone, must give a 503 with JSON, never a 500. Pinned in Task 4.
5. **The window edges.** Today and today + `booking_window_days` are accepted, and the day after is rejected. Pinned in Task 4.

---

## File Structure

```
.github/workflows/ci.yml                         # + availability smoke check
README.md                                        # + availability row in the Quick start table
backend/
  migrations/versions/0003_create_reservations.py
  app/
    clock.py                                     # NEW: utc_now dependency
    main.py                                      # + include availability router
    seed.py                                      # + 2 settings
    models/__init__.py                           # + re-export Reservation
    models/reservation.py                        # NEW: Reservation + exclusion constraint
    availability/__init__.py                     # NEW
    availability/engine.py                       # NEW: pure engine
    repositories/availability.py                 # NEW: load settings/data, call engine
    repositories/reservations.py                 # NEW: reserve(), SlotUnavailable
    api/availability.py                          # NEW: GET /api/availability
  tests/
    unit/test_availability_engine.py             # NEW
    unit/test_availability_clock_changes.py      # NEW
    integration/test_migrations.py               # + reservations
    integration/test_seed.py                     # 9 settings
    integration/test_reservation_constraints.py  # NEW
    integration/test_reserve.py                  # NEW
    integration/test_reserve_concurrency.py      # NEW
    integration/test_availability_api.py         # NEW
```

All backend commands run from `backend/`.

---

### Task 1: Branch, `reservations` table and the two new settings

**Files:**
- Create: `backend/app/models/reservation.py`, `backend/migrations/versions/0003_create_reservations.py`, `backend/tests/integration/test_reservation_constraints.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/seed.py`, `backend/tests/integration/test_migrations.py`, `backend/tests/integration/test_seed.py`

**Interfaces:**
- Consumes: `Base` with its naming convention, `Bay`, `seed`, and the fixtures `fresh_database_url`, `db_session` and `alembic_config`.
- Produces:
  - `Reservation` (`reservations`), re-exported from `app.models`: `id: int` PK; `bay_id: int` (FK `bays.id`); `kind: str` (`String(20)`); `during: Range[datetime]` (`TSTZRANGE`, not null); `active: bool` (server default true); `note: str | None` (`Text`); `created_at: datetime` (`DateTime(timezone=True)`, server default `now()`); and a `bay` relationship.
  - Constraints:
    - `CheckConstraint("kind IN ('booking', 'block')", name="kind_valid")`
    - `CheckConstraint("NOT isempty(during) AND NOT lower_inf(during) AND NOT upper_inf(during)", name="during_bounded")`
    - `ExcludeConstraint((bay_id, "="), (during, "&&"), using="gist", where=text("active"), name="ex_reservations_no_overlap")`
  - Migration revision `"0003"`, `down_revision = "0002"`. `upgrade()` runs `CREATE EXTENSION IF NOT EXISTS btree_gist` first. `downgrade()` drops the table and leaves the extension.
  - `DEFAULT_SETTINGS` gains `"slot_grid_minutes": 30` and `"bay_buffer_minutes": 15`.

- [ ] **Step 1: Create the branch and commit the docs**

```bash
git switch main
git pull
git switch -c milestone3-availability
git add docs/superpowers
git commit -m "docs - milestone 3 availability design and plan"
```

- [ ] **Step 2: Write the failing tests**

In `test_migrations.py`, add `test_upgrade_head_creates_reservations` (`"reservations"` is in the table names after `head`) and `test_downgrade_to_0002_drops_reservations` (after downgrading to `"0002"`, `"reservations"` is gone and `"services"` remains).

In `test_seed.py`, add the two keys with values 30 and 15 to the expected dict in `test_seed_inserts_default_settings`, and change both `== 7` counts to `== 9`.

In `test_reservation_constraints.py`, call `seed(db_session)` and use the bays `bay-1` and `bay-2` looked up by slug. A helper builds `Range(at(h1, m1), at(h2, m2))` on 2026-11-10 UTC. Each bad insert runs inside `db_session.begin_nested()`.

| Test | Rows | Expect |
| --- | --- | --- |
| `test_overlapping_active_reservations_in_one_bay_are_rejected` | bay-1 `[09:00, 10:00)`, then bay-1 `[09:30, 10:30)` | `IntegrityError` whose `.orig.sqlstate == "23P01"` |
| `test_same_range_in_different_bays_is_allowed` | bay-1 and bay-2, both `[09:00, 10:00)` | no error |
| `test_back_to_back_reservations_are_allowed` | bay-1 `[09:00, 10:00)` and `[10:00, 11:00)` | no error |
| `test_overlap_with_an_inactive_reservation_is_allowed` | bay-1 `[09:00, 10:00)` with `active=False`, then bay-1 `[09:30, 10:30)` | no error |
| `test_kind_must_be_booking_or_block` | `kind="holiday"` | `IntegrityError` |
| `test_empty_range_is_rejected` | `Range(at(9, 0), at(9, 0))` | `IntegrityError` |
| `test_unbounded_range_is_rejected` | `Range(None, at(9, 0))` | `IntegrityError` |

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `uv run pytest tests/integration/test_migrations.py tests/integration/test_seed.py tests/integration/test_reservation_constraints.py -v`
Expected: FAIL with `ImportError` for `Reservation`, a missing table, or settings counts of 7.

- [ ] **Step 4: Implement the model, the two settings, and migration `0003`**

Autogenerate with `uv run alembic revision --autogenerate --rev-id 0003 -m "create reservations"`. Then rename the file to `0003_create_reservations.py`, add the `btree_gist` extension line at the top of `upgrade()`, and check that both check constraints and the exclusion constraint (with its `WHERE (active)`) are in it. Add any that autogenerate missed by hand.

- [ ] **Step 5: Run the full suite and checks**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all pass, including `test_models_match_migrations`.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "backend - reservations table with no-overlap constraint, grid and buffer settings"
```

---

### Task 2: The pure engine

**Files:**
- Create: `backend/app/availability/__init__.py`, `backend/app/availability/engine.py`, `backend/tests/unit/test_availability_engine.py`, `backend/tests/unit/test_availability_clock_changes.py`

**Interfaces:**
- Consumes: nothing from the app, only the standard library.
- Produces, in `app/availability/engine.py` (all dataclasses `frozen=True`):
  - `ServiceInfo(id: int, duration_minutes: int, bay_type_id: int)`
  - `BayInfo(id: int, bay_type_id: int)`
  - `DayHours(open: time, close: time, breaks: tuple[tuple[time, time], ...] = ())`, in local wall-clock time
  - `Occupied(bay_id: int, start: datetime, end: datetime)`, aware and half-open
  - `Policy(zone: ZoneInfo, grid_minutes: int, buffer_minutes: int, cutoff_minutes: int)`
  - `Slot(start: datetime, end: datetime, bay_ids: tuple[int, ...])`: `start` and `end` are aware in `policy.zone`, `end` is the real end without the buffer, and `bay_ids` are ascending
  - `DayAvailability(duration_minutes: int, slots: tuple[Slot, ...], unavailable_reason: Literal["mixed_bay_types"] | None)`
  - `find_slots(day: date, services: Sequence[ServiceInfo], bays: Sequence[BayInfo], hours: DayHours | None, occupied: Sequence[Occupied], policy: Policy, now: datetime) -> DayAvailability`. It raises `ValueError` if `services` is empty or `now` is naive. `hours=None` means closed. `duration_minutes` is the sum of the services' durations, even when there are no slots.

The rules are in the design doc's "The engine" section, steps 1–6. Compare instants in UTC. Compute `end = (start_utc + duration).astimezone(zone)`. A bay is free for a start when `[start, end + buffer)` overlaps none of its `occupied` ranges.

- [ ] **Step 1: Write the failing tests** in `test_availability_engine.py`

Shared setup: `ZONE = ZoneInfo("Europe/London")`; `DAY = date(2026, 11, 10)` (a Tuesday, GMT, so local equals UTC); `NOW = datetime(2026, 11, 1, tzinfo=UTC)`; `WEEKDAY = DayHours(time(8), time(17, 30), ((time(12, 30), time(13)),))`; `GENERAL, MOT = 1, 2`; general bays `BayInfo(1, GENERAL)`, `BayInfo(2, GENERAL)`, `BayInfo(3, GENERAL)` and `BayInfo(10, MOT)`; and `policy(grid=30, buffer=15, cutoff=120)`. Two helpers: `at(h, m) -> datetime` on `DAY` in `ZONE`, and `starts(result) -> list[str]` giving the local `"HH:MM"` values. Unless a row says otherwise, use all four bays, `WEEKDAY`, no occupied ranges and `NOW`.

| Test | Setup | Assert |
| --- | --- | --- |
| `test_mot_offers_grid_starts_except_inside_lunch` | one 60-min MOT service | `starts == ["08:00", "08:30", … "12:00", "13:00", … "16:30"]`, 17 items |
| `test_slot_has_real_end_and_every_free_bay` | 180-min general | first slot is start `at(8, 0)`, end `at(11, 0)`, `bay_ids == (1, 2, 3)` |
| `test_job_must_finish_by_closing` | 180-min general | last start `"14:30"` |
| `test_job_may_end_exactly_at_closing` | 60-min general | `"16:30"` in starts, `"17:00"` not |
| `test_job_runs_through_lunch_with_unchanged_end` | 360-min general | `starts == ["08:00" … "11:30"]` (8 items), and the 08:00 slot ends `at(14, 0)` |
| `test_no_start_inside_a_break` | 30-min general | `"12:00"` and `"13:00"` in starts, `"12:30"` not |
| `test_duration_longer_than_the_day_gives_no_slots` | 600-min general | `slots == ()`, `unavailable_reason is None` |
| `test_previous_jobs_buffer_delays_the_next_start` | MOT, occupied bay 10 `[08:00, 09:15)` | first start `"09:30"` |
| `test_own_buffer_cannot_overlap_the_next_reservation` | MOT, occupied bay 10 `[10:00, 11:00)` | `"08:30"` in starts, `"09:00"` not |
| `test_zero_buffer_allows_back_to_back` | MOT, buffer 0, occupied bay 10 `[08:00, 09:00)` and `[10:00, 11:00)` | `"09:00"` in starts |
| `test_buffer_cannot_overlap_a_block` | MOT, block on bay 10 `[10:00, 12:00)` | `"09:00"` not in starts |
| `test_full_day_block_on_one_bay_removes_only_that_bay` | 60-min general, bay 1 `[08:00, 17:30)` | every slot has `bay_ids == (2, 3)` |
| `test_partial_block_on_one_bay` | 60-min general, bay 1 `[08:00, 10:00)` | 08:00 slot `(2, 3)`, 10:00 slot `(1, 2, 3)` |
| `test_block_on_all_bays_gives_no_slots` | 60-min general, bays 1–3 `[08:00, 17:30)` | `slots == ()` |
| `test_other_bay_types_are_ignored` | 60-min general, bay 10 occupied all day | 17 starts, no slot contains bay 10 |
| `test_long_job_fits_fewer_bays_than_short_job` | bay 1 occupied `[11:00, 12:00)`, 180 vs 60 min | 180-min 08:00 slot `(2, 3)`; 60-min 08:00 slot `(1, 2, 3)` |
| `test_mixed_bay_types_give_reason_and_no_slots` | MOT 60 + general 180 | `slots == ()`, `unavailable_reason == "mixed_bay_types"`, `duration_minutes == 240` |
| `test_durations_are_summed` | general 180 + general 90 | `duration_minutes == 270`, the 08:00 slot ends `at(12, 30)`, last start `"13:00"` |
| `test_closed_day_gives_no_slots` | `hours=None` | `slots == ()`, `unavailable_reason is None` |
| `test_cutoff_drops_early_starts` | no breaks, `now = at(10, 5)` | first start `"12:30"` |
| `test_start_exactly_at_cutoff_is_allowed` | no breaks, `now = at(10, 0)` | first start `"12:00"` |
| `test_grid_is_anchored_at_opening_time` | `DayHours(time(8, 15), time(12))` | starts begin `["08:15", "08:45"]` |
| `test_two_breaks` | breaks 10:00–10:30 and 15:00–15:15 | `"10:00"` and `"15:00"` not in starts, `"10:30"` and `"15:30"` are |
| `test_empty_services_or_naive_now_raise` | `[]`, or `now=datetime(2026, 11, 1)` | `ValueError` |

In `test_availability_clock_changes.py`, use one 60-min general service, one general bay, buffer 0 and cut-off 0. Compare starts as full ISO strings (`slot.start.isoformat()`).

| Test | Day and hours | Expected starts |
| --- | --- | --- |
| `test_spring_forward_skips_missing_times_and_measures_elapsed_time` | 2027-03-28, 00:00–04:00 | `00:00+00:00`, `00:30+00:00`, `02:00+01:00`, `02:30+01:00`, `03:00+01:00` (with the date prefix); the 00:30 slot ends `02:30+01:00` |
| `test_fall_back_uses_first_occurrence_and_never_duplicates` | 2026-10-25, 00:00–03:00 | `00:00+01:00`, `00:30+01:00`, `01:00+01:00`, `01:30+01:00`, `02:00+00:00` — no duplicates |
| `test_demo_hours_carry_the_right_offset` | 2026-10-23 and 2026-10-26, `WEEKDAY` | the first start is `2026-10-23T08:00:00+01:00` and `2026-10-26T08:00:00+00:00` |

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest tests/unit -v`
Expected: FAIL with `ModuleNotFoundError: app.availability`.

- [ ] **Step 3: Implement `app/availability/engine.py`**

To turn local wall-clock times into aware datetimes, use `datetime.combine(day, t, tzinfo=zone)`, which is `fold=0` by default. A local time doesn't exist if converting it to UTC and back doesn't give the same wall time; skip it. Grid stepping happens on naive wall times, so `08:00 + 30 min` is always `08:30` local.

- [ ] **Step 4: Run the tests and checks**

Run: `uv run pytest tests/unit -v && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "backend - pure availability engine with buffer, breaks and clock changes"
```

---

### Task 3: Loading the data, `reserve()` and the concurrency test

**Files:**
- Create: `backend/app/repositories/availability.py`, `backend/app/repositories/reservations.py`, `backend/tests/integration/test_reserve.py`, `backend/tests/integration/test_reserve_concurrency.py`

**Interfaces:**
- Consumes: the engine types and `find_slots` (Task 2), `Reservation` (Task 1), the catalogue models, `get_setting`, `seed`, and the fixtures `db_session`, `fresh_database_url` and `alembic_config`.
- Produces:
  - In `app/repositories/availability.py`:
    - `class SettingsUnavailable(Exception)`
    - `load_policy(session: Session) -> Policy` reads `garage_timezone` (must load as a `ZoneInfo`), `slot_grid_minutes` (an int ≥ 5), `bay_buffer_minutes` (an int ≥ 0) and `booking_cutoff_minutes` (an int ≥ 0). `bool` doesn't count as an int. Any failure raises `SettingsUnavailable`.
    - `load_booking_window_days(session: Session) -> int` (an int ≥ 0, else `SettingsUnavailable`)
    - `find_active_services(session: Session, slugs: Sequence[str]) -> list[Service]` returns the active services whose slug is in `slugs`, in `slugs` order. Missing ones are just absent.
    - `day_availability(session: Session, services: Sequence[Service], day: date, now: datetime, policy: Policy) -> DayAvailability` loads the active bays, that weekday's hours (a missing row or null times means `None`), and the **active** reservations overlapping the local day `[midnight, next midnight)` in UTC, then returns `find_slots(...)`.
  - In `app/repositories/reservations.py`:
    - `class SlotUnavailable(Exception)`
    - `ReserveResult(reservation: Reservation, start: datetime, end: datetime)`, frozen, with local aware `start` and `end`
    - `reserve(session: Session, service_ids: Sequence[int], start: datetime, now: datetime, cutoff_minutes: int | None = None) -> ReserveResult`. It raises `ValueError` for a naive `start` or an unknown or inactive service ID. It uses `load_policy`, with `cutoff_minutes` replacing the setting when it isn't `None`, and calls `day_availability` for `start`'s local date. It finds the slot whose start equals `start` as an instant (else `SlotUnavailable`), then for each bay in `bay_ids` adds `Reservation(kind="booking", during=Range(start_utc, end_utc + buffer))` inside `session.begin_nested()` and flushes. On an `IntegrityError` whose `.orig.sqlstate == "23P01"`, it moves to the next bay; any other error is re-raised. After the last bay it raises `SlotUnavailable`. It doesn't commit.

- [ ] **Step 1: Write the failing tests** in `test_reserve.py`

Each test calls `seed(db_session)`. Use `NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)`, `DAY = 2026-11-10`, and `start = datetime(2026, 11, 10, 9, tzinfo=ZoneInfo("Europe/London"))`.

| Test | Assert |
| --- | --- |
| `test_reserve_mot_stores_range_with_buffer` | reserving `mot-test` at 09:00 gives `result.end` 10:00 local, the reservation is in the `mot-bay`, and `during == Range(09:00Z, 10:15Z)` with `kind == "booking"` |
| `test_reserve_next_to_an_existing_booking_succeeds` | reserve MOT 09:00, then MOT 10:30 (the first's buffer ends 10:15): both succeed |
| `test_reserve_start_not_on_the_grid_is_unavailable` | 09:10 raises `SlotUnavailable` |
| `test_reserve_taken_single_bay_is_unavailable` | reserve MOT 09:00 twice: the second raises `SlotUnavailable`, and one active row exists |
| `test_reserve_spreads_across_general_bays_then_runs_out` | reserve `full-service` at 09:00 four times: three succeed in `bay-1`, `bay-2` and `bay-3` (ascending `id`), and the fourth raises `SlotUnavailable` |
| `test_reserve_falls_back_when_constraint_rejects` | Simulates a rival insert. Call the real `day_availability` for `full-service` on `DAY` and keep the result (`stale`). Then insert an active reservation directly in `bay-1` over 09:00–12:15, and `monkeypatch` `app.repositories.reservations.day_availability` to return `stale`. Reserving full-service at 09:00 lands in `bay-2`, with no exception |
| `test_reserve_raises_slot_unavailable_when_every_bay_rejects` | the same stale patch, with bays 1–3 all filled directly: `SlotUnavailable`, never `IntegrityError` |
| `test_inactive_reservations_do_not_block` | insert an `active=False` reservation over MOT 09:00: reserving MOT 09:00 succeeds |
| `test_cutoff_override_allows_a_start_inside_the_cutoff` | with `now` = 08:30 local on `DAY`, MOT 09:00 raises `SlotUnavailable` by default, and succeeds with `cutoff_minutes=0` |
| `test_unknown_service_or_naive_start_raises_value_error` | `ValueError` |
| `test_load_policy_rejects_broken_settings` | parametrised: delete `slot_grid_minutes`; `slot_grid_minutes = 4`; `bay_buffer_minutes = -1`; `booking_cutoff_minutes = "soon"`; `slot_grid_minutes = true`; `garage_timezone = "Mars/Base"`. Each raises `SettingsUnavailable` |

In `test_reserve_concurrency.py`, write `test_two_simultaneous_reserves_of_one_bay_have_exactly_one_winner`. Upgrade `fresh_database_url` to `head`, then seed and **commit** (the threads need committed data on their own connections). Run 5 rounds, with MOT starts at 08:00, 09:00, 10:00, 11:00 and 13:00 on `DAY`. Each round starts two threads on separate `Session(engine)`s. Each thread waits on a shared `threading.Barrier(2)`, calls `reserve`, then commits on success or rolls back on `SlotUnavailable`, and records `"won"` or `"lost"`. Assert that each round's outcomes, sorted, are `["lost", "won"]`, and that the database ends with exactly 5 active reservations. Join the threads with a timeout, and fail if one is still alive.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest tests/integration/test_reserve.py tests/integration/test_reserve_concurrency.py -v`
Expected: FAIL with `ModuleNotFoundError` for the new repository modules.

- [ ] **Step 3: Implement both repository modules**

- [ ] **Step 4: Run the full suite and checks**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all pass. Then run `uv run pytest tests/integration/test_reserve_concurrency.py -v` three more times. It must pass every time.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "backend - load availability data, reserve a slot, concurrency test"
```

---

### Task 4: `GET /api/availability`

**Files:**
- Create: `backend/app/clock.py`, `backend/app/api/availability.py`, `backend/tests/integration/test_availability_api.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `load_policy`, `load_booking_window_days`, `find_active_services`, `day_availability` and `SettingsUnavailable` (Task 3); `get_session`; and the fixtures `api_client` and `db_session`.
- Produces:
  - `app/clock.py`: `utc_now() -> datetime` returns `datetime.now(UTC)`. Routes take it via `Depends(utc_now)`, and tests set `api_client.app.dependency_overrides[utc_now]`.
  - `app/api/availability.py`: `router = APIRouter()`, included in `create_app` with `prefix="/api"`.
    - `SlotOut(start: str, end: str)`. These are `isoformat()` strings in garage local time, for example `"2026-11-10T08:00:00+00:00"`. They're strings so Pydantic can't turn `+00:00` into `Z`.
    - `AvailabilityOut(date: str, timezone: str, duration_minutes: int, unavailable_reason: Literal["mixed_bay_types"] | None, slots: list[SlotOut])`
    - `GET /api/availability?services=<slug>&services=<slug>&date=YYYY-MM-DD` → `AvailabilityOut`. The `services` parameter is a required `list[str]`, and `date` is a `date` (use `Query(alias="date")`).
    - 422 (`HTTPException`) for an empty or repeated slug, an unknown or inactive slug, a date before today in the garage zone, or a date after today + window. FastAPI's own 422 covers a missing `services` and an invalid `date`.
    - 503 with `{"detail": "Availability unavailable"}` on `SettingsUnavailable`.

- [ ] **Step 1: Write the failing tests** in `test_availability_api.py`

Each test calls `seed(db_session)` (except the 503 test, which edits after seeding) and overrides `utc_now` to `NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)` unless stated. `DAY = "2026-11-10"`, a Tuesday.

| Test | Request / setup | Assert |
| --- | --- | --- |
| `test_mot_returns_slots_in_local_time` | `services=mot-test&date=2026-11-10` | 200; `date`, `timezone == "Europe/London"`, `duration_minutes == 60`, `unavailable_reason is None`; 17 slots; first is `{"start": "2026-11-10T08:00:00+00:00", "end": "2026-11-10T09:00:00+00:00"}`; no key containing `"bay"` anywhere |
| `test_summer_date_has_bst_offset` | `NOW = datetime(2026, 7, 1, 8, tzinfo=UTC)`, `date=2026-07-02` | first start `"2026-07-02T08:00:00+01:00"` |
| `test_multi_service_sums_durations` | `services=full-service&services=front-brake-pads` | `duration_minutes == 270`, 10 slots, first `08:00`–`12:30`, last starts `13:00` |
| `test_mixed_bay_types` | `mot-test` + `full-service` | 200, `slots == []`, `unavailable_reason == "mixed_bay_types"` |
| `test_closed_day_has_no_slots` | set Tuesday's `OpeningHours` times to `None`, flush | 200, `slots == []`, reason `None` |
| `test_existing_reservation_removes_slots` | insert MOT-bay booking `[08:00Z, 09:15Z)` | `08:00`, `08:30` and `09:00` gone, `09:30` present |
| `test_needs_approval_services_get_slots` | `clutch-replacement` | 8 slots, first ends `"…T14:00:00+00:00"` |
| `test_rejects_bad_services` | parametrised: none; `services=`; `mot-test` twice; `no-such-service`; `full-service` set inactive | 422 |
| `test_rejects_bad_dates` | parametrised: `date=2026-13-01`; `date=2026-11-08` (yesterday) | 422 |
| `test_window_edges` | `date=2026-11-09` (today), `2027-01-08` (today + 60), `2027-01-09` | 200, 200, 422 |
| `test_today_follows_garage_zone_near_midnight` | `NOW = 2026-07-01T23:30Z` | `date=2026-07-01` → 422; `date=2026-07-02` → 200 |
| `test_broken_settings_give_503` | parametrised: delete `slot_grid_minutes`; `garage_timezone = "Mars/Base"`; `booking_window_days = "lots"` | 503, body `{"detail": "Availability unavailable"}` |

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest tests/integration/test_availability_api.py -v`
Expected: FAIL. `app.clock` doesn't exist, or the route returns 404.

- [ ] **Step 3: Implement `app/clock.py` and the router, and wire the router into `create_app`**

Work out "today" as `now.astimezone(policy.zone).date()`. Check the window as `today <= day <= today + timedelta(days=window)`.

- [ ] **Step 4: Run the full suite and checks, then try it in Swagger**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all pass. Then run `docker compose up --build -d --wait` and check the timezone loads inside the container:

```powershell
docker compose exec api python -c "from zoneinfo import ZoneInfo; print(ZoneInfo('Europe/London'))"
```

Expected: `Europe/London`. If it fails with `ZoneInfoNotFoundError`, add `tzdata` as a runtime dependency (`uv add tzdata`) and rebuild. Then open http://localhost:8000/docs, try `/api/availability` with `mot-test` and tomorrow's date, and check that slots come back.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "backend - public availability endpoint"
```

---

### Task 5: CI smoke check, README and pull request

**Files:**
- Modify: `.github/workflows/ci.yml`, `README.md`

**Interfaces:**
- Consumes: `GET /api/availability` (Task 4) and the seeded `mot-test`.
- Produces:
  - In the `compose` job, a step straight after the services check:
    `curl -fsS "http://localhost:8080/api/availability?services=mot-test&date=$(TZ=Europe/London date -d tomorrow +%F)" | grep -F '"slots":[{'`
  - In the README Quick start table, a row `| Availability example | http://localhost:8000/api/availability?services=mot-test&date=YYYY-MM-DD |`, plus one sentence saying the date must be today or within the next 60 days.

- [ ] **Step 1: Add the CI step and the README row**

- [ ] **Step 2: Validate the workflow locally**

Run: `uvx --from check-jsonschema check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/ci.yml`
Expected: `ok -- validation done`

- [ ] **Step 3: Check the whole stack from a clean state**

Run: `docker compose down -v`, then `docker compose up --build`.
Expected: http://localhost:8080 still shows the Milestone 2 page, and the README's example URL with tomorrow's date returns slots.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml README.md
git commit -m "ci - availability smoke check, readme example"
```

- [ ] **Step 5: Push and open a PR (ask the user before pushing)**

Run: `git push -u origin milestone3-availability`, then open a PR into `main` at https://github.com/Adxm1go7/car-repair/compare/main...milestone3-availability.
Expected: the `backend`, `frontend` and `compose` checks all pass. Then merge it.

---

## Milestone 3 definition of done

- [ ] Every edge case in the design doc's "Edge cases" section has a passing test (Tasks 1–4).
- [ ] The concurrency test shows exactly one winner every round, run after run (Task 3).
- [ ] `GET /api/availability` has integration tests against real PostgreSQL, and CI's smoke check passes on the PR (Tasks 4 and 5).
