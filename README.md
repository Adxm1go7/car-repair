# Garage Booking

Online booking system for a car repair garage: a public booking site and a staff back office,
backed by a FastAPI API and PostgreSQL.

## Live demo

**<https://garage-demo.duckdns.org>**

It's a demo: no real email is sent and no real money moves.

- **Pay** with Stripe's test card `4242 4242 4242 4242`, any future expiry date and any CVC.
- **Emails** appear in the **Demo inbox** (linked in the footer) instead of being sent.
  Everyone can see that inbox, so don't type real names, emails or car details.
- **Staff side:** open `/staff` and log in as `admin@example.test` / `demo-admin-pass` or
  `staff@example.test` / `demo-staff-pass`. These two logins can't be locked, reset or
  changed.
- **Everything resets** to the demo data at 03:00 UK time every night.

A five-minute walkthrough:

1. **Book.** On the home page, tick **MOT test**, click **Choose a time**, pick a time, enter
   made-up details and pay with the test card. You land on "You're booked".
2. **Read the email.** Open the **Demo inbox** and the confirmation email. Its link opens your
   booking, where you could cancel it.
3. **Log in as staff.** Go to `/staff` and log in as the admin. Your booking is on the day
   view.
4. **Move it.** Open the booking, choose **Move**, and pick another time or bay.
5. **See what the customer got.** Back in the Demo inbox, the "moved" email shows the old and
   new times.

| Choosing services | Picking a time |
| --- | --- |
| ![The home page: services in groups with prices and times](docs/images/demo-home.png) | ![Choose a time: a day strip and morning and afternoon slots](docs/images/demo-book.png) |
| **Staff day view** | **Demo inbox** |
| ![The staff day view: bookings in columns, one per bay](docs/images/demo-staff-day.png) | ![The Demo inbox: booking confirmation emails, newest first](docs/images/demo-inbox.png) |
| **Admin settings** | **On a phone** |
| ![Settings: the services list with prices, durations and reorder buttons](docs/images/demo-settings.png) | ![The home page on a phone](docs/images/demo-phone.png) |

How it's hosted (a free Oracle Cloud server, Caddy for HTTPS), and how to deploy or rebuild
it: [docs/deployment.md](docs/deployment.md).

## Quick start

Prerequisite: [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
docker compose up --build
```

This starts PostgreSQL, Mailpit, the API, the web app and a worker. On every start the API
applies database migrations and seeds default settings and the demo garage (safe to re-run;
existing values are kept). Every 60 seconds (`WORKER_INTERVAL_SECONDS`) the worker releases
slot holds that have run out and closes their payment forms. Every 5 seconds
(`EMAIL_INTERVAL_SECONDS`) it queues reminders and sends queued emails.

To book, open http://localhost:8080, tick one or more services, click **Choose a time**, pick
a day and a time, enter your details and click **Continue to payment**, then pay the £20
deposit. The time is held for 5 minutes while you type (`slot_hold_minutes`) and 10 more
while you pay (`payment_hold_minutes`). The deposit is `deposit_amount_pence`.

**Payments.** With no Stripe keys, the payment step runs in **demo mode**: a "Pay £20 (demo)"
button instead of a card form, so a fresh clone books end to end with no setup. With Stripe
test keys in `.env`, it shows Stripe's real payment form inside the page (test mode, so no
money moves). See [docs/stripe-setup.md](docs/stripe-setup.md). Demo mode is refused in
production and never used in CI.

**Emails.** Every email goes to [Mailpit](http://localhost:8025), which catches it instead of
delivering it. After paying, a confirmation arrives there with a private link to the booking
(`/booking/<reference>#t=<token>`). The link lets the customer view the booking and cancel it
more than 24 hours before the start (`free_cancellation_hours`), which refunds the deposit.
Customers can't reschedule: the page asks them to call. A reminder is sent 48 hours before
(`reminder_hours_before`), and a cancellation email after cancelling. Failed sends are retried
after 1, 5, 15 and 60 minutes. `PUBLIC_BASE_URL` is the address the links point to, and
`SMTP_FROM` is the sender.

**Staff back office.** Open http://localhost:8080/staff and log in with one of the sample
accounts. The seed adds them everywhere except production (and on the live demo):

| Role | Email | Password |
| --- | --- | --- |
| Admin | `admin@example.test` | `demo-admin-pass` |
| Staff | `staff@example.test` | `demo-staff-pass` |

Staff see every bay's bookings by day or week, book customers in over the phone (no deposit,
email optional), move or cancel a booking (the customer is emailed, and a cancellation
refunds the deposit), block time, and move a job through in progress and completed, or mark a
no show. Online requests for services that need approval wait on **Requests** (the menu shows
how many): staff approve one, decline it, or phone the customer and propose another time, and
the customer then pays the deposit from the link in their email. Customers who don't know
what's wrong describe the problem from the services page, and it waits on **Enquiries** (the
menu shows how many are new): staff phone the customer if they need to, then book it in (a
confirmed booking with no deposit, emailed to the customer) or decline it. Admins can also invite staff, change roles, remove or restore access, send password
resets (**Team**), and read the log of every staff change (**Audit**). Invite and reset emails
land in Mailpit like the rest.

Admins also change the garage's details under **Settings**: add, edit, hide or show, and
reorder services; add and rename bays, take a bay out of use or put it back, and add bay types;
line up opening hours from a future date (tomorrow at the earliest); and edit the contact
details shown on the site and in emails. A change that would leave a booking outside the hours,
or in a bay that's out of use, is refused with those bookings listed, so staff can move or
cancel them first. The booking rules (deposit, booking window, cut-off and so on) stay in setup
data.

