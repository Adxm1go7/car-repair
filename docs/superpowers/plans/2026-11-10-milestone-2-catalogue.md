# Milestone 2: Services and the Public Catalogue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The database holds the garage's bay types, bays, services and opening hours. The seed command loads a fictional demo garage into them, three public read-only endpoints expose them, and the page at `/` shows them as service cards with an "Open today" strip, the weekly hours and contact details.

**Architecture:** One new model module, `app/models/catalogue.py`, plus migration `0002`. Read queries live in `app/repositories/catalogue.py`. Routes and their Pydantic response models live in `app/api/catalogue.py` and get a database session through a new `get_session` dependency, which tests override with the rolled-back `db_session`. Demo data lives in `app/demo_data.py` and the existing `seed()` inserts it, never overwriting. On the frontend, pure helpers in `src/catalogue/` (fetching, formatting, "Open today") are unit-tested on their own, and `App` renders them. There's no router and no UI library.

**Tech Stack:** As in Milestone 1. No new dependencies.

**Spec:** [docs/superpowers/specs/2026-11-10-milestone-2-catalogue-design.md](../specs/2026-11-10-milestone-2-catalogue-design.md), which builds on [docs/SPEC.md](../../SPEC.md). Read the design doc first; it holds the demo data and the reasons behind each choice.

## Global Constraints

- Everything from the Milestone 1 plan's Global Constraints still applies (free tools only, no secrets, UTC timestamps, LF endings, the same versions).
- Catalogue values are never hardcoded in app logic or the page. They come from the database. Demo values exist only in `app/demo_data.py`.
- The seed inserts what's missing and never overwrites or re-creates anything that exists or was deliberately removed.
- Rows are deactivated (`active = false`), never deleted, for services and bays.
- Money is integer pence everywhere: `price_from_pence`, `price_to_pence`. It's formatted as pounds only in the page.
- Opening and break times are local wall-clock `time` values. The garage timezone is the setting `garage_timezone` = `"Europe/London"`. The page works out "today" in that zone, never the browser's.
- No router, no UI library, plain CSS. The page is phone-first.
- `main` is protected: all work goes on the branch `milestone2-catalogue` and merges through a PR.

## Review Focus

1. **The seed brings back something an admin removed.** If an admin deletes Monday's lunch break or deactivates a service, a container restart re-runs the seed, and the change must survive. Pinned in Task 2.
2. **A weekday row missing from `opening_hours`.** `GET /api/opening-hours` must still return 7 entries, with the missing day shown as closed, not a 500 or a 6-item list. Pinned in Task 3.
3. **A visitor whose browser is in another timezone, and summer time.** "Open today" must follow the garage's zone, including BST, never the device clock's zone. Pinned in Task 4.
4. **Broken or missing garage settings.** `GET /api/garage` returns 503 with JSON, and the page shows its error state instead of crashing. Pinned in Task 3 and Task 5.
5. **Awkward prices.** Pence that aren't whole pounds (£54.85), and a range where "to" equals "from", must display correctly. Pinned in Task 4.

---

## File Structure

```
.gitignore                                 # + .superpowers/
.github/workflows/ci.yml                   # compose job also checks /api/services
README.md                                  # + "Changing the demo data"
backend/
  migrations/versions/0002_create_catalogue.py
  app/
    db.py                                  # + get_session dependency
    main.py                                # + include catalogue router
    demo_data.py                           # NEW: fictional garage values only
    seed.py                                # seeds settings + catalogue
    models/__init__.py                     # + re-export catalogue models
    models/catalogue.py                    # NEW: BayType, Bay, Service, OpeningHours, OpeningHoursBreak
    repositories/__init__.py               # NEW
    repositories/catalogue.py              # NEW: read queries
    api/catalogue.py                       # NEW: 3 routes + response models
  tests/
    conftest.py                            # + api_client fixture
    integration/test_migrations.py         # + catalogue tables
    integration/test_catalogue_constraints.py   # NEW
    integration/test_seed.py               # + catalogue seeding
    integration/test_catalogue_api.py      # NEW
frontend/src/
  App.tsx                                  # catalogue page replaces status page
  App.test.tsx                             # rewritten
  App.css                                  # NEW
  catalogue/types.ts                       # NEW: API response types
  catalogue/api.ts                         # NEW: fetchCatalogue
  catalogue/format.ts                      # NEW: formatPrice, formatDuration
  catalogue/format.test.ts                 # NEW
  catalogue/openToday.ts                   # NEW: openTodayText
  catalogue/openToday.test.ts              # NEW
```

