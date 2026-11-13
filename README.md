# Garage Booking

Online booking system for a car repair garage: a public booking site and a staff back office,
backed by a FastAPI API and PostgreSQL.

## Quick start

Prerequisite: [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
docker compose up --build
```

This starts PostgreSQL, Mailpit, the API, the web app and a worker. On every start the API
applies database migrations and seeds default settings and the demo garage (safe to re-run;
existing values are kept). The worker releases slot holds that have run out, every 60 seconds
(`WORKER_INTERVAL_SECONDS`).

To book, open http://localhost:8080, tick one or more services, click **Choose a time**, pick
a day and a time, then enter your details and confirm. The time is held for you for 5
minutes while you type (the `slot_hold_minutes` setting). There is no payment step yet.
No `.env` file is needed. To override defaults, copy `.env.example` to `.env`.

| What | URL |
| --- | --- |
| Web app | http://localhost:8080 |
| API docs (Swagger) | http://localhost:8000/docs |
| API health | http://localhost:8000/api/health |
| Availability example | http://localhost:8000/api/availability?services=mot-test&date=YYYY-MM-DD |
| Mailpit (captured emails) | http://localhost:8025 |
| PostgreSQL | `localhost:5433`, user/password/db `garage` |

For the availability example, use a date (`YYYY-MM-DD`) from today up to 60 days ahead.
Repeat `services=` to book several services together, for example
`?services=full-service&services=front-brake-pads&date=...`.

Stop with `docker compose down`. Add `-v` to also delete the database volume.

Re-run the seed by hand:

```bash
docker compose exec api python -m app.seed
```

> **All default credentials and values in this repo are for local development only.**
> Production must set its own values through environment variables.

## Changing the demo data

The demo garage (Hillside Motors: its services, bays, opening hours and contact details) is
fictional. Its values live in one file, `backend/app/demo_data.py`.

The seed only adds what's missing. It never overwrites a value or brings back something that
was removed, so edits to `demo_data.py` don't reach a database that already exists. To load
your edited values, reset the database:

```bash
docker compose down -v
docker compose up --build
```

Admin screens for editing the catalogue arrive in Milestone 7.

## Local development

Prerequisites: Python 3.13 and [uv](https://docs.astral.sh/uv/), Node 22, and Docker
(backend tests start a throwaway PostgreSQL with Testcontainers).

### Backend (`backend/`)

```bash
cd backend
uv sync
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

To run the API outside Docker against the Compose database (`docker compose up -d db`):

```bash
export DATABASE_URL=postgresql+psycopg://garage:garage@localhost:5433/garage
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn --factory app.main:create_app --reload
```

On Windows PowerShell, set the variable with `$env:DATABASE_URL = "..."` instead of `export`.

### Frontend (`frontend/`)

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

`npm run dev` starts the dev server on http://localhost:5173 and proxies `/api` to
`http://localhost:8000`.

### End-to-end test (`e2e/`)

A [Playwright](https://playwright.dev/) test books an MOT in a real browser, then checks the
booked time is no longer offered. It runs against the Compose stack, so start that first:

```bash
docker compose up --build -d --wait
cd e2e
npm ci
npx playwright install chromium
npm test
```

Each run makes a real booking in the local database. `docker compose down -v` clears them.
Set `BASE_URL` to test another address.

## Documentation

- [Specification](docs/SPEC.md)
- [Implementation plans](docs/superpowers/plans/)
