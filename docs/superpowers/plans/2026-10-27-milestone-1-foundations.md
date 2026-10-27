# Milestone 1: Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fresh clone of the repo starts the whole stack (API, web, PostgreSQL, mail catcher) with one command, migrations and seed data apply automatically, and GitHub Actions runs lint, type checks, tests and a Docker build green on every push.

**Architecture:** Monorepo with `backend/` (FastAPI, layered: `app/api` routes → services → repositories, though M1 only needs routes and models) and `frontend/` (one Vite + React + TS app; the public site and the staff back office will be two route areas of this app, `/` and `/admin`, sharing one build). The backend runs sync SQLAlchemy 2.0 on psycopg 3 and is built by an app factory `create_app(config)`, so tests inject their own database. In M1 the only domain table is `settings`, because the spec puts policy values there. This gives the first migration and the seed command real work.

**Tech Stack:** Python 3.13, uv, FastAPI, SQLAlchemy 2.0, psycopg 3, Alembic, pydantic-settings, pytest, Testcontainers, ruff, mypy (strict) · Node 22, Vite, React 18, TypeScript, ESLint, Vitest, React Testing Library · PostgreSQL 17, Mailpit, nginx · Docker Compose · GitHub Actions.

**Spec:** [docs/SPEC.md](../../SPEC.md). The relevant sections are "Build order" item 1, "Architecture and tech stack", "Testing strategy" and "Decisions log" (policy settings).

## Global Constraints

- Every tool and hosting choice must have a free option; no paid services.
- No secrets in the repository; configuration comes from environment variables, one set per environment. `.env` is git-ignored; `.env.example` is committed.
- Times stored in UTC: every timestamp column is `DateTime(timezone=True)`.
- Policy values live in the `settings` table, not hardcoded in logic. Seed defaults: booking window 60 days, cut-off 2 hours before a slot, slot hold 10 minutes, free cancellation 24 hours, deposit £20.
- Inject the clock into anything time-dependent. M1 has nothing time-dependent, so don't add a clock abstraction yet.
- CI runs lint, type checks, all tests and a Docker build on every push.
- The developer machine is Windows. Commands in this plan use POSIX shell syntax (Git Bash), and files that run inside Linux containers must have LF line endings.
- Versions: Python `3.13`, Node `22`, image `postgres:17-alpine`, image `axllent/mailpit:v1.21`, image `nginx:1.27-alpine`.

## Review Focus

1. **Running the seed twice.** `docker compose up` re-runs the seed on every start. A second run must insert nothing and must not overwrite a value an admin has since changed. Pinned in Task 4.
2. **Database down or slow at startup.** The API must not start serving before Postgres is ready, and `/api/health` must return 503 with a JSON body, not an unhandled 500, when the database is unreachable. Pinned in Task 2 (503 test) and Task 6 (healthcheck plus `depends_on: service_healthy`).
3. **Missing `DATABASE_URL`.** The app must fail at startup with an error naming the variable, not on the first request. Pinned in Task 1.
4. **Models and migrations drifting apart.** A later model edit without a migration must fail CI. Pinned in Task 3 (`alembic check` test) and Task 3's downgrade/upgrade round trip.
5. **CRLF line endings from a Windows checkout reaching a Linux container.** A CRLF `nginx.conf` or shell line breaks the container. `.gitattributes` forces LF, and the CI compose smoke test starts the real images. Pinned in Task 6.

---

## File Structure

