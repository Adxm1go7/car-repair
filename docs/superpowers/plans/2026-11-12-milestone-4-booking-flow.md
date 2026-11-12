# Milestone 4: Booking Flow with Slot Hold — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A customer ticks instant services, picks a day and time, has it held while they enter their details, and confirms. Expired holds are released by a worker and on the spot. Flow 1 passes end to end in Playwright, without payment.

**Architecture:** A `bookings` row (status `held`) links to the Milestone 3 `reservations` row. One rule says what an expired hold is, and availability, hold creation, confirm and the worker all use it with an injected `now`. The routes in `app/api/holds.py` call a service module (`app/bookings/service.py`), which calls the repositories. The frontend gains `react-router` and three pages, and a new root `e2e/` package runs Playwright against Compose.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, pytest + Testcontainers. React 19 + TypeScript + Vite, Vitest + React Testing Library, react-router. Playwright (Chromium).

**Spec:** [docs/superpowers/specs/2026-11-12-milestone-4-booking-flow-design.md](../specs/2026-11-12-milestone-4-booking-flow-design.md). It builds on [docs/SPEC.md](../../SPEC.md) and the [Milestone 3 design](../specs/2026-11-11-milestone-3-availability-design.md). Read the design first: field rules, response shapes and messages are defined there and are not repeated in full here.

## Global Constraints

- Work on branch `milestone4-booking-flow`; merge via PR. `main` needs the `backend`, `frontend` and `compose` CI checks.
- Commit messages are in the style `area - what` (for example `backend - bookings table`).
- Nothing reads the real clock except `app.clock.utc_now` and the worker's loop. Everything else takes `now`.
- Hold length comes from the `slot_hold_minutes` setting (1–1440, else 503). The booking window comes from `booking_window_days`. Neither is hardcoded in the backend or the frontend.
- Times in responses are garage-local ISO strings with an offset (`+00:00`, never `Z`), the same as `/api/availability`.
- Every 422 body is `{"detail": "<string>"}`.
- The hold token is stored only as a SHA-256 hex digest, compared with `hmac.compare_digest`, and never logged.
- New dependencies: `react-router` (frontend) and `@playwright/test` (e2e) only. No new backend dependency.
- Backend gates: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`. Frontend gates: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`.
- `playground/` is untracked and must not be touched or committed.

## Review Focus

1. **Expired-but-not-yet-released hold**: availability must show the slot and `POST /api/holds` must win it in the same request, before any worker run. Covered by `test_expired_hold_is_freed_on_the_spot` (Task 5).
2. **Confirm racing the sweep**: the booking ends up fully confirmed or fully expired, never confirmed with an inactive reservation. Covered by `test_confirm_and_sweep_never_mix` (Task 6).
3. **Double tap on "Confirm booking"**: the second call gives 200 with the same summary and no change. Covered by `test_repeat_confirm_is_idempotent` (Task 6) and the form disabling its button while submitting (Task 10).
4. **The garage's "today" just after midnight UTC during BST**: the day strip starts on the garage's date, not the browser's. Covered by `bookableDays` tests (Task 9).
5. **The phone clock is wrong**: the countdown uses `expires_in_seconds`, not `expires_at` minus `Date.now()`. Covered by the countdown test with a skewed system time (Task 10).

---

### Task 1: Milestone 3 leftovers — duplicate ids and one 422 shape

**Files:**
- Modify: `backend/app/repositories/reservations.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_reserve.py`, `backend/tests/integration/test_validation_errors.py` (new)

**Interfaces:**
- Produces: `reserve()` raises `ValueError("Duplicate service")` when `service_ids` has repeats. A `RequestValidationError` handler is registered in `create_app`.

- [ ] **Step 1: Write the failing tests**

```python
# test_reserve.py
def test_duplicate_service_ids_are_rejected(db_session: Session) -> None:
    seed(db_session)
    mot = service_id(db_session, "mot-test")
    with pytest.raises(ValueError, match="Duplicate service"):
        reserve(db_session, [mot, mot], local(8), NOW)

# test_validation_errors.py
def test_schema_errors_have_a_string_detail(client: TestClient) -> None:
    response = client.get("/api/availability", params={"services": "mot-test", "date": "nope"})
    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], str)
    assert body["detail"].startswith("date: ")
```