All backend commands run from `backend/`, and all frontend commands from `frontend/`.

---

### Task 1: Branch, catalogue models and migration `0002`

**Files:**
- Create: `backend/app/models/catalogue.py`, `backend/migrations/versions/0002_create_catalogue.py`, `backend/tests/integration/test_catalogue_constraints.py`
- Modify: `backend/app/models/__init__.py`, `backend/tests/integration/test_migrations.py`, `.gitignore`

**Interfaces:**
- Consumes: `Base` and its naming convention, and the fixtures `fresh_database_url`, `db_session` and `alembic_config` (Milestone 1).
- Produces these models in `app/models/catalogue.py`, all re-exported from `app.models`:
  - `BayType` (`bay_types`): `id: int` PK, `slug: str` (`String(64)`, unique), `name: str` (`String(100)`).
  - `Bay` (`bays`): `id`, `slug` (unique), `name`, `bay_type_id` (FK `bay_types.id`), `active: bool` (server default true), and `bay_type` relationship.
  - `Service` (`services`): `id`, `slug` (unique), `name`, `category: str` (`String(50)`), `description: str` (`Text`), `duration_minutes: int`, `price_from_pence: int`, `price_to_pence: int | None`, `required_bay_type_id` (FK `bay_types.id`), `approval_mode: str` (`String(20)`), `active: bool` (server default true), `sort_order: int`.
  - `OpeningHours` (`opening_hours`): `weekday: int` PK (no autoincrement), `open_time: time | None`, `close_time: time | None`, and `breaks` relationship ordered by `start_time`.
  - `OpeningHoursBreak` (`opening_hours_breaks`): `id`, `weekday` (FK `opening_hours.weekday`, `ondelete="CASCADE"`), `start_time: time`, `end_time: time`.
  - Check constraints, named so the convention produces `ck_<table>_<name>`:
    - `services`: `duration_positive` (`duration_minutes > 0`), `price_from_non_negative` (`price_from_pence >= 0`), `price_range_ordered` (`price_to_pence IS NULL OR price_to_pence >= price_from_pence`), `approval_mode_valid` (`approval_mode IN ('instant', 'needs_approval')`).
    - `opening_hours`: `weekday_range` (`weekday BETWEEN 0 AND 6`), `open_close_together` (both null or both set), `open_before_close` (`open_time < close_time`).
    - `opening_hours_breaks`: `start_before_end` (`start_time < end_time`).
  - Migration revision `"0002"`, `down_revision = "0001"`, filename `0002_create_catalogue.py`. Its `downgrade()` drops the five tables in reverse dependency order.

- [ ] **Step 1: Create the branch and ignore mockups**

```bash
git switch main
git pull
git switch -c milestone2-catalogue
```

Add `.superpowers/` to the end of `.gitignore`. Then commit the design doc and this plan:

```bash
git add .gitignore docs/superpowers
git commit -m "docs: milestone 2 catalogue design and plan"
```

- [ ] **Step 2: Write the failing tests**

In `test_migrations.py`, add:

```python
CATALOGUE_TABLES = {"bay_types", "bays", "services", "opening_hours", "opening_hours_breaks"}

def test_upgrade_head_creates_catalogue_tables(fresh_database_url: str) -> None:
    command.upgrade(alembic_config(fresh_database_url), "head")
    assert CATALOGUE_TABLES <= set(inspect(make_engine(fresh_database_url)).get_table_names())

def test_downgrade_to_0001_drops_catalogue_tables(fresh_database_url: str) -> None:
    cfg = alembic_config(fresh_database_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")
    tables = set(inspect(make_engine(fresh_database_url)).get_table_names())
    assert tables.isdisjoint(CATALOGUE_TABLES) and "settings" in tables
```

In `test_catalogue_constraints.py`, each test inserts one bad row inside `db_session.begin_nested()` and expects `sqlalchemy.exc.IntegrityError`. A module-level helper `make_service(session, **overrides) -> Service` builds a valid service on a fresh `BayType`, so each test changes only one field.

