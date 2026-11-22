# Milestone 11: Deployment (live demo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the app online as a free, public live demo on an Oracle Always Free VM, over HTTPS, with a demo-site switch (demo logins, a shared in-site Demo inbox instead of sending email, protected shared logins, nightly reset), and pass the e2e suite against it.

**Architecture:** A `DEMO_SITE` config flag turns on the demo-only behaviour inside the existing backend and frontend. Everything else stays `ENVIRONMENT=production`. Deployment is the existing compose file plus a `docker-compose.prod.yml` override that adds Caddy (HTTPS, HSTS) in front of nginx. The images are built on the server.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + Postgres 17, React + Vite + Vitest, nginx, Caddy 2, Docker Compose, Playwright.

**Spec:** docs/superpowers/specs/2026-11-21-milestone-11-deployment-design.md

## Global Constraints

- It must cost nothing. Oracle Free Tier only, no Pay-As-You-Go, a free DuckDNS name, Stripe **test** keys.
- No email ever leaves the server when `DEMO_SITE` is on. The worker never opens an SMTP connection.
- `DEMO_SITE` defaults to off. With it off, behaviour is exactly as today: no inbox routes, no reset, no demo logins in production.
- Production stays production: Stripe keys required, rate limits on, no demo payments. No rate-limit bypass for e2e.
- One shared public inbox. It shows customer emails only. `staff_invite` and `password_reset` are stored but never returned.
- Warning copy, verbatim: "Everyone can see this inbox. Don't use real names, emails or car details."
- Banner copy, verbatim: "This is a demo. Pay with Stripe's test card 4242 4242 4242 4242. Emails appear in the Demo inbox. Everything resets nightly."
- Nightly reset at 03:00 Europe/London. One transaction. Takes `lock_exclusive`, keeps `alembic_version`, does **not** restart ID sequences, then re-runs `seed(..., sample_accounts=True)`.
- All DB access goes through sessions from `make_engine` / `get_session`, as now (multi-garage direction). No `garage_id`, and no hard-coded garage text in the frontend.
- Commits are named "area - what": one short title, no body, no AI attribution.
- Backend tests: `cd backend; uv run pytest`, plus `uv run ruff check .` and `uv run mypy .`. Frontend: run `npm test` and `npm run lint` from **PowerShell** (`e:\...` paths). e2e: `docker compose up --build -d --wait` and then `cd e2e; npm test`.

## Review Focus

1. **Visitor IP behind Caddy:** a request with a forged `X-Forwarded-For: 1.2.3.4` sent to Caddy must still be counted under the visitor's real address. Pinned in Task 8 (a curl check in the guide, and `docker compose logs api` showing the address).
2. **Inbox with `DEMO_SITE` off:** `/api/demo-inbox` must be 404, and the worker must send by SMTP. Pinned in Task 3 (`test_inbox_is_404_when_off`) and Task 2 (`test_worker_uses_smtp_when_off`).
3. **A failed send in demo mode:** if the outbox rolls back, no inbox row may be left behind. The inbox row is written in the same session as the `email_log` update. Pinned in Task 2 (`test_inbox_row_rolls_back_with_failure`).
4. **A late Stripe webhook after a reset** must be ignored with a 200, not a 500, and not attached to a new row. Pinned in Task 5 (`test_webhook_for_wiped_session_is_ignored`).
5. **The reset racing a booking:** the reset waits on `lock_exclusive`, so a booking being made isn't half-wiped. Pinned in Task 5 (`test_reset_takes_exclusive_lock`).

---

### Task 1: The `DEMO_SITE` switch, demo logins, and `demo_site` on `/api/garage`

**Files:**
- Modify: `backend/app/config.py` (add the field)
- Modify: `backend/app/seed.py:167` (`main()`)
- Modify: `backend/app/api/catalogue.py` (`GarageOut`, `garage()`)
- Modify: `frontend/src/catalogue/types.ts` (`Garage`)
- Test: `backend/tests/unit/test_config.py`, `backend/tests/integration/test_seed.py`, `backend/tests/integration/test_catalogue_api.py`