```
.gitattributes                 # LF for everything container-side
.gitignore
.env.example                   # documents every env var, dev-only values
README.md                      # one-command start, ports, dev commands
docker-compose.yml             # db, mailpit, api, web
.github/workflows/ci.yml
backend/
  pyproject.toml               # deps + ruff + mypy + pytest config
  uv.lock
  Dockerfile
  alembic.ini
  migrations/
    env.py
    script.py.mako
    versions/0001_create_settings.py
  app/
    __init__.py
    config.py                  # AppConfig, get_config()
    db.py                      # make_engine()
    main.py                    # create_app()
    api/__init__.py
    api/health.py              # GET /api/health
    models/__init__.py         # imports every model, exposes Base
    models/base.py             # Base with naming convention
    models/setting.py          # Setting
    seed.py                    # DEFAULT_SETTINGS, seed(), main()
  tests/
    conftest.py                # postgres container + DB fixtures
    unit/test_config.py
    integration/test_health.py
    integration/test_migrations.py
    integration/test_seed.py
frontend/
  package.json, package-lock.json, tsconfig*.json, eslint.config.js, index.html
  vite.config.ts               # /api proxy + vitest config
  Dockerfile                   # build stage → nginx
  nginx.conf                   # serves SPA, proxies /api to api:8000
  src/main.tsx
  src/App.tsx
  src/App.test.tsx
  src/test-setup.ts
```

Python modules use the `app.` package root. All backend commands run from `backend/`, and all frontend commands from `frontend/`.

---

### Task 1: Backend skeleton, tooling and config

**Files:**
- Create: `.gitignore`, `.gitattributes`, `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/tests/unit/test_config.py`

**Interfaces:**
- Produces: `class AppConfig(BaseSettings)` with fields `database_url: str` (required, env `DATABASE_URL`) and `environment: Literal["development", "test", "production"] = "development"` (env `ENVIRONMENT`). It does not read any `.env` file, because Compose and CI pass env vars directly. Also `get_config() -> AppConfig`, cached with `functools.lru_cache`.

- [ ] **Step 1: Install uv and create the project**

```bash
winget install --id=astral-sh.uv -e   # then open a new terminal so uv is on PATH
cd backend
uv init --app --name garage-backend --python 3.13 --no-readme --vcs none .
uv add fastapi "uvicorn[standard]" "sqlalchemy>=2.0" "psycopg[binary]" alembic pydantic-settings
uv add --dev pytest httpx "testcontainers[postgres]" ruff mypy
```

Delete the `main.py` that `uv init` generates. In `pyproject.toml`, set these values:
- `[tool.ruff]` `line-length = 100`, `target-version = "py313"`
- `[tool.ruff.lint]` `select = ["E", "F", "I", "B", "UP", "S", "SIM"]`
- `[tool.ruff.lint.per-file-ignores]` `"tests/**" = ["S101"]`
- `[tool.mypy]` `strict = true`, `plugins = ["pydantic.mypy"]`, `files = ["app", "tests"]` (Task 3 adds `"migrations"` once that folder exists)
- `[tool.pytest.ini_options]` `testpaths = ["tests"]`, `pythonpath = ["."]` (so tests can import `app`), `addopts = "-ra --strict-markers"`

`.gitignore` covers `.env`, `__pycache__/`, `.venv/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `node_modules/`, `dist/` and `coverage/`. Write `.gitattributes` with `* text=auto eol=lf`, and add `*.png binary` and `*.jpg binary`.

- [ ] **Step 2: Write the failing tests** in `backend/tests/unit/test_config.py`

```python
def test_config_reads_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    config = AppConfig()
    assert config.database_url == "postgresql+psycopg://u:p@h:5432/d"
    assert config.environment == "development"