| Test | Bad value |
| --- | --- |
| `test_service_duration_must_be_positive` | `duration_minutes=0` |
| `test_service_price_cannot_be_negative` | `price_from_pence=-1` |
| `test_service_price_range_top_cannot_be_below_bottom` | `price_from_pence=500, price_to_pence=400` |
| `test_service_approval_mode_must_be_known` | `approval_mode="maybe"` |
| `test_service_slug_must_be_unique` | two services with `slug="mot-test"` |
| `test_opening_hours_weekday_must_be_0_to_6` | `weekday=7` |
| `test_opening_hours_open_and_close_set_together` | `open_time=time(8), close_time=None` |
| `test_opening_hours_open_before_close` | `open_time=time(17), close_time=time(8)` |
| `test_break_must_end_after_it_starts` | `start_time=time(13), end_time=time(12, 30)` |

Also add `test_valid_service_and_closed_day_are_accepted`. It inserts a valid range-priced service and a closed day (`OpeningHours(weekday=6, open_time=None, close_time=None)`) without error.

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `uv run pytest tests/integration/test_migrations.py tests/integration/test_catalogue_constraints.py -v`
Expected: FAIL with `ImportError` for the catalogue models, or missing tables.

- [ ] **Step 4: Implement the models, then write migration `0002`**

Autogenerate against a scratch database with `uv run alembic revision --autogenerate --rev-id 0002 -m "create catalogue"`, then check it by hand. Autogenerate skips check constraints, so add every `op.create_check_constraint` (or inline `sa.CheckConstraint`) yourself, using the same names as the models.