**Interfaces:**
- Produces: `AppConfig.demo_site: bool = False` (env `DEMO_SITE`).
- Produces: `sample_accounts_wanted(config: AppConfig) -> bool` in `app/seed.py`. It returns `config.environment != "production" or config.demo_site`.
- Produces: `GET /api/garage` gains `"demo_site": bool`. The frontend `Garage` type gains `demo_site: boolean`.

- [ ] **Step 1: Write the failing tests**
  - `test_config.py::test_demo_site_defaults_off`: `AppConfig(database_url="x").demo_site is False`.
  - `test_seed.py::test_sample_accounts_wanted`:
    - production + `demo_site=False` → False;
    - production + `demo_site=True` → True;
    - development → True.
  - `test_catalogue_api.py::test_garage_says_whether_demo_site`: through `client_for(AppConfig(..., demo_site=True))`, `/api/garage` returns `demo_site == True`. With the default `api_client` it returns False.
- [ ] **Step 2: Run them and see them fail:** `uv run pytest tests/unit/test_config.py tests/integration/test_seed.py tests/integration/test_catalogue_api.py -k "demo_site or sample_accounts"`.
- [ ] **Step 3: Implement**
  - Add the field and `sample_accounts_wanted`, and use it in `seed.main()`.
  - `garage()` takes `request: Request` and reads `request.app.state.config.demo_site`.
  - Update the seed docstring ("never in production" becomes "only in production when `DEMO_SITE` is on").
  - Add `demo_site` to the frontend `Garage` type and to every test fixture that builds a `Garage`. Run `npm run build` to find them.
- [ ] **Step 4: Run the backend suite, ruff, mypy, and the frontend tests (PowerShell).** All pass.
- [ ] **Step 5: Commit** `backend - demo site switch and demo logins`

### Task 2: The worker stores emails in `demo_inbox` instead of sending them