def test_config_without_database_url_fails_naming_the_field(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        AppConfig()

def test_config_rejects_unknown_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    with pytest.raises(ValidationError):
        AppConfig()
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `uv run pytest tests/unit -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 4: Implement `AppConfig` and `get_config()` in `backend/app/config.py`**

- [ ] **Step 5: Run the tests and all checks**

Run: `uv run pytest tests/unit -v && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: 3 passed, and ruff and mypy report no issues.

- [ ] **Step 6: Commit**

```bash
git add .gitignore .gitattributes backend
git commit -m "chore(backend): scaffold FastAPI project with config, ruff and mypy"
```

---

### Task 2: App factory, database engine and health endpoint

**Files:**
- Create: `backend/app/db.py`, `backend/app/main.py`, `backend/app/api/__init__.py`, `backend/app/api/health.py`, `backend/tests/conftest.py`, `backend/tests/integration/test_health.py`

**Interfaces:**
- Consumes: `AppConfig`, `get_config()` (Task 1).
- Produces:
  - `make_engine(database_url: str) -> sqlalchemy.Engine`, with `pool_pre_ping=True` and `connect_args={"connect_timeout": 5}`.
  - `create_app(config: AppConfig | None = None) -> FastAPI`. It defaults to `get_config()` and stores the engine on `app.state.engine`. Uvicorn runs it with `--factory app.main:create_app`; there is no module-level `app`.
  - `GET /api/health` returns 200 `{"status": "ok", "database": "ok"}`. When `SELECT 1` raises `sqlalchemy.exc.OperationalError`, it returns 503 `{"status": "error", "database": "unavailable"}`. All future routes also live under `/api`.
  - Fixtures in `tests/conftest.py`: `postgres_url` is session-scoped. It starts `PostgresContainer("postgres:17-alpine")` and yields `container.get_connection_url(driver="psycopg")`. `client` is function-scoped and yields a `TestClient(create_app(AppConfig(database_url=postgres_url)))`.

- [ ] **Step 1: Write the failing tests** in `backend/tests/integration/test_health.py`

```python
def test_health_reports_ok_when_database_reachable(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}

def test_health_reports_503_when_database_unreachable():
    app = create_app(AppConfig(database_url="postgresql+psycopg://u:p@127.0.0.1:1/none"))
    response = TestClient(app).get("/api/health")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest tests/integration/test_health.py -v` (Docker must be running)
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Implement `make_engine`, `create_app` and the health router**

The health route reads the engine from `request.app.state.engine`.

- [ ] **Step 4: Run the tests and checks**

Run: `uv run pytest -v && uv run ruff check . && uv run mypy`
Expected: 5 passed, and ruff and mypy are clean.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(backend): app factory, engine and /api/health with DB check"
```

---

### Task 3: Alembic and the `settings` table

**Files:**
- Create: `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`, `backend/migrations/versions/0001_create_settings.py`, `backend/app/models/__init__.py`, `backend/app/models/base.py`, `backend/app/models/setting.py`, `backend/tests/integration/test_migrations.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Consumes: `get_config()`, `make_engine()`, `postgres_url` fixture.
- Produces:
  - `class Base(DeclarativeBase)`, whose `metadata` uses the naming convention `{"ix": "ix_%(column_0_label)s", "uq": "uq_%(table_name)s_%(column_0_name)s", "ck": "ck_%(table_name)s_%(constraint_name)s", "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s"}`.
  - `class Setting(Base)` maps the table `settings` with these columns:
    - `key: Mapped[str]` is `String(64)` and the primary key.
    - `value: Mapped[Any]` is `JSONB` and not null.
    - `updated_at: Mapped[datetime]` is `DateTime(timezone=True)`, not null, with `server_default=func.now()`.
  - `app/models/__init__.py` re-exports `Base` and `Setting`, so importing `app.models` registers every model.
  - Migration revision id is `"0001"`, filename `0001_create_settings.py`.
  - `migrations/env.py` uses `config.get_main_option("sqlalchemy.url")` when it is set and falls back to `get_config().database_url` otherwise. Its `target_metadata` is `app.models.Base.metadata`, and it sets `compare_type=True`.
  - New conftest helpers and fixtures:
    - `alembic_config(database_url: str) -> alembic.config.Config` finds `alembic.ini` relative to `conftest.py`.
    - `fresh_database_url` is function-scoped. It runs `CREATE DATABASE test_<uuid hex>` on the container, yields that URL, then drops the database.
    - `migrated_url` is session-scoped. It upgrades `postgres_url` to head once.
    - `db_session` is function-scoped. It is a `Session` bound to a connection inside an outer transaction that rolls back after the test.

- [ ] **Step 1: Initialise Alembic**

Run `uv run alembic init migrations` from `backend/`. Then edit `env.py` as described above, and set `file_template = %%(rev)s_%%(slug)s` in `alembic.ini`.

- [ ] **Step 2: Write the failing tests** in `backend/tests/integration/test_migrations.py`

```python
def test_upgrade_head_on_empty_database_creates_settings(fresh_database_url):
    command.upgrade(alembic_config(fresh_database_url), "head")
    columns = {c["name"] for c in inspect(make_engine(fresh_database_url)).get_columns("settings")}
    assert columns == {"key", "value", "updated_at"}

def test_downgrade_to_base_and_upgrade_again(fresh_database_url):
    cfg = alembic_config(fresh_database_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert "settings" not in inspect(make_engine(fresh_database_url)).get_table_names()
    command.upgrade(cfg, "head")
    assert "settings" in inspect(make_engine(fresh_database_url)).get_table_names()

def test_models_match_migrations(fresh_database_url):
    cfg = alembic_config(fresh_database_url)
    command.upgrade(cfg, "head")
    command.check(cfg)  # raises AutogenerateDiffsDetected on drift
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `uv run pytest tests/integration/test_migrations.py -v`
Expected: FAIL. The `settings` table does not exist, or `app.models` cannot be imported.

- [ ] **Step 4: Implement `Base` and `Setting`, then write the migration `0001`**

Autogenerate the migration with `uv run alembic revision --autogenerate --rev-id 0001 -m "create settings"` against a scratch database. Review it by hand and rename the file to `0001_create_settings.py`. Its `downgrade()` drops the table.

- [ ] **Step 5: Run the full suite and checks**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all pass. The checks cover `migrations/`, so fix any type errors in `env.py`.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat(backend): alembic setup and settings table migration"
```

---

### Task 4: Idempotent seed command

**Files:**
- Create: `backend/app/seed.py`, `backend/tests/integration/test_seed.py`

**Interfaces:**
- Consumes: `Setting`, `make_engine`, `get_config`, and the fixtures `db_session`, `fresh_database_url` and `alembic_config` (Task 3).
- Produces:
  - `DEFAULT_SETTINGS: Final[dict[str, int]] = {"booking_window_days": 60, "booking_cutoff_minutes": 120, "slot_hold_minutes": 10, "free_cancellation_hours": 24, "deposit_amount_pence": 2000}`. These key names are the contract for later milestones.
  - `seed(session: Session) -> None` inserts any missing defaults with `postgresql.insert(...).on_conflict_do_nothing(index_elements=["key"])`. It never overwrites an existing value. The caller commits.
  - `main() -> None` is the entry point for `python -m app.seed`. It opens a session from `make_engine(get_config().database_url)`, calls `seed`, commits, and prints `Seed complete`.

- [ ] **Step 1: Write the failing tests** in `backend/tests/integration/test_seed.py`

```python
def test_seed_inserts_default_policy_settings(db_session):
    seed(db_session)
    rows = {s.key: s.value for s in db_session.scalars(select(Setting))}
    assert rows == {
        "booking_window_days": 60, "booking_cutoff_minutes": 120, "slot_hold_minutes": 10,
        "free_cancellation_hours": 24, "deposit_amount_pence": 2000,
    }

def test_seed_twice_creates_no_duplicates(db_session):
    seed(db_session)
    seed(db_session)
    assert db_session.scalar(select(func.count()).select_from(Setting)) == 5

def test_seed_keeps_admin_edited_value(db_session):
    seed(db_session)
    db_session.get(Setting, "slot_hold_minutes").value = 15
    db_session.flush()
    seed(db_session)
    db_session.expire_all()
    assert db_session.get(Setting, "slot_hold_minutes").value == 15

def test_upgrade_head_on_seeded_database_keeps_data(fresh_database_url):
    cfg = alembic_config(fresh_database_url)
    command.upgrade(cfg, "head")
    with Session(make_engine(fresh_database_url)) as session:
        seed(session)
        session.commit()
    command.upgrade(cfg, "head")
    with Session(make_engine(fresh_database_url)) as session:
        assert session.scalar(select(func.count()).select_from(Setting)) == 5
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest tests/integration/test_seed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.seed'`

- [ ] **Step 3: Implement `DEFAULT_SETTINGS`, `seed` and `main` in `backend/app/seed.py`**

- [ ] **Step 4: Run the full suite and checks**

Run: `uv run pytest -v && uv run ruff check . && uv run mypy`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(backend): idempotent seed command for policy settings"
```

---

### Task 5: Frontend scaffold with an API status page

**Files:**
- Create: everything under `frontend/` listed in the File Structure except `Dockerfile` and `nginx.conf`.

**Interfaces:**
- Consumes: `GET /api/health` (Task 2).
- Produces:
  - `export function App(): JSX.Element` renders an `<h1>` reading `Garage Booking` and a status line. The status line reads `API: checking…` until `fetch("/api/health")` settles. It then reads `API: ok` when the response is OK and its JSON `status === "ok"`, and `API: unavailable` for anything else, including a rejected fetch or a 503.
  - npm scripts: `dev`, `build` (`tsc -b && vite build`), `lint` (`eslint .`), `typecheck` (`tsc -b --noEmit`), `test` (`vitest run`).
  - `vite.config.ts` proxies `/api` to `http://localhost:8000` and configures Vitest with `environment: "jsdom"` and `setupFiles: ["./src/test-setup.ts"]`. The setup file imports `@testing-library/jest-dom/vitest`.

- [ ] **Step 1: Scaffold the project**

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

Remove the template's demo assets, demo CSS and counter code.

- [ ] **Step 2: Write the failing tests** in `frontend/src/App.test.tsx`

```tsx
afterEach(() => vi.unstubAllGlobals());

it("shows API ok when health check succeeds", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ status: "ok", database: "ok" }), { status: 200 })));
  render(<App />);
  expect(screen.getByRole("heading", { name: "Garage Booking" })).toBeInTheDocument();
  expect(await screen.findByText("API: ok")).toBeInTheDocument();
});

it("shows API unavailable on 503", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ status: "error", database: "unavailable" }), { status: 503 })));
  render(<App />);
  expect(await screen.findByText("API: unavailable")).toBeInTheDocument();
});

it("shows API unavailable when the request fails", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
  render(<App />);
  expect(await screen.findByText("API: unavailable")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `npm test`
Expected: FAIL. `App` has no named export, or the expected text is not found.

- [ ] **Step 4: Implement `App`**

- [ ] **Step 5: Run every frontend check**

Run: `npm run lint && npm run typecheck && npm test && npm run build`
Expected: all succeed, with 3 tests passed and `dist/` produced.

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat(frontend): Vite React TS scaffold with API status page"
```

---

### Task 6: Docker images, Compose stack and README

**Files:**
- Create: `backend/Dockerfile`, `backend/.dockerignore`, `frontend/Dockerfile`, `frontend/.dockerignore`, `frontend/nginx.conf`, `docker-compose.yml`, `.env.example`, `README.md`

**Interfaces:**
- Consumes: `create_app` (factory), `python -m app.seed`, `alembic upgrade head`, `npm run build`.
- Produces: the Compose service names `db`, `mailpit`, `api` and `web`, which CI and later milestones refer to. Ports and settings:

| Service | Image or build | Host port | Healthcheck |
| --- | --- | --- | --- |
| `db` | `postgres:17-alpine`, named volume `pgdata` | `5433:5432` | `pg_isready -U $POSTGRES_USER` |
| `mailpit` | `axllent/mailpit:v1.21` | `8025` (UI), `1025` (SMTP) | none |
| `api` | `./backend` | `8000` | `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"` |
| `web` | `./frontend` | `8080:80` | none |

- [ ] **Step 1: Write the backend Dockerfile**

Use a multi-stage build. The first stage, `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`, runs `uv sync --frozen --no-dev`. The second stage, `python:3.13-slim`, copies `.venv` and `app/`, `migrations/` and `alembic.ini`, and runs as a non-root user. Its CMD is:

`["sh", "-c", "alembic upgrade head && python -m app.seed && uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000"]`

- [ ] **Step 2: Write the frontend Dockerfile and `nginx.conf`**

The build stage, `node:22-alpine`, runs `npm ci && npm run build`. The serve stage is `nginx:1.27-alpine`. In `nginx.conf`, `location /api/` does `proxy_pass http://api:8000;`, and `location /` does `try_files $uri /index.html;`.

- [ ] **Step 3: Write `docker-compose.yml` and `.env.example`**

Variables come from `${VAR:-dev default}` so that a fresh clone works without a `.env`. The defaults are `POSTGRES_USER=garage`, `POSTGRES_PASSWORD=garage` and `POSTGRES_DB=garage`. These are development values; the README must say so. `api` receives:
- `DATABASE_URL=postgresql+psycopg://garage:garage@db:5432/garage`
- `ENVIRONMENT=development`
- `SMTP_HOST=mailpit`
- `SMTP_PORT=1025`

Nothing reads the SMTP variables yet; they reserve the names for M6. `api` has `depends_on: db: condition: service_healthy`, and `web` has `depends_on: api: condition: service_healthy`. `.env.example` lists every variable with a comment.

- [ ] **Step 4: Verify the one-command start from a clean state**

Run:
```bash
docker compose down -v
docker compose up --build -d --wait
curl -fsS http://localhost:8080/api/health
curl -fsS -o /dev/null -w "%{http_code}\n" http://localhost:8025
docker compose exec db psql -U garage -c "select key, value from settings order by key"
docker compose restart api && docker compose exec db psql -U garage -tc "select count(*) from settings"
```
Expected: `{"status":"ok","database":"ok"}`, then `200`, then the 5 settings rows, then a count of `5` after the restart (the seed is idempotent across restarts). Open http://localhost:8080 and confirm it shows `API: ok`.

- [ ] **Step 5: Write `README.md`**

Cover the following:
- prerequisites: Docker, plus Python 3.13 and uv and Node 22 for local development
- `docker compose up --build`
- the URL table (web 8080, API docs at 8000/docs, Mailpit 8025)
- how to run the backend and frontend checks locally (the exact commands from Tasks 4 and 5)
- `docker compose exec api python -m app.seed`
- a note that every default credential is for development only

- [ ] **Step 6: Commit**

```bash
git add .gitattributes .env.example docker-compose.yml README.md backend frontend
git commit -m "chore: Docker images and Compose stack with one-command start"
```

---

### Task 7: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the check commands from Tasks 1 to 6 and the Compose service names.
- Produces: a workflow named `CI` that triggers on `push` and `pull_request`. It has three jobs:
  - **`backend`** runs on `ubuntu-latest` from `working-directory: backend`. It installs uv with `astral-sh/setup-uv@v5` and caching enabled, then runs `uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and `uv run pytest -v`. Testcontainers uses the runner's Docker.
  - **`frontend`** uses `actions/setup-node@v4` with Node 22 and an npm cache, then runs `npm ci`, `npm run lint`, `npm run typecheck`, `npm test` and `npm run build`.
  - **`compose`** runs with `needs: [backend, frontend]`. It runs `docker compose up --build -d --wait`, then `curl -fsS http://localhost:8080/api/health | grep '"status":"ok"'`. On failure it runs `docker compose logs`, and it always runs `docker compose down -v`.

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

- [ ] **Step 2: Validate the workflow locally**

Run: `uvx --from check-jsonschema check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/ci.yml`
Expected: `ok -- validation done`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: lint, type check, test and compose smoke test on every push"
```

- [ ] **Step 4: Push the branch and confirm CI is green (ask the user before pushing)**

Run: `git push -u origin <branch>`. Open the run at https://github.com/Adxm1go7/car-repair/actions.
Expected: all three jobs pass.

- [ ] **Step 5: Hand a manual step to the user**

Tell the user to turn on branch protection on `main` and require the `backend`, `frontend` and `compose` checks. This meets the spec's "blocks merging on failure". The step needs repository admin rights in GitHub settings, and `gh` is not installed.

---

## Milestone 1 definition of done

- [ ] `git clone … && docker compose up --build` gives a working stack: web at :8080 shows `API: ok`, and the `settings` table holds the 5 seeded rows (Task 6, Step 4).
- [ ] The CI workflow is green on the pushed branch (Task 7, Step 4).