On a fresh database with no sample accounts (production), create the first admin. The command
prints a set-password link that works once, for 72 hours, and sends no email:

```bash
docker compose exec api python -m app.create_admin --name "Your Name" --email you@example.com
```

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

The seed fills a new, empty database from it. It only adds what's missing: it never
overwrites a value or brings back something that was removed. Once the garage is running,
admins change its services, bays, opening hours and contact details from **Settings** in the
staff pages instead.

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
uv run uvicorn --factory app.main:create_app --reload --no-access-log
```

On Windows PowerShell, set the variable with `$env:DATABASE_URL = "..."` instead of `export`.

The API and the worker log one JSON object per line: one `app.request` line per request (method, path without the query string, status, time taken, and a request id also sent back as `X-Request-ID`), and one `app.worker` line per job that did something. Read them with `docker compose logs api worker`. Uvicorn's own access log is off, so requests aren't logged twice.

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

[Playwright](https://playwright.dev/) tests book an MOT in a real browser, pay the deposit
in Stripe's form with a test card, then check the booked time is no longer offered. Flow 4 then
opens the link from the confirmation email in Mailpit, cancels, and checks the cancellation
email and that the time is free again. A made-up link must show the safe message. Flow 5 logs
in as the sample staff member, books a customer in over the phone, blocks an hour on Bay 1,
starts and completes the job, then checks the admin's audit log and removes the block. Flow 6
has staff move a paid booking (checking the "moved" email and the customer's page) and then
cancel it (checking the email and the refund). Flow 7 has the admin add a service (and see it
on the home page), hide it, be refused new hours that would close the day of a phone booking,
then add and delete future hours that clash with nothing. Flow 2 has a customer request a
diagnostic check without paying, staff approve it from the Requests page, and the customer pay
the deposit from the link in the approval email. Flow 3 has a customer send an enquiry,
staff book it in from the Enquiries page, and the customer open the confirmed booking from
the email; it needs no Stripe keys. An accessibility check runs axe (WCAG 2 A and AA) on the
main customer and staff pages and fails on any serious or critical problem. The others need
the stack running with Stripe test keys ([docs/stripe-setup.md](docs/stripe-setup.md)) and
fail at once, with a clear message, in demo mode. Start the stack first:

```bash
docker compose up --build -d --wait
cd e2e
npm ci
npx playwright install chromium
npm test
```

Each run makes real bookings in the local database, and flow 7 leaves a hidden test service
(services can't be deleted). `docker compose down -v` clears them.
Set `BASE_URL` to test another address.

In CI the `compose` job runs the same test. It reads `STRIPE_SECRET_KEY` and
`STRIPE_PUBLISHABLE_KEY` (test keys) from the repository's Actions secrets and fails if they're
missing. GitHub doesn't pass secrets to pull requests from forks or to Dependabot, so that
check fails there.

### Load test

`backend/scripts/load_availability.py` runs a small load test of the busiest public lookup,
`GET /api/availability`, against a running stack. It's run by hand, not in CI. It reads the first
service and the next open day, then has 50 simulated users ask for that day's free times over
and over for 30 seconds:

```bash
docker compose up --build -d --wait
cd backend
uv run python scripts/load_availability.py   # --base-url, --users, --seconds to change it
```

Result on 20 Nov 2026, against the local Compose stack through nginx (one API process), on an
AMD Ryzen 7 5700X3D (8 cores, 16 threads) with 32 GB RAM, Windows 10 and Docker Desktop 29.9:

```
GET /api/availability?services=mot-test&date=2026-11-21 - 50 users, 30s
requests: 2658
requests per second: 87
errors: 0
p50: 569 ms
p95: 893 ms
p99: 1188 ms
```

Each request works out a whole day's free times from the opening hours, bays, bookings and
blocks. The availability lookup has no rate limit, so these numbers aren't throttled.

## Security

- **Rate limits:** the public forms (picking a time, paying, sending a request or an enquiry,
  and cancelling from a booking link) are rate-limited per visitor IP, counted in the database.
  A visitor over the limit gets "Too many attempts". The limits are off when `ENVIRONMENT` is
  `development`, which is what the local stack runs as, so local testing never trips them.
- **Honeypot:** the details step and the enquiry form carry a hidden field. A bot that fills it
  in gets nowhere.
- **Headers:** nginx sends the security headers, including a content policy that allows only
  the site itself and Stripe ([frontend/security-headers.conf](frontend/security-headers.conf)).
- **Scans:** the CI `scan` job audits the Python and npm packages and scans the built images
  with Trivy. Allowed exceptions go in `.trivyignore`, each with its reason.

## Privacy

- **Privacy note:** `/privacy` on the public site says what's collected, why, who sees it and
  for how long. Every customer page links to it in the footer, and the booking and enquiry
  forms link to it next to the submit button.
- **12-month rule:** once a day the worker blanks the customer's details on bookings whose
  appointment ended more than 12 months ago, and on enquiries older than that which weren't
  booked in ([backend/app/privacy/retention.py](backend/app/privacy/retention.py)). The rows
  stay, so the schedule history and the audit trail stay whole: the name, phone, email and
  registration become "removed", notes are cleared, and the copies in the audit log and email
  log go too. Car make and model are kept.

## Documentation

- [Specification](docs/SPEC.md)
- [Setting up Stripe (test mode)](docs/stripe-setup.md)
- [Deploying the live demo](docs/deployment.md)
- [Implementation plans](docs/superpowers/plans/)