**Files:**
- Create: `backend/migrations/versions/0014_demo_inbox.py`
- Create: `backend/app/models/demo_inbox.py` (export it from `app/models/__init__.py`)
- Modify: `backend/app/email/sender.py` (add `DemoInboxSender`)
- Modify: `backend/app/email/outbox.py` (`send_due_emails` passes the template)
- Modify: `backend/app/worker.py` (`send_emails` picks the sender per run)
- Test: `backend/tests/integration/test_demo_inbox_sender.py`, `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Produces the table `demo_inbox`:
  - `id` serial primary key;
  - `template` String(30) not null;
  - `recipient` String(254);
  - `subject` String(300);
  - `text` Text;
  - `html` Text;
  - `sent_at` timestamptz not null default now();
  - index on `(recipient, id)`.
- Produces the model `DemoInboxEmail` with the same columns. Its module docstring says: "Demo site only: stores booking-link tokens on purpose; the inbox is how visitors use their links."
- Produces `OutgoingEmail.template: str`. Add the field, and fill it in `render_email`, `render_enquiry_email` and `render_staff_email`.
- Produces `class DemoInboxSender: __init__(self, session: Session)`, with `send(message: OutgoingEmail) -> None`. It adds a `DemoInboxEmail` to the session and **never commits** (the outbox's commit covers it).
- Produces `make_sender(config: AppConfig, session: Session) -> EmailSender` in `app/worker.py`. It returns `DemoInboxSender(session)` when `config.demo_site`, else `SmtpSender(...)`.
- Produces `send_emails(engine: Engine, config: AppConfig) -> int`.

- [ ] **Step 1: Write the failing tests** in `test_demo_inbox_sender.py`. Reuse the helpers from `test_outbox.py` (move `confirmed` and `queued` into `factories.py` if needed).
  - `test_demo_sender_stores_the_email`: queue a confirmation, run `send_due_emails(session, DemoInboxSender(session), now, "https://demo.test")`. Then exactly one `DemoInboxEmail` exists, with `template == "confirmation"`, the right recipient, a subject, and `"https://demo.test/booking/"` in its text. The `email_log` row is `sent`.
  - `test_inbox_row_rolls_back_with_failure`: a sender subclass that stores and then raises `EmailUnavailable` leaves zero `DemoInboxEmail` rows, and the email is still `queued` with `attempts == 1`.
  - `test_worker_uses_smtp_when_off` / `test_worker_uses_inbox_when_on`: check the type that `make_sender` returns.
  - Migrations: extend the existing upgrade/downgrade round-trip test so it covers `0014`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the migration (revision `"0014"`, down `"0013"`), the model, the `template` field, `DemoInboxSender`, `make_sender`, and the worker change. Tests that build `OutgoingEmail` directly need the new field. The worker's start log line also says `emails: demo inbox` or `emails: smtp`.
- [ ] **Step 4: Run the backend suite, ruff and mypy.** All pass.
- [ ] **Step 5: Commit** `backend - demo inbox stores emails instead of sending`

### Task 3: Demo inbox API

**Files:**
- Create: `backend/app/api/demo_inbox.py`
- Modify: `backend/app/main.py` (include the router only when `config.demo_site`)
- Test: `backend/tests/integration/test_demo_inbox_api.py`

**Interfaces:**
- Consumes: `DemoInboxEmail` (Task 2).
- Produces: `GET /api/demo-inbox?to=<email>` returns `list[InboxSummaryOut]` with `{id: int, to: str, subject: str, sent_at: datetime}`.
  - Newest first, at most 50.
  - `to` is optional, and matches case-insensitively after `normalise`, like `clean_email`.
  - It never includes templates in `STAFF_TEMPLATES = ("staff_invite", "password_reset")`.
- Produces: `GET /api/demo-inbox/{id}` returns `InboxEmailOut` with `{id, to, subject, sent_at, text, html}`. A staff template or an unknown id returns 404 `"No such email"`.
- Both are public (no login) and use `ResourceId` for the path.

- [ ] **Step 1: Write the failing tests:**
  - `test_inbox_is_404_when_off`: the default `api_client` gets 404 on both routes.
  - `test_lists_newest_first_and_caps_at_50`: insert 51 rows, get 50, and the first is the highest id.
  - `test_filters_by_recipient`: `?to=Ann@Example.com` returns only Ann's.
  - `test_staff_emails_never_shown`: a `password_reset` row is missing from the list, and its id returns 404.
  - `test_reads_one_email`: returns text and html.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the router and include it in `create_app` behind `if config.demo_site:`.
- [ ] **Step 4: Run the backend suite, ruff and mypy.** All pass.
- [ ] **Step 5: Commit** `backend - demo inbox api`

### Task 4: Protect the shared demo logins

**Files:**
- Create: `backend/app/staff/demo_accounts.py`
- Modify: `backend/app/staff/throttle.py` (`is_locked`), `backend/app/api/staff_auth.py` (`login`, `forgot_password`), `backend/app/api/staff_team.py` (`update`, `reset_password`)
- Test: `backend/tests/integration/test_demo_accounts.py`

**Interfaces:**
- Produces `is_demo_account(config: AppConfig, email: str) -> bool`. It's True only when `config.demo_site` and the normalised email is in `{s.email for s in DEMO_STAFF}`.
- Produces `DEMO_ACCOUNT_LOCKED: Final = "The demo logins can't be changed"`.
- `is_locked(session, email, ip, now, *, skip_email_limit: bool = False) -> bool`. With `skip_email_limit`, only `IP_LIMIT` applies.
- On a demo account (demo site on):
  - `login` calls `is_locked` with `skip_email_limit=True`;
  - `forgot_password` still replies `LINK_SENT` but queues nothing;
  - `PATCH /staff/team/{id}` (role or active) returns 409 with `DEMO_ACCOUNT_LOCKED`;
  - `POST /staff/team/{id}/reset-password` returns 409 with `DEMO_ACCOUNT_LOCKED`.
  Other accounts are unchanged.

- [ ] **Step 1: Write the failing tests** (`client_for(AppConfig(..., demo_site=True))`, seeding `DEMO_STAFF` via `seed(session, sample_accounts=True)`):
  - `test_demo_login_not_locked_by_wrong_passwords`: 10 wrong passwords for `admin@example.test` from varied IPs, then the right one gives 200.
  - `test_demo_login_still_ip_limited`: 20 failures from one IP, then the right password gives 401.
  - `test_forgot_password_queues_nothing_for_demo_account`.
  - `test_admin_cannot_change_demo_accounts`: a PATCH of role, a PATCH of `active=false`, and a reset-password each give 409 with the message, and nothing in the DB changes.
  - `test_invited_staff_behave_normally`.
  - `test_demo_accounts_normal_when_off`: with `demo_site` False, the email lockout applies to `admin@example.test`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** The team routes get the config from `request.app.state.config`.
- [ ] **Step 4: Run the backend suite, ruff and mypy.** All pass.
- [ ] **Step 5: Commit** `backend - protect the shared demo logins`

### Task 5: Nightly reset

**Files:**
- Create: `backend/app/demo/__init__.py`, `backend/app/demo/reset.py`, `backend/app/demo_reset.py` (the `python -m app.demo_reset` entry point)
- Modify: `backend/app/worker.py` (add a `"demo_reset"` job when `config.demo_site`)
- Test: `backend/tests/integration/test_demo_reset.py`, `backend/tests/unit/test_reset_due.py`, `backend/tests/integration/test_stripe_webhook*.py` (the existing webhook test file)

**Interfaces:**
- Produces `reset_demo(session: Session) -> None`. It does `lock_exclusive(session)`, then one `TRUNCATE <every table in Base.metadata.sorted_tables> CONTINUE IDENTITY CASCADE`. That keeps `alembic_version`, since it isn't in the metadata. Then `seed(session, sample_accounts=True)`. The caller commits.
- Produces `RESET_AT: Final = time(3, 0)` and `reset_due(last_reset: datetime | None, now: datetime, zone: ZoneInfo) -> bool`. It's True when the most recent 03:00 in `zone` at or before `now` is after `last_reset`. When `last_reset` is None, it's True only if `now` is within 10 minutes after 03:00, so a worker restart at noon doesn't wipe the demo.
- The worker keeps `last_reset` in memory, checks once per loop, and logs `job finished` with `job="demo_reset"`.
- `python -m app.demo_reset`:
  - refuses with exit code 1 and the message `"DEMO_SITE is off: refusing to reset"` unless `config.demo_site`;
  - otherwise resets, commits and prints `"Demo reset complete"`.

- [ ] **Step 1: Write the failing tests**
  - `test_reset_due` cases (zone Europe/London):
    - last None at 03:05 → True;
    - last None at 12:00 → False;
    - last yesterday 03:00, now 03:00 today → True;
    - last today 03:00, now 23:00 → False;
    - one case on the clock-change night (2026-03-29 and 2026-10-25).
  - `test_reset_wipes_bookings_and_reseeds`:
    - make a booking, an enquiry, an inbox row and an invited staff member, then change `garage_contact`;
    - after `reset_demo` and a commit, all are gone, the settings equal `DEFAULT_SETTINGS`, the `DEMO_STAFF` logins exist, and the catalogue counts equal `DEMO_COUNTS`.
  - `test_reset_keeps_ids_running`: a booking id made after the reset is greater than one made before.
  - `test_reset_keeps_alembic_version`.
  - `test_reset_takes_exclusive_lock`: hold `lock_shared` in a second connection, then run `reset_demo` in a thread with `SET lock_timeout = '1s'`. It raises, and the data is still there.
  - `test_demo_reset_command_refuses_when_off`.
  - `test_webhook_for_wiped_session_is_ignored`: a signed `checkout.session.completed` for an unknown session id returns 200 and creates no rows. If this already passes, keep it as a regression test.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the backend suite, ruff and mypy.** All pass.
- [ ] **Step 5: Commit** `backend - nightly demo reset`

### Task 6: Frontend: demo banner, demo logins, form warnings, Demo inbox page

**Files:**
- Create: `frontend/src/demo/DemoBanner.tsx`, `frontend/src/demo/DemoInboxPage.tsx`, `frontend/src/demo/api.ts`, `frontend/src/demo/linkify.ts` (+ a `.test.ts(x)` for each)
- Modify:
  - `frontend/src/App.tsx`: the banner above the customer `<Routes>`, a `/demo-inbox` route only when `garage.demo_site`, and an inbox link in `CustomerFooter` when on;
  - `frontend/src/staff/StaffLayout.tsx` and `LoginPage.tsx`: the banner, and on the login page the two logins `admin@example.test` / `demo-admin-pass` and `staff@example.test` / `demo-staff-pass`;
  - the booking details form and `EnquiryPage`: the warning copy when `demo_site`.

**Interfaces:**
- Consumes: `/api/garage` `demo_site` (Task 1), and `/api/demo-inbox` plus `/api/demo-inbox/{id}` (Task 3).
- Produces `linkify(text: string, origin: string): (string | { href: string; label: string })[]`. It turns only URLs that start with `origin` into links. Anything else stays text.
- The `DemoInboxPage`:
  - lists the emails (subject, to, sent time in the garage zone) and shows the warning copy at the top;
  - opening one shows the subject and the **text** body in a `<pre>`, with `linkify(text, window.location.origin)`;
  - the HTML body is never injected;
  - an empty list says "No emails yet. Book something and its emails will appear here.";
  - a load failure shows the usual alert style.

- [ ] **Step 1: Write the failing tests:**
  - `linkify` keeps foreign URLs as text, and links site URLs including the `#t=` fragment;
  - the banner renders the exact copy;
  - `DemoInboxPage` covers the list, open-one, empty and error states with mocked fetch;
  - the `App` route is absent when `demo_site` is false;
  - the login page shows the demo logins only when `demo_site`;
  - the booking form shows the warning only when `demo_site`.
