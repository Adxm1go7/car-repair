# Milestone 11: deployment (live demo) — design

## Intent

Put the garage booking app online as a free, public **live demo**. The main audience is a
recruiter or another developer opening one link. They should be able to:

- book as a customer, including paying the deposit with Stripe's test card;
- log into the staff side with a shared demo login and run the schedule, enquiries and
  settings;
- see the emails the system would have sent, on a "Demo inbox" page in the site.

SPEC.md's Milestone 11: *cloud environment from the same images, environment configuration,
a seeded live demo, and a short walkthrough or recording. Done when the live demo passes the
end-to-end suite.* It must cost nothing.

## Goals

- The app runs on one free cloud server, over HTTPS, at a public address.
- Production settings everywhere it matters (Stripe required, rate limits on, secure cookie,
  HSTS), plus a **demo-site switch** that adds only what a public demo needs.
- No email ever leaves the server. Emails are kept for the Demo inbox page instead.
- The demo data goes back to the seed every night, so damage by visitors doesn't last.
- The e2e suite passes against the live site.
- README gains a "Live demo" section: link, demo logins, Stripe test card, a short
  walkthrough with a few screenshots, and how to deploy and update.

## Non-goals

- A real email provider (SMTP login/TLS). Dropped: not needed for a demo, and a public site
  that emails any typed address is an abuse risk.
- Automated deploys from CI, a container registry, or Arm image builds in CI.
- Multi-garage hosting (see the long-term direction: one DB per garage). Keep all DB access
  through `get_session` / the shared session helper, as now.
- Backups, monitoring or uptime alerts beyond what Docker's `restart:` gives.
- Live Stripe keys. The demo uses Stripe **test mode** keys.

## Anti-goals (a failure even if it works)

- Any cost, or a setup that silently starts costing money.
- The site emailing a real person.
- A visitor being able to lock everyone else out of the demo staff login until the next
  reset.
- Development shortcuts (demo payments, limits off) creeping into the live site.

## Constraints and facts from the code

- Today's stack (docker-compose.yml): `db` (postgres:17-alpine), `mailpit`, `api` and
  `worker` (one backend image), `web` (nginx serving the React build and proxying `/api`,
  fixed at 172.28.0.10; the api trusts it via `TRUSTED_PROXIES` and uvicorn's
  `ProxyHeadersMiddleware`, backend/app/main.py:82).
- The api container runs migrations and the seed on every start (backend/Dockerfile CMD).
  The seed adds the demo staff logins everywhere except production
  (backend/app/seed.py:167, `DEMO_STAFF` in backend/app/demo_data.py).
- `ENVIRONMENT=production` already demands Stripe secret, publishable and webhook keys
  (backend/app/config.py) and turns rate limits on (backend/app/limits.py).
- Emails: queued in `email_log`, rendered and sent by the worker
  (backend/app/email/outbox.py) through `SmtpSender` (backend/app/email/sender.py). **No body
  is stored**, on purpose, so booking-link tokens never touch the database.
- The e2e suite reads emails from Mailpit's API (e2e/tests/mailpit.ts) and logs in with the
  demo staff accounts (e2e/tests/staff.ts). In CI it runs with `ENVIRONMENT=development`, so
  rate limits are **off** there; on the live site they will be on.
- The session cookie is `Secure` when `PUBLIC_BASE_URL` starts with `https://`.

## Approaches considered

**Hosting.**

1. *Oracle Cloud Always Free Arm VM* (up to 2 OCPU / 12 GB since mid-2026). Runs the
   existing compose stack nearly unchanged; free with no end date. Card needed at sign-up
   for identity; "out of capacity" errors possible; idle free VMs can be reclaimed.
   **Chosen by the user.**
2. *Google Cloud e2-micro* — free, but 1 GB RAM: needs swap and images built elsewhere.
3. *Render / similar PaaS* — no free background worker, free web services sleep after
   15 minutes, free Postgres is deleted after 30 days. Rejected.

**Getting the code onto the server.**

- **A. Build on the server** (chosen): `git clone`, then
  `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`. Update =
  `git pull` + the same command. Simple, and the user can follow every step.