- [ ] **Step 5: Run the full suite and checks**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all pass. `test_models_match_migrations` passing proves the models and `0002` agree.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat(backend): catalogue tables with database-enforced rules"
```

---

### Task 2: Seed the demo garage

**Files:**
- Create: `backend/app/demo_data.py`
- Modify: `backend/app/seed.py`, `backend/tests/integration/test_seed.py`

**Interfaces:**
- Consumes: the models from Task 1, `Setting`.
- Produces:
  - In `app/demo_data.py`, every value from the design doc's "Demo data" section:
    - `DEMO_BAY_TYPES: Final[list[tuple[str, str]]]` as (slug, name): `("mot", "MOT ramp")`, `("general", "General bay")`.
    - `DEMO_BAYS: Final[list[tuple[str, str, str]]]` as (slug, name, bay type slug): `mot-bay`/`MOT bay`/`mot`, then `bay-1`, `bay-2`, `bay-3` named `Bay 1` to `Bay 3`, all `general`.
    - `DEMO_SERVICES: Final[list[DemoService]]`, where `DemoService` is a frozen dataclass with `slug, name, category, description, duration_minutes, price_from_pence, price_to_pence, bay_type_slug, approval_mode`. It holds the 10 services in the design doc's table order, and `sort_order` is the list index × 10.
    - `DEMO_OPENING_HOURS: Final[dict[int, tuple[time, time] | None]]`: 0 to 4 → 08:00–17:30, 5 → 09:00–14:00, 6 → 10:00–13:00.
    - `DEMO_BREAKS: Final[dict[int, list[tuple[time, time]]]]`: 0 to 4 → `[(12:30, 13:00)]`.
    - `DEMO_GARAGE_CONTACT: Final[dict[str, str]] = {"name": "Hillside Motors", "address": "12 Station Road, Anytown, AT1 2CD", "phone": "01632 960123", "email": "bookings@example.com"}`.
  - In `app/seed.py`:
    - `DEFAULT_SETTINGS` becomes `Final[dict[str, Any]]` and gains `"garage_timezone": "Europe/London"` and `"garage_contact": DEMO_GARAGE_CONTACT`, for 7 keys in total.
    - `seed(session)` still has the same signature and still never overwrites. It inserts settings, then bay types, bays and services (each `on_conflict_do_nothing` on `slug`, resolving FKs by selecting bay types by slug), then opening hours (`on_conflict_do_nothing` on `weekday` with `.returning(OpeningHours.weekday)`). It inserts `DEMO_BREAKS` only for the weekdays that statement returned, meaning days created in this run.

- [ ] **Step 1: Write the failing tests** in `test_seed.py`

Update `test_seed_inserts_default_policy_settings` and `test_seed_twice_creates_no_duplicates` for 7 settings: the 5 policy values plus `garage_timezone` and `garage_contact`. Update the `== 5` in `test_upgrade_head_on_seeded_database_keeps_data` to `== 7`. Then add:

```python
def count(session: Session, model: type[Base]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0

def test_seed_inserts_demo_catalogue(db_session: Session) -> None:
    seed(db_session)
    assert [count(db_session, m) for m in (BayType, Bay, Service, OpeningHours, OpeningHoursBreak)] \
        == [2, 4, 10, 7, 5]
    mot = db_session.scalars(select(Service).where(Service.slug == "mot-test")).one()
    assert (mot.duration_minutes, mot.price_from_pence, mot.price_to_pence) == (60, 5485, None)
    clutch = db_session.scalars(select(Service).where(Service.slug == "clutch-replacement")).one()
    assert (clutch.price_from_pence, clutch.price_to_pence, clutch.approval_mode) \
        == (45000, 75000, "needs_approval")

def test_seed_twice_keeps_catalogue_counts(db_session: Session) -> None:
    seed(db_session)
    seed(db_session)
    assert [count(db_session, m) for m in (BayType, Bay, Service, OpeningHours, OpeningHoursBreak)] \
        == [2, 4, 10, 7, 5]

def test_seed_keeps_edited_service_price(db_session: Session) -> None: ...
    # set mot-test price_from_pence = 4999, flush, seed again, expire_all, still 4999

def test_seed_keeps_deactivated_service_inactive(db_session: Session) -> None: ...
    # set full-service active = False, flush, seed again, still False

def test_seed_does_not_recreate_deleted_break(db_session: Session) -> None: ...
    # delete Monday's (weekday 0) break, flush, seed again: Monday has no breaks, total is 4
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest tests/integration/test_seed.py -v`
Expected: FAIL with `ImportError` (`app.demo_data` or the new imports) or wrong counts.

- [ ] **Step 3: Implement `app/demo_data.py` and extend `seed`**

Write one plain, customer-facing sentence of description per service, for example "Oil, filters, fluids and a 50-point check" for the full service.

- [ ] **Step 4: Run the full suite and checks**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(backend): seed the demo garage catalogue without overwriting edits"
```

---

### Task 3: Public catalogue API

**Files:**
- Create: `backend/app/repositories/__init__.py`, `backend/app/repositories/catalogue.py`, `backend/app/api/catalogue.py`, `backend/tests/integration/test_catalogue_api.py`
- Modify: `backend/app/db.py`, `backend/app/main.py`, `backend/tests/conftest.py`

**Interfaces:**
- Consumes: the models (Task 1), `seed` (Task 2), `create_app`, `AppConfig`, and the fixtures `db_session` and `migrated_url`.
- Produces:
  - `app/db.py`: `get_session(request: Request) -> Iterator[Session]` yields a `Session` on `request.app.state.engine` and closes it afterwards.
  - `app/repositories/catalogue.py`:
    - `list_active_services(session: Session) -> list[Service]` returns active services ordered by `sort_order`, then `id`.
    - `list_opening_hours(session: Session) -> list[OpeningHours]` returns the rows that exist, with breaks loaded via `selectinload`.
    - `get_setting(session: Session, key: str) -> Any | None`.
  - `app/api/catalogue.py`: `router = APIRouter()`, included in `create_app` with `prefix="/api"`. The response models:
    - `ServiceOut`: `slug, name, category, description: str`, `duration_minutes: int`, `price_from_pence: int`, `price_to_pence: int | None`, `approval_mode: Literal["instant", "needs_approval"]`.
    - `BreakOut`: `start: str`, `end: str`.
    - `OpeningDayOut`: `weekday: int`, `open: str | None`, `close: str | None`, `breaks: list[BreakOut]`. Times are formatted `"HH:MM"`.
    - `GarageOut`: `name, address, phone, email, timezone: str`.
  - The routes:
    - `GET /api/services` → `list[ServiceOut]`.
    - `GET /api/opening-hours` → `list[OpeningDayOut]`: always weekdays 0 to 6 in order, and a missing row comes out as `open=None, close=None, breaks=[]`.
    - `GET /api/garage` → `GarageOut` from `garage_contact` + `garage_timezone`. If either setting is missing or `garage_contact` doesn't validate, it raises `HTTPException(503, "Garage details unavailable")`.
  - `conftest.py` fixture `api_client(db_session, migrated_url) -> Iterator[TestClient]` builds `create_app(AppConfig(database_url=migrated_url))`, overrides `get_session` to yield `db_session`, and yields a `TestClient`. Tests insert or seed through `db_session`, and everything rolls back.

- [ ] **Step 1: Write the failing tests** in `test_catalogue_api.py`

```python
def test_services_lists_seeded_services_in_order(api_client, db_session) -> None:
    seed(db_session)
    body = api_client.get("/api/services").json()
    assert [s["slug"] for s in body][:2] == ["mot-test", "oil-filter-change"]
    assert len(body) == 10
    assert body[0] == {"slug": "mot-test", "name": "MOT test", "category": "MOT",
                       "description": ANY, "duration_minutes": 60, "price_from_pence": 5485,
                       "price_to_pence": None, "approval_mode": "instant"}

def test_services_hides_inactive_services(api_client, db_session) -> None:
    # seed, set full-service active=False, flush: "full-service" not in the slugs, len == 9

def test_services_does_not_expose_bay_details(api_client, db_session) -> None:
    # seed: no key containing "bay" in any item

def test_opening_hours_returns_seven_days_with_breaks(api_client, db_session) -> None:
    seed(db_session)
    body = api_client.get("/api/opening-hours").json()
    assert [d["weekday"] for d in body] == [0, 1, 2, 3, 4, 5, 6]
    assert body[0] == {"weekday": 0, "open": "08:00", "close": "17:30",
                       "breaks": [{"start": "12:30", "end": "13:00"}]}
    assert body[6] == {"weekday": 6, "open": "10:00", "close": "13:00", "breaks": []}

def test_opening_hours_shows_missing_day_as_closed(api_client, db_session) -> None:
    # seed, delete the weekday 2 row, flush: still 7 entries, body[2] ==
    # {"weekday": 2, "open": None, "close": None, "breaks": []}

def test_garage_returns_contact_and_timezone(api_client, db_session) -> None:
    seed(db_session)
    assert api_client.get("/api/garage").json() == {
        "name": "Hillside Motors", "address": "12 Station Road, Anytown, AT1 2CD",
        "phone": "01632 960123", "email": "bookings@example.com", "timezone": "Europe/London"}

def test_garage_returns_503_when_settings_missing(api_client) -> None:
    response = api_client.get("/api/garage")
    assert response.status_code == 503
    assert response.json() == {"detail": "Garage details unavailable"}

def test_garage_returns_503_when_contact_is_malformed(api_client, db_session) -> None:
    # seed, set the garage_contact value to {"name": "x"}, flush: 503
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest tests/integration/test_catalogue_api.py -v`
Expected: FAIL. The `api_client` fixture can't import `get_session`, or the routes return 404.

- [ ] **Step 3: Implement `get_session`, the repository functions, the router, and wire it into `create_app`**

- [ ] **Step 4: Run the full suite and checks, then look at the docs page**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all pass. Then run `docker compose up --build`, open http://localhost:8000/docs, and check that the three endpoints are listed with their response shapes.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(backend): public services, opening hours and garage endpoints"
```

---

### Task 4: Frontend data helpers

**Files:**
- Create: `frontend/src/catalogue/types.ts`, `frontend/src/catalogue/api.ts`, `frontend/src/catalogue/format.ts`, `frontend/src/catalogue/format.test.ts`, `frontend/src/catalogue/openToday.ts`, `frontend/src/catalogue/openToday.test.ts`

**Interfaces:**
- Consumes: the three endpoint shapes from Task 3.
- Produces:
  - `types.ts`: `Service`, `OpeningDay`, `Garage` matching `ServiceOut`, `OpeningDayOut` and `GarageOut` field for field; `Catalogue = { services: Service[]; hours: OpeningDay[]; garage: Garage }`; `CatalogueResult = { ok: true; data: Catalogue } | { ok: false; phone: string | null }`.
  - `api.ts`: `fetchCatalogue(): Promise<CatalogueResult>` requests `/api/services`, `/api/opening-hours` and `/api/garage` in parallel with `Promise.allSettled`. Any failure (rejected fetch or non-OK status) gives `{ ok: false, phone }`, where `phone` is the garage phone if that one request succeeded, otherwise `null`. It never throws.
  - `format.ts`:
    - `formatPrice(fromPence: number, toPence: number | null): string` gives `"£219"`, `"£54.85"` or `"£450–£750"` (en dash). Whole pounds show no pence. When `toPence` is null or equals `fromPence`, it shows a single price.
    - `formatDuration(minutes: number): string` gives `"45m"`, `"1h"`, `"1h 30m"` or `"6h"`.
  - `openToday.ts`: `openTodayText(hours: OpeningDay[], now: Date, timeZone: string): string`. It finds the current weekday (0 = Mon) and `HH:MM` in `timeZone` with `Intl.DateTimeFormat("en-GB", { timeZone, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(now)`. Then:
    - If today is open and the time is before close: `Open today 08:00–17:30`. This covers before opening too, and ignores breaks.
    - Otherwise, find the next open day 1 to 7 days ahead. `<when>` is `tomorrow` for 1 day ahead, otherwise the short day name (`Mon`). The text is `Closed now, opens <when> at 08:00` if today was open, or `Closed today, opens <when> at 08:00` if today is closed.
    - If no day is open: `Closed`.

- [ ] **Step 1: Write the failing tests**

`format.test.ts`:

```ts
it.each([
  [21900, null, '£219'], [5485, null, '£54.85'], [45000, 75000, '£450–£750'],
  [12000, 12000, '£120'], [9050, 18000, '£90.50–£180'],
])('formatPrice(%i, %s) is %s', (from, to, expected) =>
  expect(formatPrice(from, to)).toBe(expected))

it.each([[45, '45m'], [60, '1h'], [90, '1h 30m'], [360, '6h']])(
  'formatDuration(%i) is %s', (m, expected) => expect(formatDuration(m)).toBe(expected))
```

`openToday.test.ts` uses a `DEMO_HOURS: OpeningDay[]` constant equal to the seeded week (Mon to Fri 08:00–17:30 with a 12:30–13:00 break, Sat 09:00–14:00, Sun 10:00–13:00). 2026-11-10 is a Tuesday in GMT, and 2026-07-14 is a Tuesday in BST.

| Test | `now` | Hours | Expected |
| --- | --- | --- | --- |
| open mid-morning | `2026-11-10T10:00:00Z` | demo | `Open today 08:00–17:30` |
| before opening | `2026-11-10T07:00:00Z` | demo | `Open today 08:00–17:30` |
| during lunch | `2026-11-10T12:45:00Z` | demo | `Open today 08:00–17:30` |
| after closing | `2026-11-10T18:00:00Z` | demo | `Closed now, opens tomorrow at 08:00` |
| Friday evening → Saturday hours | `2026-11-13T18:00:00Z` | demo | `Closed now, opens tomorrow at 09:00` |
| summer time, open (08:30 BST) | `2026-07-14T07:30:00Z` | demo | `Open today 08:00–17:30` |
| summer time, closed (17:45 BST) | `2026-07-14T16:45:00Z` | demo | `Closed now, opens tomorrow at 08:00` |
| closed day | `2026-11-11T12:00:00Z` (Wed) | demo with Wed and Thu closed | `Closed today, opens Fri at 08:00` |
| uses the given zone, not the device's | `2026-11-10T23:30:00Z` | demo, zone `Asia/Tokyo` (Wed 08:30 there) | `Open today 08:00–17:30` |
| never open | any | all days closed | `Closed` |

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `npm test`
Expected: FAIL. `./format` and `./openToday` can't be resolved.

- [ ] **Step 3: Implement `types.ts`, `format.ts`, `openToday.ts` and `api.ts`**

`fetchCatalogue` is tested through `App` in Task 5.

- [ ] **Step 4: Run every frontend check**

Run: `npm run lint && npm run typecheck && npm test`
Expected: all succeed. The old `App.test.tsx` still passes, because `App` hasn't changed yet.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): catalogue fetching, price, duration and open-today helpers"
```

---

### Task 5: The public catalogue page

**Files:**
- Create: `frontend/src/App.css`
- Modify: `frontend/src/App.tsx`, `frontend/src/App.test.tsx` (rewritten)

**Interfaces:**
- Consumes: everything in `src/catalogue/` (Task 4).
- Produces: `export function App({ now = () => new Date() }: { now?: () => Date }): JSX.Element`. It renders:
  - **Loading:** the text `Loading…`.
  - **Error:** an alert (`role="alert"`) reading `Sorry, we couldn't load our services right now.`, plus `Please call us on <phone>` with a `tel:` link when the phone is known.
  - **Ready:**
    - an `<h1>` with the garage name, then the strip `openTodayText(hours, now(), garage.timezone)`
    - one `<section>` per category, ordered by first appearance, with an `<h2>` of the category name and a `<ul>` of cards
    - each card is an `<li>` with an `<h3>` service name, the description, `formatDuration` and `formatPrice`, and the text `Needs approval` only for `needs_approval` services
    - an "Opening hours" `<h2>` section listing Monday to Sunday with times or `Closed`, and breaks as `Closed 12:30–13:00`
    - a "Contact" `<h2>` section with the address, a phone `tel:` link (spaces stripped from the href) and an email `mailto:` link
  - Phone-first CSS in `App.css`: cards in one column, two or more columns from about 640px wide, and readable contrast in light and dark themes.

- [ ] **Step 1: Write the failing tests** in `App.test.tsx`

Stub `fetch` with a function that answers by URL using small fixtures: 3 services in 2 categories (`mot-test`, `full-service`, `clutch-replacement`), the demo week, and the demo garage. Pass `now={() => new Date('2026-11-10T10:00:00Z')}`.

```tsx
it('shows the garage name, open-today strip and services grouped by category', async () => {
  // findByRole heading level 1 "Hillside Motors"; text "Open today 08:00–17:30";
  // h2 "MOT" and h2 "Repairs" exist; within the "Full service" card: "3h" and "£219"
})
it('badges only needs-approval services', async () => {
  // within the "Clutch replacement" card: "Needs approval"; within "Full service": none
})
it('lists weekly hours with breaks and links the contact details', async () => {
  // text "Closed 12:30–13:00"; link "01632 960123" has href "tel:01632960123";
  // link "bookings@example.com" has href "mailto:bookings@example.com"
})
it('shows an error with the phone number when services fail but garage loads', async () => {
  // /api/services → 500: role alert contains "couldn't load"; link href "tel:01632960123"
})
it('shows an error without a phone number when every request fails', async () => {
  // fetch rejects: role alert present, no link with a tel: href
})
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `npm test`
Expected: FAIL. The page still shows `API: …`, so the headings aren't found.

- [ ] **Step 3: Implement `App` and `App.css`**

Use `useEffect` with the same `cancelled` guard as the Milestone 1 `App`.

- [ ] **Step 4: Run every frontend check, then look at it**

Run: `npm run lint && npm run typecheck && npm test && npm run build`
Expected: all succeed. Then run `docker compose up --build`, open http://localhost:8080, and check it at phone width with your browser's device toolbar (F12, then the phone icon). It should match mockup B.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): public catalogue page with services, hours and contact"
```

---

### Task 6: CI smoke check, README and pull request

**Files:**
- Modify: `.github/workflows/ci.yml`, `README.md`

**Interfaces:**
- Consumes: `GET /api/services` (Task 3) and the seeded `mot-test` (Task 2).
- Produces:
  - In the `compose` job, a step after the health check: `curl -fsS http://localhost:8080/api/services | grep '"slug":"mot-test"'`.
  - A README section, "Changing the demo data", which says:
    - demo values live in `backend/app/demo_data.py`
    - the seed only adds what's missing, so an edited file reaches an existing database only after a reset with `docker compose down -v`
    - admin screens for editing arrive in Milestone 7

- [ ] **Step 1: Add the CI step and README section**

- [ ] **Step 2: Validate the workflow locally**

Run: `uvx --from check-jsonschema check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/ci.yml`
Expected: `ok -- validation done`

- [ ] **Step 3: Verify the whole stack from a clean state**

Run: `docker compose down -v` then `docker compose up --build`.
Expected: http://localhost:8080 shows Hillside Motors with 10 services in 6 categories, and http://localhost:8080/api/services returns 10 items.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml README.md
git commit -m "ci: smoke-check the services endpoint; document demo data"
```

- [ ] **Step 5: Push and open a PR (ask the user before pushing)**

Run: `git push -u origin milestone2-catalogue`. Open a PR into `main` at https://github.com/Adxm1go7/car-repair/compare/main...milestone2-catalogue.
Expected: the `backend`, `frontend` and `compose` checks all pass on the PR. Then merge it.

---

## Milestone 2 definition of done

- [ ] From a clean state, `docker compose up --build` gives a page at :8080 showing the seeded services, opening hours and contact details (Task 6, Step 3).
- [ ] Every new endpoint has integration tests against real PostgreSQL, and CI is green on the PR (Task 3, Task 6).