- [ ] **Step 2: Run them and see them fail** (PowerShell: `cd e:\WORK_FOLDER_OF_FOLDERS\car-repair\frontend; npm test`).
- [ ] **Step 3: Implement**, in the existing CSS style, using CSS variables only. Staff pages fetch `demo_site` through the existing `StaffContext` garage fetch.
- [ ] **Step 4: Run** `npm test`, `npm run lint` and `npm run build`. All pass. Then add `/demo-inbox` to the pages in `e2e/tests/accessibility.spec.ts` when the target has `demo_site` on (skip it otherwise).
- [ ] **Step 5: Commit** `frontend - demo banner, logins and inbox page`

### Task 7: e2e reads the Demo inbox on the live site

**Files:**
- Modify: `e2e/tests/mailpit.ts` (keep the file name and the `waitForEmail` signature)
- Modify: `docker-compose.yml` (`DEMO_SITE: ${DEMO_SITE:-false}` on `api` and `worker`)

**Interfaces:**
- Behaviour: `waitForEmail(request, to, subject, timeoutMs)`:
  - when `process.env.INBOX === 'demo'`, it polls `${BASE_URL}/api/demo-inbox?to=` and finds by subject, then GETs `/api/demo-inbox/{id}` and returns `{ text, html }`;
  - otherwise it uses Mailpit as now.