- B. CI builds Arm images to a registry, the server pulls. Rejected: slower CI, a registry
  and deploy keys for no real gain here. ("Same images" is read as the same Dockerfiles.)

**Where visitors see the emails.**

- A. Expose Mailpit's web UI publicly. No code, e2e unchanged, but it looks like a dev tool,
  anyone can delete mail, and it shows staff reset links (a visitor could take over the demo
  login). Rejected.
- **B. A "Demo inbox" page in the site** (chosen): in demo mode the worker stores each
  finished email instead of sending it; a read-only page shows the latest ones in the site's
  own style, without staff invite/reset emails.

## The design

### 1. Server and HTTPS

- One Oracle Always Free Arm VM (Ubuntu), Docker Engine + the compose plugin. Ports 80 and
  443 opened in both the Oracle network security list and the VM's own firewall (Oracle's
  Ubuntu images ship iptables rules that block them).
- A free **DuckDNS** name (e.g. `<name>.duckdns.org`) pointing at the VM's public IP.
  *(Claude's call: free, no domain purchase. A domain the user owns works the same way.)*
- A new **Caddy** container in front of nginx, on ports 80/443, getting a Let's Encrypt
  certificate automatically and proxying everything to `web`. Caddy sets **HSTS**
  (`max-age` of at least 6 months; no `preload`, since DuckDNS isn't ours).
- Real visitor IP: Caddy → nginx → api. Caddy gets a fixed address on the compose network;
  nginx trusts it (`set_real_ip_from` + `real_ip_header X-Forwarded-For`) so the address it
  passes on is the visitor's, and the api keeps trusting only nginx. Rate limits and the
  login lockout must count the visitor, not Caddy. nginx's `X-Forwarded-Proto` must say
  `https` to the api.
- Only Caddy publishes ports. db, api and web stop publishing theirs in the prod file.

### 2. `docker-compose.prod.yml` (override file) and `.env` on the server

- Removes mailpit from the stack (or leaves it unused; builder's call), adds Caddy, removes
  published ports except Caddy's, sets `restart: unless-stopped` on every service.
- `ENVIRONMENT=production`, `DEMO_SITE=true`, `PUBLIC_BASE_URL=https://<name>.duckdns.org`,
  a strong random `POSTGRES_PASSWORD`, Stripe **test** keys, and the Stripe webhook secret
  from a webhook endpoint registered in the Stripe test dashboard for
  `https://<name>.duckdns.org/api/stripe/webhook` (or wherever the route lives).
- A `.env.production.example` with placeholders only, documenting every variable.
  The real `.env` lives only on the server.

### 3. The demo-site switch (`DEMO_SITE`)

A new config flag, default off; allowed with any environment, but meant for production.
When on:

- **Demo logins:** the seed adds `DEMO_STAFF` even in production.
- **Email:** the worker uses a new `DemoInboxSender` instead of `SmtpSender`: it stores the
  rendered email (recipient, subject, text, html, template, sent time) in a new
  `demo_inbox` table, and never opens an SMTP connection. The `email_log` row is marked
  sent as usual.
  - This deliberately stores booking-link tokens in the database, only in demo mode; the
    inbox is the only way a visitor can use "manage my booking". Note it in the code and in
    the privacy note.
  - Staff emails (`staff_invite`, `password_reset`) are stored but **never shown** on the
    page or returned by its API.
- **Demo inbox page:** a public, read-only customer-site page (e.g. `/demo-inbox`) listing
  the latest emails, newest first (a sensible cap, e.g. 50), each openable to show the
  email. A public API endpoint feeds it. Only exists with `DEMO_SITE` on (404 otherwise).
  - **One shared inbox (user's decision):** every visitor sees every customer email,
    including recipients and working "manage my booking" links. Accepted: the nightly reset
    clears it. The page, and the booking and enquiry forms in demo mode, say plainly:
    "Everyone can see this inbox. Don't use real names, emails or car details."
  - The API can filter by recipient (and the e2e helper can match by subject on the
    results), so the e2e helper can look emails up from a plain Playwright request context
    with no cookie.
- **Demo banner:** a small notice on every page: "This is a demo. Pay with Stripe's test
  card 4242 4242 4242 4242. Emails appear in the Demo inbox. Everything resets nightly."
  The staff login page shows the demo logins.
- **Protect the shared logins:** the two demo accounts can't have their password changed or
  reset, be deactivated, or have their role or email changed. The api refuses with a clear
  message; the UI may hide those buttons. Other staff the visitor invites behave normally.
  - The per-email login lockout (backend/app/staff/throttle.py, 10 failures → 15 minutes)
    doesn't apply to the two demo accounts in demo mode, since their emails are public and
    anyone could keep them locked. Any per-IP protection stays. *(Claude's call.)*
- **Everything else the admin can do stays allowed (user's decision),** including editing
  the garage contact details, services, hours, bays and deposits, and cancelling bookings.
  The risk of defacement for up to a day is accepted. The nightly reset puts it back.
- **Nightly reset:** at a fixed time each night (03:00 Europe/London; Claude's call), the
  worker empties every data table and runs the seed again, in one transaction, under the
  same lock the settings code uses so no booking is half-written. A
  `python -m app.demo_reset` command does the same on demand (used after an e2e run).
  Without `DEMO_SITE` the job and the command refuse to run.
  - *(Claude's calls)* `alembic_version` is kept. ID sequences are **not** restarted, so a
    late Stripe webhook for a wiped booking can't match a new row with the same ID. The
    webhook must ignore sessions it doesn't know (check it already does, and add a test).
    Open Stripe test sessions are left to expire by themselves.

Everything else stays production: Stripe required, rate limits on, demo payments off.

### 4. End-to-end suite against the live site

- `BASE_URL=https://<name>.duckdns.org npm test` from the user's machine.
- The email helper (e2e/tests/mailpit.ts) reads from the Demo inbox API when the target is
  the demo site (an env var such as `INBOX=demo`, or detected), and from Mailpit otherwise.
  Same function signature, so the specs don't change. CI keeps using Mailpit.
- Rate limits are on there. The builder must count how many holds/payments/requests/
  enquiries one full run makes from one IP against `LIMITS` (backend/app/limits.py). If a
  run would trip them, prefer running the suite in two halves over loosening production
  limits; don't add a bypass.
- Run `app.demo_reset` after the e2e run, since some flows change settings. The guide says
  to do both at a quiet time, because a visitor mid-booking would lose it. *(Claude's
  call.)*
- CI also gains a small job/step proving the demo switch works locally (seed adds logins,
  inbox stores instead of sending), via backend tests; the live run itself stays manual.

### 5. Docs

- README "Live demo": the link, demo logins, test card, "emails are in the Demo inbox",
  nightly reset, and a short walkthrough (customer booking → inbox → staff schedule →
  move the booking → the "moved" email) with 4–6 screenshots taken from the live site.
- `docs/deployment.md`: step-by-step server setup (Oracle account, VM, firewall, DuckDNS,
  Docker, clone, `.env`, Stripe webhook, first start, update, reset, logs), written so the
  user runs each command themselves.
- SPEC.md: answer the "which free tier" open question (Oracle Always Free), change the email
  row (no provider for the demo: Demo inbox), tick "HTTPS in the deployed environment" with
  evidence, and mark Milestone 11 done once the live e2e run passes.

## Left to the builder

- Exact table/column names, the API path and JSON shape of the inbox.
- How the inbox page looks, within the existing customer-site style.
- Caddy image version and Caddyfile details; how Caddy's fixed IP is set.
- Whether mailpit is removed by the override or simply unused.
- Exact reset mechanics (TRUNCATE … RESTART IDENTITY CASCADE vs deletes), as long as it is
  one transaction, takes the settings lock and re-runs the normal seed.
- Test coverage for the new backend and frontend pieces, in the project's usual style.

## Idle reclaim (user's decision)

The account stays on Oracle's Free Tier, so nothing can ever cost money. If Oracle reclaims
the VM as idle, the demo is rebuilt from docs/deployment.md, which therefore has to work as
a from-scratch rebuild guide (about half an hour). No keep-alive workload, and no
Pay-As-You-Go upgrade.