(Use the existing helpers in `test_reserve.py`, or add a `service_id(session, slug)` helper if it doesn't exist. `client` is the seeded fixture pattern from `test_availability_api.py`.)

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/integration/test_reserve.py tests/integration/test_validation_errors.py -v`
Expected: both FAIL. The first because no error is raised, the second because `detail` is a list.

- [ ] **Step 3: Implement**

In `reserve()`, compare `len(set(service_ids))` with `len(service_ids)` before the existing check. In `create_app`, add a handler for `fastapi.exceptions.RequestValidationError` that returns `JSONResponse(status_code=422, content={"detail": message})`. Build `message` from the **first** error as `f"{field}: {msg}"`. `field` is the last element of `loc` that is a string and not `"body"`, `"query"` or `"path"`, falling back to `"request"`. `msg` has a leading `"Value error, "` removed, which is how Pydantic prefixes errors raised from validators.

- [ ] **Step 4: Run the whole backend suite**

Run: `uv run pytest -v`
Expected: PASS. No existing test checks the list shape, which was confirmed while planning.

- [ ] **Step 5: Commit**

```powershell
git add backend/app backend/tests
git commit -m "backend fixes - reject duplicate services, one 422 shape"
```

---

### Task 2: Bookings tables

**Files:**
- Create: `backend/app/models/booking.py`, `backend/migrations/versions/0004_create_bookings.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/integration/test_booking_constraints.py` (new), `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Produces: `Booking` and `BookingItem` models. Booking columns are exactly as in the design's "Data model". The names are `reference`, `reservation_id`, `status`, `start_at`, `end_at`, `hold_expires_at`, `hold_token_hash`, `customer_name`, `customer_phone`, `customer_email`, `car_registration`, `car_make`, `car_model`, `notes`, `created_at` and `confirmed_at`. Relationships are `Booking.reservation: Reservation` and `Booking.items: list[BookingItem]`, ordered by `position` with `cascade="all, delete-orphan"`. `BookingItem` has `booking_id`, `service_id`, `service_name`, `price_from_pence`, `price_to_pence`, `duration_minutes` and `position`. Also produces `BOOKING_STATUSES: Final[tuple[str, ...]]`, the eight statuses in the design's order.

- [ ] **Step 1: Write the failing constraint tests** (each inserts with `db_session`, flushes, and expects `IntegrityError`, except the first)

- `test_held_booking_can_be_stored`: a held row with a reservation, an expiry and a token hash flushes.
- `test_held_booking_needs_expiry_and_token_hash`: parametrise which of the two is `None`. IntegrityError.
- `test_confirmed_booking_needs_customer_details`: a confirmed row with `customer_email=None` gives IntegrityError.
- `test_unknown_status_is_rejected`: `status="maybe"` gives IntegrityError.
- `test_start_must_be_before_end`
- `test_one_booking_per_reservation`: two bookings on one reservation give IntegrityError.
- `test_reference_is_unique`
- `test_item_positions_are_unique_per_booking`

In `test_migrations.py`, extend the existing upgrade/downgrade test so that `bookings` and `booking_items` exist at head and are gone after downgrading to `0003`.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/integration/test_booking_constraints.py -v`
Expected: FAIL with an ImportError (no `Booking`).

- [ ] **Step 3: Implement the models and migration `0004`** (revision `"0004"`, down revision `"0003"`, the same style as `0003`)

Use these constraint names, with the naming convention adding the `ck_bookings_` prefix: `status_valid`, `start_before_end`, `held_has_expiry`, `held_has_token`, `confirmed_has_details`. Add an index `ix_bookings_status_hold_expires_at` on `(status, hold_expires_at)`. `booking_items` gets a unique constraint on `(booking_id, position)`, `duration_minutes > 0`, and the same two price checks as `services`. The downgrade drops `booking_items` and then `bookings`.

- [ ] **Step 4: Run them and see them pass**

Run: `uv run pytest tests/integration/test_booking_constraints.py tests/integration/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/models backend/migrations backend/tests
git commit -m "backend - bookings and booking items tables"
```

---

### Task 3: Field rules, references and tokens

**Files:**
- Create: `backend/app/bookings/__init__.py`, `backend/app/bookings/rules.py`
- Test: `backend/tests/unit/test_booking_rules.py` (new)

**Interfaces:**
- Produces (all in `app/bookings/rules.py`):
  - `REFERENCE_ALPHABET: Final = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"`
  - `new_reference() -> str`: `"XXXX-XXXX"`, using `secrets.choice`.
  - `new_hold_token() -> str`: `secrets.token_urlsafe(32)`.
  - `hash_token(token: str) -> str`: SHA-256 hex.
  - `token_matches(token: str, stored_hash: str | None) -> bool`: constant-time, and False when `stored_hash` is None.
  - `clean_name(v: str) -> str`, `clean_phone(v: str) -> str`, `clean_email(v: str) -> str`, `clean_registration(v: str) -> str`, `clean_make_or_model(v: str) -> str` and `clean_notes(v: str | None) -> str | None`. Each one trims first, applies the design's rule, and raises `ValueError` with a customer-readable message.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("value", ["A", "x" * 100])
def test_name_lengths_accepted(value: str) -> None: assert clean_name(f"  {value} ") == value

@pytest.mark.parametrize("value", ["", "   ", "x" * 101])
def test_name_lengths_rejected(value: str) -> None:
    with pytest.raises(ValueError): clean_name(value)

@pytest.mark.parametrize("value", ["07700 900123", "+44 (0)7700-900123", "1234567"])
def test_phone_accepted(value: str) -> None: assert clean_phone(value) == value

@pytest.mark.parametrize("value", ["123456", "07700 90012x", "1" * 21, "+++ ++++ +++"])
def test_phone_rejected(value: str) -> None: ...

def test_email_is_lower_cased() -> None: assert clean_email(" Sam@Example.COM ") == "sam@example.com"

@pytest.mark.parametrize("value", ["sam", "sam@example", "a@@b.com", "s am@example.com", "a@" + "b" * 250 + ".com"])
def test_email_rejected(value: str) -> None: ...

def test_registration_normalised() -> None: assert clean_registration(" ab12 cde ") == "AB12CDE"

@pytest.mark.parametrize("value", ["A", "ABCDEFGH9", "AB-12"])
def test_registration_rejected(value: str) -> None: ...

def test_make_or_model_limits() -> None: ...  # "" and 51 chars rejected, 50 accepted

def test_empty_notes_become_none() -> None:
    assert clean_notes("  ") is None
    assert clean_notes(None) is None

def test_notes_over_1000_rejected() -> None: ...

def test_reference_shape() -> None:
    ref = new_reference()
    assert len(ref) == 9 and ref[4] == "-"
    assert set(ref.replace("-", "")) <= set(REFERENCE_ALPHABET)

def test_token_matches_only_its_hash() -> None:
    token = new_hold_token()
    assert token_matches(token, hash_token(token))
    assert not token_matches(token + "x", hash_token(token))
    assert not token_matches(token, None)
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/unit/test_booking_rules.py -v`
Expected: FAIL with an ImportError.

- [ ] **Step 3: Implement `rules.py`** as listed under Interfaces.

- [ ] **Step 4: Run them and see them pass**

Run: `uv run pytest tests/unit/test_booking_rules.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/bookings backend/tests/unit
git commit -m "backend - booking field rules, references, hold tokens"
```

---

### Task 4: The expired-hold rule, release, and availability ignoring expired holds

**Files:**
- Create: `backend/app/repositories/bookings.py`
- Modify: `backend/app/repositories/availability.py`
- Test: `backend/tests/integration/test_hold_expiry.py` (new), `backend/tests/unit/test_hold_expiry_rule.py` (new)

**Interfaces:**
- Consumes: `Booking`, `Reservation` (Task 2).
- Produces (in `app/repositories/bookings.py`):
  - `expired_hold(now: datetime) -> ColumnElement[bool]`, the SQL form: `Booking.status == "held"` and `Booking.hold_expires_at <= now`.
  - `hold_has_expired(booking: Booking, now: datetime) -> bool`, the same rule in Python. The two sit side by side with a comment that they must agree.
  - `release_hold(session: Session, booking: Booking) -> None`, which sets `status="expired"` and `booking.reservation.active=False`, then flushes.
  - `release_expired_holds(session: Session, now: datetime) -> int`. It runs one `UPDATE bookings … WHERE expired_hold(now) RETURNING reservation_id`, then one `UPDATE reservations SET active = false WHERE id IN (…)`, and returns the count. It doesn't commit.
  - `get_booking_for_update(session: Session, reference: str) -> Booking | None`, using `with_for_update()` and `populate_existing()`, with items and the reservation loaded.
  - `load_hold_minutes(session: Session) -> int`, in `app/repositories/availability.py`, using `_int_setting(session, "slot_hold_minutes", 1, 1440)`.
- Changes: `day_availability(...)` leaves out reservations for which a booking exists that matches `expired_hold(now)` (a `NOT EXISTS` on `bookings.reservation_id`). Its signature doesn't change.

Add a test helper `make_hold(session, start_utc, expires_at, *, bay_slug="mot-bay", status="held") -> Booking` in `backend/tests/factories.py` (new). It inserts a reservation (`kind="booking"`, the range `[start, start + 75 min)`) and a booking with `start_at`, `end_at = start + 60 min`, the reference from `new_reference()` and `hold_token_hash=hash_token("t")`. Tasks 5 and 6 reuse it.

- [ ] **Step 1: Write the failing tests**

```python
# unit: the boundary
def test_hold_expired_exactly_at_expiry() -> None:   # status held, now == hold_expires_at → True
def test_hold_not_expired_one_second_before() -> None:
def test_confirmed_booking_never_expired() -> None:  # even when hold_expires_at < now

# integration (db_session, seeded)
def test_release_expired_holds_releases_only_expired_held(db_session: Session) -> None:
    # Three bookings: held and expired, held and live, confirmed with a past hold_expires_at.
    # release_expired_holds(db_session, NOW) == 1
    # The first is now "expired" with an inactive reservation. The other two are untouched.

def test_availability_ignores_an_expired_hold_before_release(db_session: Session) -> None:
    # An expired hold on the MOT bay at 08:00 on DAY. day_availability for mot-test
    # with now=NOW offers 08:00, and the reservation is still active in the table.

def test_availability_respects_a_live_hold(db_session: Session) -> None:
    # The same, but expiring after NOW: 08:00 isn't offered.
```

The unit test may build an unsaved `Booking(...)` object without a session.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/unit/test_hold_expiry_rule.py tests/integration/test_hold_expiry.py -v`
Expected: FAIL with an ImportError.

- [ ] **Step 3: Implement** as listed under Interfaces.

- [ ] **Step 4: Run them, and the Milestone 3 tests, and see them pass**

Run: `uv run pytest tests/unit tests/integration/test_hold_expiry.py tests/integration/test_availability_api.py tests/integration/test_reserve.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app backend/tests
git commit -m "backend - expired hold rule, release, availability ignores expired holds"
```

---

### Task 5: Create a hold — `POST /api/holds` and `GET /api/booking-policy`

**Files:**
- Create: `backend/app/bookings/service.py`, `backend/app/api/validation.py`, `backend/app/api/holds.py`
- Modify: `backend/app/api/availability.py` (use the shared validation), `backend/app/api/catalogue.py` (booking-policy), `backend/app/main.py` (include the holds router)
- Test: `backend/tests/integration/test_holds_api.py` (new), `backend/tests/integration/test_hold_concurrency.py` (new), `backend/tests/integration/test_booking_policy_api.py` (new)

**Interfaces:**
- Consumes: `reserve`, `SlotUnavailable`, `ReserveResult` (Milestone 3), and `release_expired_holds`, `load_hold_minutes` (Task 4). Also `new_reference`, `new_hold_token`, `hash_token` (Task 3).
- Produces:
  - `app/api/validation.py`, holding the checks moved out of `availability.py` unchanged (same messages and limits): `resolve_services(session: Session, slugs: list[str]) -> list[Service]` and `check_bookable_date(day: date, now: datetime, zone: ZoneInfo, window_days: int) -> None`. Both raise `HTTPException(422)`. `availability.py` now calls them.
  - `app/bookings/service.py`:
    - `@dataclass(frozen=True) class HoldCreated: booking: Booking; token: str`
    - `create_hold(session: Session, services: Sequence[Service], start: datetime, now: datetime, hold_minutes: int) -> HoldCreated`. It calls `release_expired_holds(session, now)` and `reserve(session, [s.id for s in services], start, now)`. It inserts a `held` Booking (`hold_expires_at = now + hold_minutes`), with one `BookingItem` per service in the given order and snapshot values, then flushes. It raises `SlotUnavailable`. The caller commits.
    - `summary_services(booking: Booking) -> list[dict[str, object]]`, built from the item snapshots. (The route converts it into `ServiceSummaryOut`.)
  - `app/api/holds.py`: `router`, with `POST /holds` taking `HoldIn{services: list[str], start: AwareDatetime}` and returning `HoldOut` with status 201, in the design's exact shape. Also `local_iso(value: datetime, zone: ZoneInfo) -> str`, which Task 6 reuses.
  - `GET /api/booking-policy` returning `BookingPolicyOut{booking_window_days: int, slot_hold_minutes: int}`, with 503 on `SettingsUnavailable`.
- Route order in `POST /holds`: load the policy, window and hold minutes (503 on failure). Then `resolve_services`. Then reject needs-approval services (422, with the design's message). Then mixed bay types (422, with the design's message). Then `check_bookable_date(start.astimezone(zone).date(), …)`. Then `create_hold`. `SlotUnavailable` becomes 409 `"That time has just been taken"`. Commit, then return. `expires_in_seconds = hold_minutes * 60`.

- [ ] **Step 1: Write the failing tests** (seeded `client` fixture, `NOW = 2026-11-09 09:00Z`, `DAY = 2026-11-10`, MOT 08:00 local = `"2026-11-10T08:00:00+00:00"`)

```python
def test_hold_returns_201_with_the_design_shape(client) -> None:
    r = hold(client, ["mot-test"], "2026-11-10T08:00:00+00:00")
    assert r.status_code == 201
    body = r.json()
    assert body["start"] == "2026-11-10T08:00:00+00:00" and body["end"] == "2026-11-10T09:00:00+00:00"
    assert body["expires_at"] == "2026-11-09T09:10:00+00:00" and body["expires_in_seconds"] == 600
    assert body["services"] == [{"slug": "mot-test", "name": "MOT test", "duration_minutes": 60,
                                 "price_from_pence": 5485, "price_to_pence": None}]
    assert len(body["hold_token"]) >= 40 and len(body["reference"]) == 9

def test_hold_stores_snapshots_and_hashes_the_token(client, db_session) -> None:
    # The booking is "held", hold_token_hash == hash_token(token) != token, the items are in order,
    # and its reservation is active.

def test_hold_takes_the_slot_out_of_availability(client) -> None:
def test_taken_slot_gives_409(client) -> None:              # second hold for the same MOT start
def test_off_grid_start_gives_409(client) -> None:          # "2026-11-10T08:10:00+00:00"
def test_mixed_bay_types_gives_422(client) -> None:         # ["mot-test", "full-service"]
def test_needs_approval_service_gives_422(client) -> None:  # ["diagnostic-check"]
def test_start_without_offset_gives_422(client) -> None:    # "2026-11-10T08:00:00"
@pytest.mark.parametrize(...)  # the same service cases as availability: empty, unknown, duplicate, 21 services
def test_service_validation_matches_availability(client, services) -> None:
def test_past_and_beyond_window_dates_give_422(client) -> None:
def test_broken_hold_setting_gives_503(client, db_session) -> None:  # slot_hold_minutes = 0

def test_expired_hold_is_freed_on_the_spot(client, db_session) -> None:
    first = hold(client, ["mot-test"], MOT_0800)
    set_now(client, NOW + timedelta(minutes=10, seconds=1))
    assert MOT_0800_LOCAL in starts(get_availability(client, "mot-test"))
    assert hold(client, ["mot-test"], MOT_0800).status_code == 201
    # The first booking is "expired" and its reservation is inactive.

# test_booking_policy_api.py
def test_policy_shape(client) -> None:  # {"booking_window_days": 60, "slot_hold_minutes": 10}
def test_policy_503_when_setting_broken(client, db_session) -> None:
```

`test_hold_concurrency.py` follows `test_reserve_concurrency.py`: a fresh database, migrated and seeded and committed. Two threads, each with its own `Session(engine)`, wait on a `Barrier(2)`, then call `create_hold(session, [mot], start, NOW, 10)` and commit. Run the same five `STARTS` rounds. Assert outcomes are `{"won", "lost"}` in every round, and that each start has exactly one `held` booking.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/integration/test_holds_api.py tests/integration/test_hold_concurrency.py tests/integration/test_booking_policy_api.py -v`
Expected: FAIL (404s and ImportErrors).

- [ ] **Step 3: Implement** the validation move, `create_hold`, the routes and booking-policy, as listed under Interfaces.

- [ ] **Step 4: Run the whole backend suite**

Run: `uv run pytest -v`
Expected: PASS, including the unchanged availability tests.

- [ ] **Step 5: Commit**

```powershell
git add backend/app backend/tests
git commit -m "backend - create hold endpoint, booking policy endpoint"
```

---

### Task 6: Confirm and release a hold

**Files:**
- Modify: `backend/app/bookings/service.py`, `backend/app/api/holds.py`
- Test: `backend/tests/integration/test_confirm_hold_api.py` (new), `backend/tests/integration/test_confirm_sweep_race.py` (new)

**Interfaces:**
- Consumes: `get_booking_for_update`, `hold_has_expired`, `release_hold` (Task 4), `token_matches` and the `clean_*` functions (Task 3), and `local_iso` (Task 5).
- Produces, in `service.py`:
  - Exceptions `HoldNotFound`, `HoldExpired` and `AlreadyConfirmed`.
  - `@dataclass(frozen=True) class CustomerDetails`, with fields `name`, `phone`, `email`, `registration`, `make`, `model`, and `notes: str | None`.
  - `confirm_hold(session: Session, reference: str, token: str, details: CustomerDetails, now: datetime) -> Booking`. It locks the booking. If the booking is missing or the token is wrong, it raises `HoldNotFound`. If it's `confirmed`, it returns the booking unchanged. If it's `held` and `hold_has_expired`, it calls `release_hold` and raises `HoldExpired`. If it's `expired`, it raises `HoldExpired`. Otherwise it sets the details, `status="confirmed"` and `confirmed_at=now`, then flushes.
  - `cancel_hold(session: Session, reference: str, token: str) -> None`. A missing booking or wrong token raises `HoldNotFound`. `held` calls `release_hold`. `expired` does nothing. Any other status raises `AlreadyConfirmed`.
- Routes in `holds.py`:
  - `POST /holds/{reference}/confirm` takes `ConfirmIn` (`hold_token: str` plus the fields as `Annotated[str, AfterValidator(clean_…)]`, and `notes: … = None`), and returns `BookingSummaryOut` in the design's shape.
  - `DELETE /holds/{reference}` takes `CancelIn{hold_token: str}` and returns 204.
  - `HoldNotFound` → 404 `"Booking not found"`. `HoldExpired` → **commit first**, so the release persists, then 410 `"Your hold has expired"`. `AlreadyConfirmed` → 409 `"This booking is already confirmed"`.
  - `reference` longer than 9 characters or containing NUL → 404, without querying.

- [ ] **Step 1: Write the failing tests**

```python
def test_confirm_stores_normalised_details(client, db_session) -> None:
    created = hold(client, ["mot-test"], MOT_0800).json()
    r = confirm(client, created, registration="ab12 cde", email="Sam@Example.com")
    assert r.status_code == 200
    body = r.json()
    assert (body["reference"], body["status"], body["registration"], body["start"]) == (
        created["reference"], "confirmed", "AB12CDE", MOT_0800)
    # In the database: confirmed, customer_email == "sam@example.com", reservation active, confirmed_at == NOW.

def test_repeat_confirm_is_idempotent(client, db_session) -> None:  # second call: 200, same body, confirmed_at unchanged
def test_wrong_token_gives_404(client) -> None:
def test_unknown_reference_gives_404(client) -> None:              # same body as the wrong token
def test_late_confirm_gives_410_and_releases(client, db_session) -> None:
    # set_now to NOW + 10 min; 410; the booking is "expired" and the reservation inactive (re-query after the response)
@pytest.mark.parametrize("field,value", [("name", ""), ("phone", "123"), ("email", "sam"),
                                         ("registration", "A"), ("make", ""), ("model", "x" * 51),
                                         ("notes", "x" * 1001)])
def test_field_rules_give_422_naming_the_field(client, field, value) -> None:
    assert r.status_code == 422 and r.json()["detail"].startswith(f"{field}: ")

def test_delete_releases_the_hold(client, db_session) -> None:        # 204; the slot is back in availability
def test_delete_is_idempotent(client) -> None:                        # a second delete gives 204
def test_delete_with_wrong_token_gives_404(client) -> None:
def test_delete_confirmed_gives_409_and_changes_nothing(client, db_session) -> None:
```

`test_confirm_sweep_race.py` uses a fresh database, seeded and committed. Use `make_hold` from `tests/factories.py` with `hold_expires_at = T` and commit. In each of 10 rounds, one thread calls `confirm_hold(..., now=T - 1s)` and the other calls `release_expired_holds(session, now=T)`, behind a `Barrier(2)`, each on its own session, each committing. Then re-read the booking and its reservation. Assert that either the status is `confirmed` and `active` is True, or the status is `expired` and `active` is False. Name it `test_confirm_and_sweep_never_mix`.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/integration/test_confirm_hold_api.py tests/integration/test_confirm_sweep_race.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement** as listed under Interfaces.

- [ ] **Step 4: Run the whole backend suite**

Run: `uv run pytest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app backend/tests
git commit -m "backend - confirm and release hold endpoints"
```

---

### Task 7: The worker

**Files:**
- Create: `backend/app/worker.py`
- Modify: `backend/app/config.py`, `docker-compose.yml`, `.env.example`
- Test: `backend/tests/integration/test_worker.py` (new), `backend/tests/unit/test_config.py`

**Interfaces:**
- Consumes: `release_expired_holds` (Task 4).
- Produces:
  - `AppConfig.worker_interval_seconds: int = 60`, read from the `WORKER_INTERVAL_SECONDS` environment variable. It must be at least 1, using `Field(ge=1)`.
  - `run_once(session: Session, now: datetime) -> int`, which releases, commits and returns the count.
  - `main() -> None`, which builds the engine and installs SIGTERM and SIGINT handlers that set a `threading.Event`. It loops: open a session, call `run_once(session, utc_now())`, log `"released %d expired holds"` when the count is above 0, then `event.wait(interval)`. It disposes of the engine on exit. Exceptions inside one cycle are logged with `logging.exception` and the loop carries on.
  - The Compose service `worker`: `build: ./backend`, `command: ["python", "-m", "app.worker"]`, the same `DATABASE_URL` and `ENVIRONMENT` as `api`, and `depends_on: api: condition: service_healthy`, so migrations have run.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_once_releases_and_commits(fresh_database_url) -> None:
    # Migrate and seed. Create one expired and one live hold with make_hold and commit.
    # With a new Session: run_once(session, NOW) == 1. With another new Session, the expired one
    # reads "expired" (proving it was committed) and the live one reads "held".

def test_run_once_with_nothing_to_do_returns_zero(fresh_database_url) -> None:

# test_config.py
def test_worker_interval_defaults_to_60(monkeypatch) -> None:
def test_worker_interval_below_1_is_rejected(monkeypatch) -> None:
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/integration/test_worker.py tests/unit/test_config.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement** `worker.py`, the config field, the Compose service, and a commented `WORKER_INTERVAL_SECONDS=60` in `.env.example`.

- [ ] **Step 4: Verify**

Run: `uv run pytest -v`, then `docker compose up --build -d --wait`, then `docker compose ps worker`.
Expected: the tests PASS and the worker is `running`. `docker compose logs worker` shows no traceback.

- [ ] **Step 5: Commit**

```powershell
git add backend docker-compose.yml .env.example
git commit -m "backend - worker releases expired holds"
```

---

### Task 8: Frontend routing, booking API client, and service selection

**Files:**
- Modify: `frontend/package.json` (add `react-router`), `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/App.test.tsx`, `frontend/src/App.css`
- Create: `frontend/src/booking/types.ts`, `frontend/src/booking/api.ts`, `frontend/src/booking/selection.ts`, `frontend/src/booking/selection.test.ts`

**Interfaces:**
- Produces:
  - `types.ts`: `BookingPolicy`, `AvailabilitySlot{start, end}`, `Availability`, `ServiceSummary`, `Hold`, `BookingSummary` and `CustomerDetails`. They mirror the design's JSON field for field.
  - `api.ts`, where every function never throws and returns a discriminated union:
    - `fetchBookingPolicy(): Promise<Result<BookingPolicy>>`
    - `fetchAvailability(services: string[], date: string): Promise<Result<Availability>>`
    - `createHold(services: string[], start: string): Promise<Result<Hold> | { ok: false; kind: 'taken' }>`
    - `confirmHold(reference: string, token: string, details: CustomerDetails): Promise<Result<BookingSummary> | { ok: false; kind: 'expired' }>`
    - `cancelHold(reference: string, token: string): Promise<void>`

    Here `Result<T> = { ok: true; data: T } | { ok: false; kind: 'error'; detail: string | null }`. A 409 maps to `taken`, and a 410 maps to `expired`.
  - `selection.ts`: `parseSelection(search: string): string[]`, which reads the repeated `services` parameters, de-duplicated with order kept. `selectionQuery(slugs: string[]): string`, which gives `"?services=a&services=b"`. `totalMinutes(services: Service[], slugs: string[]): number`.
  - `App` becomes the router shell. It renders `<Routes>`, with `/` showing the services page (the existing catalogue page, still taking `now`), `/book` showing `BookPage` (Task 9) and `/booked/:reference` showing `BookedPage` (Task 10). `main.tsx` wraps it in `<BrowserRouter>`. Tests render with `<MemoryRouter initialEntries={…}>`.
  - Each instant `ServiceCard` gets `<input type="checkbox">`, labelled by the service name. Needs-approval cards get no checkbox and the text "Needs approval — call us". When at least one service is ticked, a sticky bar shows `Choose a time · {n} service(s) · {formatDuration(total)}` as a link to `/book` + `selectionQuery`. On `/`, the boxes start ticked from `parseSelection(location.search)`.

- [ ] **Step 1: Install the dependency**

Run (in `frontend/`): `npm install react-router`
Expected: `package.json` and `package-lock.json` gain `react-router`.

- [ ] **Step 2: Write the failing tests**

```ts
// selection.test.ts
it('parses repeated services and drops duplicates', () =>
  expect(parseSelection('?services=a&services=b&services=a')).toEqual(['a', 'b']))
it('builds the query back', () => expect(selectionQuery(['a', 'b'])).toBe('?services=a&services=b'))
it('sums durations of the chosen services', () => ...)

// App.test.tsx (existing tests still pass, rendered inside MemoryRouter)
it('ticking services shows the bar with count and total time', async () => {
  // Tick MOT test (60) and Full service (180): the bar link reads "Choose a time · 2 services · 4h"
  // and its href is "/book?services=mot-test&services=full-service".
})
it('needs-approval services have no tick box', () => {
  // within(cardFor('Clutch replacement')).queryByRole('checkbox') is null, and the text "Needs approval — call us" is present.
})
it('pre-ticks services from the URL', () => { /* initialEntries ['/?services=mot-test'] */ })
```

- [ ] **Step 3: Run them and see them fail**

Run: `npm test`
Expected: the new tests FAIL.

- [ ] **Step 4: Implement** as listed under Interfaces. Add a `bookingApi.test.ts`, or extend the tests above, so that one test checks `createHold` maps a 409 to `{ ok: false, kind: 'taken' }`.

- [ ] **Step 5: Run all frontend gates**

Run: `npm run lint; npm run typecheck; npm test; npm run build`
Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add frontend
git commit -m "frontend - routing, booking api client, service selection"
```

---

### Task 9: Time picker

**Files:**
- Create: `frontend/src/booking/days.ts`, `frontend/src/booking/days.test.ts`, `frontend/src/booking/BookPage.tsx`, `frontend/src/booking/TimePicker.tsx`, `frontend/src/booking/BookPage.test.tsx`, `frontend/src/booking/format.ts`

**Interfaces:**
- Consumes: `api.ts` and `selection.ts` (Task 8), and `fetchCatalogue` (Milestone 2).
- Produces:
  - `todayInZone(now: Date, zone: string): string`, giving `"YYYY-MM-DD"` (via `Intl.DateTimeFormat('en-CA', { timeZone })`).
  - `bookableDays(today: string, windowDays: number, hours: OpeningDay[]): BookableDay[]`, where `BookableDay = { date: string; weekday: number; open: boolean }`. It covers `today` up to and including `today + windowDays`, using calendar-date arithmetic (UTC-noon `Date`s) so clock changes can't skip or repeat a day.
  - `formatTime(iso: string, zone: string): string`, giving `"08:30"`, and `formatDayLabel(date: string): { weekday: string; day: string }`.
  - `BookPage({ now }: { now: () => Date })`. It reads the selection from the URL and loads the catalogue and the policy. With no valid selection, it redirects to `/`. It holds the step state `{ kind: 'picking' } | { kind: 'details'; hold: Hold }` and renders `TimePicker` or `DetailsForm` (Task 10). Until Task 10 lands, the details step renders a placeholder with the held time.
  - `TimePicker({ services, days, zone, onHeld })`. The day strip uses buttons, with closed days `disabled`, and the first open day is selected on arrival. Picking a day calls `fetchAvailability`. Slots are grouped as "Morning" (local start before 12:00) and "Afternoon", each button showing `08:30 – 13:00`. `unavailable_reason === 'mixed_bay_types'` shows "These services can't be booked together — please book them separately" with a link back to `/` + `selectionQuery`. No slots shows "No times left on this day". Tapping a slot calls `createHold`. On success it calls `onHeld(hold)`. On `taken` it reloads the day and shows "Sorry, someone just took that time."

- [ ] **Step 1: Write the failing tests**

```ts
// days.test.ts
it('uses the garage date just after midnight UTC in BST', () =>
  expect(todayInZone(new Date('2026-06-30T23:30:00Z'), 'Europe/London')).toBe('2026-07-01'))
it('covers today through the last window day', () => {
  const days = bookableDays('2026-11-10', 60, HOURS)
  expect(days[0].date).toBe('2026-11-10'); expect(days).toHaveLength(61); expect(days.at(-1)!.date).toBe('2027-01-09')
})
it('marks closed weekdays', () => { /* hours with Sunday closed: Sunday entries have open false */ })
it('steps over the October clock change without repeating a day', () => {
  expect(bookableDays('2026-10-24', 2, HOURS).map((d) => d.date)).toEqual(['2026-10-24', '2026-10-25', '2026-10-26'])
})

// BookPage.test.tsx (stub fetch by URL as App.test.tsx does)
it('starts on the first open day and lists its times in garage time', async () => { /* "08:00 – 09:00" under "Morning" */ })
it('disables closed days', async () => {})
it('tells the customer to book mixed bay types separately', async () => {})
it('shows "just taken" and reloads after a 409', async () => { /* the availability fetch is called twice */ })
it('moves to the details step after a successful hold', async () => {})
it('redirects to the services page with no services', async () => {})
```

- [ ] **Step 2: Run them and see them fail**

Run: `npm test`
Expected: the new tests FAIL.

- [ ] **Step 3: Implement** as listed under Interfaces, and add the `/book` route to `App`.

- [ ] **Step 4: Run all frontend gates**

Run: `npm run lint; npm run typecheck; npm test; npm run build`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add frontend
git commit -m "frontend - time picker with day strip and slot hold"
```

---

### Task 10: Details form, countdown, and booked page

**Files:**
- Create: `frontend/src/booking/DetailsForm.tsx`, `frontend/src/booking/DetailsForm.test.tsx`, `frontend/src/booking/useCountdown.ts`, `frontend/src/booking/validation.ts`, `frontend/src/booking/validation.test.ts`, `frontend/src/booking/BookedPage.tsx`, `frontend/src/booking/BookedPage.test.tsx`
- Modify: `frontend/src/booking/BookPage.tsx`, `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `confirmHold` and `cancelHold` (Task 8), and `BookPage`'s step state (Task 9).
- Produces:
  - `validateDetails(values: CustomerDetails): Partial<Record<keyof CustomerDetails, string>>`. These are the design's field rules, mirrored from the backend `clean_*` functions. Empty means valid.
  - `useCountdown(seconds: number, onExpire: () => void): number`. It counts whole seconds remaining from `seconds`, using `setInterval` and elapsed `performance.now()`, never `Date.now()` compared with `expires_at`.
  - `DetailsForm({ hold, zone, initial, onExpired, onChangeTime, onBooked })`:
    - The banner reads "We're holding {day}, {time} for m:ss". Its `aria-live="polite"` region only announces at 5:00, 1:00 and expiry.
    - The six fields and notes each have a `<label>`, and their errors use `aria-describedby`.
    - "Confirm booking" is disabled while submitting.
    - "Change time" calls `cancelHold`, then `onChangeTime`.
    - On `expired` from the server, or the countdown reaching 0, it calls `onExpired(currentValues)`.
    - On success it calls `onBooked(summary)`.
  - `BookPage`: `onExpired` returns to picking with the notice "Your hold ran out, so we released that time." and keeps the typed values for the next `DetailsForm` (as `initial`). `onBooked` calls `navigate('/booked/' + reference, { state: summary })`.
  - `BookedPage`: with a summary in `location.state`, it shows "You're booked", the local day and time range, the service names, `registration · make model`, the reference and the garage phone. Without state, it shows "Your booking reference is {reference}. Call us on {phone} if you need to change it."

- [ ] **Step 1: Write the failing tests**

```ts
// validation.test.ts — one accept and one reject case per rule, the same boundaries as Task 3
// DetailsForm.test.tsx (vi.useFakeTimers())
it('counts down from expires_in_seconds even when the phone clock is wrong', () => {
  vi.setSystemTime(new Date('2030-01-01T00:00:00Z'))  // far from expires_at
  // render with expires_in_seconds 600: shows "10:00"; advance 61s: shows "8:59"
})
it('returns to the picker when the countdown reaches zero, keeping typed values', () => {})
it('shows field errors and does not call the API when invalid', async () => {})
it('disables the confirm button while submitting', async () => {})
it('a 410 from confirm calls onExpired', async () => {})
it('change time releases the hold', async () => { /* a DELETE fetch is made, then onChangeTime */ })
// BookedPage.test.tsx
it('shows the summary from navigation state', () => {})
it('shows the reference and phone when opened directly', () => {})
```

- [ ] **Step 2: Run them and see them fail**

Run: `npm test`
Expected: the new tests FAIL.

- [ ] **Step 3: Implement** as listed under Interfaces, and add the `/booked/:reference` route.

- [ ] **Step 4: Run all frontend gates, then try it by hand**

Run: `npm run lint; npm run typecheck; npm test; npm run build`, then `docker compose up --build -d --wait` and book something at `http://localhost:8080`.
Expected: the gates pass. The booking reaches "You're booked", and the same time is no longer offered.

- [ ] **Step 5: Commit**

```powershell
git add frontend
git commit -m "frontend - details form, countdown, booked page"
```

---

### Task 11: End-to-end test, CI and README

**Files:**
- Create: `e2e/package.json`, `e2e/package-lock.json`, `e2e/playwright.config.ts`, `e2e/tsconfig.json`, `e2e/tests/instant-booking.spec.ts`, `e2e/.gitignore` (`node_modules/`, `test-results/`, `playwright-report/`)
- Modify: `.github/workflows/ci.yml` (the `compose` job), `README.md`

**Interfaces:**
- Consumes: the whole running stack.
- Produces: `npm test` in `e2e/` runs `playwright test`. The config uses `baseURL: process.env.BASE_URL ?? 'http://localhost:8080'`, one `chromium` project, `retries: process.env.CI ? 1 : 0`, `trace: 'retain-on-failure'`.

- [ ] **Step 1: Set up the package**

Run (in `e2e/`): `npm init -y`, then `npm install --save-dev @playwright/test`, then `npx playwright install chromium`.
Expected: `package.json` lists `@playwright/test`. Set `"private": true` and `"scripts": {"test": "playwright test"}`.

- [ ] **Step 2: Write the test `flow 1: instant booking without payment`**

Book **"MOT test"**, because the MOT bay is the only bay of its type, so a booked start must disappear from availability. The steps: go to `/` and tick "MOT test". Click the "Choose a time" link. Today may have no times left after the cut-off, so click enabled days in order until a slot button appears, then click the first slot. Read the day from the day strip's selected button, and the start from the slot's text. Fill Name, Phone, Email, Registration, Make and Model by label, and click "Confirm booking". Expect the heading "You're booked" and text matching `/[A-Z2-9]{4}-[A-Z2-9]{4}/`. Then call `request.get('/api/availability?services=mot-test&date=<day>')` and assert that no slot's `start.slice(11, 16)` equals the booked start.

- [ ] **Step 3: Run it locally against Compose**

Run: `docker compose up --build -d --wait`, then `npm test` in `e2e/`.
Expected: `1 passed`.

- [ ] **Step 4: Add it to CI**

In the `compose` job, after the smoke checks and before `docker compose logs`, add these steps. `actions/setup-node@v5` with Node 22, caching on `e2e/package-lock.json`. `npm ci` in `e2e`. `npx playwright install --with-deps chromium`. `npm test` in `e2e`. Then, `if: failure()`, `actions/upload-artifact@v4` with `e2e/playwright-report` and `e2e/test-results`. Also add a smoke check that `docker compose ps worker --format '{{.State}}'` prints `running`.

- [ ] **Step 5: Update the README**

Add the booking flow to Quick start (`http://localhost:8080`, tick a service, choose a time), the worker to the list of services, and "Run the end-to-end test" (`cd e2e; npm ci; npx playwright install chromium; npm test`, with Compose running).

- [ ] **Step 6: Commit, push and watch CI**

```powershell
git add e2e .github/workflows/ci.yml README.md
git commit -m "ci - playwright end-to-end test for instant booking, readme"
git push -u origin milestone4-booking-flow
gh pr create --fill --base main
gh pr checks --watch
```

Expected: `backend`, `frontend` and `compose` are all green.