- No new script and no new dependency. In PowerShell, the live run is `$env:INBOX='demo'; npm test`.

- [ ] **Step 1: Locally, run the stack with `DEMO_SITE=true` and `ENVIRONMENT=development`, then run the suite with `INBOX=demo`.** Expect failures until the helper is changed.
- [ ] **Step 2: Implement the helper.**
- [ ] **Step 3: Run `INBOX=demo npm test` against the demo-on stack, then the normal `npm test` against a default stack.** Both pass (11/11 or more).
- [ ] **Step 4: Commit** `e2e - read emails from the demo inbox`

### Task 8: Production compose, Caddy and the nginx proxy headers

**Files:**
- Create: `docker-compose.prod.yml`, `Caddyfile`, `.env.production.example`
- Modify: `frontend/nginx.conf`, `.github/workflows/ci.yml` (one step in the compose job)

**Interfaces / decisions:**
- `Caddyfile`:
  - `{$SITE_ADDRESS}` → `reverse_proxy web:80`;
  - `header Strict-Transport-Security "max-age=31536000"`, with no `includeSubDomains` and no `preload`;
  - `encode gzip`.
- `docker-compose.prod.yml`:
  - adds `caddy` (pin `caddy:2.10-alpine` or the newest 2.x tag that is at least 2 weeks old), with ports `80:80`, `443:443`, `443:443/udp`, volumes `caddy_data` and `caddy_config`, `SITE_ADDRESS` from the env, and a fixed address of `172.28.0.11`;
  - uses `ports: !reset []` on `db`, `api`, `web` and `mailpit`;
  - puts mailpit behind `profiles: ["local"]` so it doesn't start;
  - sets `restart: unless-stopped` everywhere;
  - adds `DEMO_SITE` and the other variables from `.env`.
- `frontend/nginx.conf`:
  - `set_real_ip_from 172.28.0.11; real_ip_header X-Forwarded-For;`, which is harmless locally, since 172.28.0.11 is outside `ip_range` and no other container gets it;
  - `proxy_set_header X-Forwarded-For $remote_addr;`;
  - a `map` that passes on `X-Forwarded-Proto: https` from Caddy and falls back to `$scheme` otherwise.
- `.env.production.example` contains placeholders only: `POSTGRES_PASSWORD`, `ENVIRONMENT=production`, `DEMO_SITE=true`, `SITE_ADDRESS`, `PUBLIC_BASE_URL`, `SMTP_FROM`, and the three Stripe keys. Each has a comment, and nothing real goes in.
- CI: `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production.example config -q` must pass.

- [ ] **Step 1: Write the files.**
- [ ] **Step 2: Run** `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production.example config -q`. It exits 0.
- [ ] **Step 3: Local smoke test:**
  - put `SITE_ADDRESS=localhost` in a scratch env file, with Stripe test keys copied from the local `.env`, then run `up --build -d --wait`;
  - `curl -k -sI https://localhost/` shows `strict-transport-security`;
  - `curl -k -s https://localhost/api/health` is ok;
  - `curl -k -H "X-Forwarded-For: 1.2.3.4" https://localhost/api/garage`, then `docker compose logs api` shows the request logged from the docker gateway address, **not** 1.2.3.4.
  - Then `down`.
- [ ] **Step 4: Check that the normal stack's e2e still passes** (`docker compose up --build -d --wait; cd e2e; npm test`), since nginx.conf changed.
- [ ] **Step 5: Commit** `deploy - production compose with caddy https`

### Task 9: Docs: deployment guide, README live demo, SPEC

**Files:**
- Create: `docs/deployment.md`
- Modify: `README.md`, `docs/SPEC.md`, `frontend/src/PrivacyPage.tsx` (+ its test)

- [ ] **Step 1: `docs/deployment.md`**, one command per step, written for the user to run themselves, and working as a from-scratch rebuild guide:
  1. **Oracle account:** Free Tier, and don't upgrade it.
  2. **The VM:** VM.Standard.A1.Flex with 2 OCPU / 12 GB on Ubuntu 24.04. What to do on "out of capacity" (another availability domain, or retry later). Save the SSH key.
  3. **Firewall:** the security list ingress for 80, 443 and 443/udp, plus the VM's own iptables rules (`sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT` etc., then `sudo netfilter-persistent save`).
  4. **DuckDNS:** create the name and point it at the public IP.
  5. **Docker:** install Docker Engine and the compose plugin.
  6. **The code:** `git clone`, then `cp .env.production.example .env` and fill it in (generate the password with `openssl rand -base64 32`).
  7. **Stripe:** register the test-mode webhook endpoint at `https://<name>.duckdns.org/api/stripe/webhook` with the events the handler uses (`checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.expired`, `refund.created`, `refund.updated`, `charge.refund.updated`), and copy the signing secret into `.env`.
  8. **First start:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait`.
  9. **Check it:** health, HSTS, the forged X-Forwarded-For check from Task 8, and the worker log saying `emails: demo inbox`.
  10. **Update:** `git pull` and the same `up` command.
  11. **Reset now:** `docker compose ... exec api python -m app.demo_reset`.
  12. **Logs:** `docker compose ... logs -f api worker`.
  13. **Live e2e:** at a quiet time, run `$env:BASE_URL='https://…'; $env:INBOX='demo'; npm test`, then reset. If a run trips a rate limit (429), run the spec files in two halves 15 minutes apart. Never loosen the limits.
  14. **If Oracle reclaims the VM:** start again from step 2.
- [ ] **Step 2: README** gains a "Live demo" section:
  - the link (a placeholder until Task 10);
  - the demo logins and the test card;
  - "emails appear in the Demo inbox; everyone can see it";
  - the nightly reset;
  - a 5-step walkthrough: book → open the inbox → log in as staff → move the booking → see the "moved" email;
  - image slots `docs/images/demo-*.png`, filled in Task 10;
  - a pointer to `docs/deployment.md`.
- [ ] **Step 3: SPEC.md:**
  - answer "which free tier" (Oracle Cloud Always Free Arm VM, built on the server, Caddy for HTTPS);
  - change the Email row in the tools table to "a mail catcher locally; on the live demo, a Demo inbox page (nothing is sent)";
  - leave the HTTPS tick and "M11 done" for Task 10.
- [ ] **Step 4: Privacy note:** add one line saying that on the live demo, emails are kept in a public Demo inbox and everything is wiped nightly. Extend `PrivacyPage.test.tsx` to check for it when `demo_site` is on.
- [ ] **Step 5: Run the frontend tests, lint and build** (PowerShell). Commit `docs - deployment guide and live demo`.

### Task 10: Go live (the user runs each step, Claude guides)

No new code. Do this one step at a time with the user, following `docs/deployment.md`. Fix the guide wherever reality differs, and commit those fixes as `docs - deployment guide fixes`.

- [ ] **Step 1:** Work through the guide's steps 1–9 until `https://<name>.duckdns.org` serves the site with HSTS and the worker says `emails: demo inbox`.
- [ ] **Step 2: Manual check:** a booking with the 4242 card confirms, its email shows in the inbox, its manage link works, the staff login works, and a move shows a "moved" email. Also open the site once in Firefox and check the console for CSP errors on the payment step (the open note from M10a). Safari only if the user has it.
- [ ] **Step 3: Live e2e:** run `npm test` against the live site with `INBOX=demo` (guide step 13). It passes. Then run `app.demo_reset`.
- [ ] **Step 4: Screenshots:** take 4–6 with Playwright or by hand, save them under `docs/images/`, fill in the README slots and the live link.
- [ ] **Step 5: SPEC.md:**
  - tick "HTTPS in the deployed environment", with evidence: the Caddyfile HSTS line, the guide's check step, and the passing live e2e run's date;
  - mark Milestone 11 done with the date.
- [ ] **Step 6: Commit** `docs - live demo is up`. Then stop: the user pushes and opens the PR.
