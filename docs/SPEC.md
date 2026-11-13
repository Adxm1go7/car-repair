# Garage Booking System: Project Specification

Oct 27, 2026 · @Adam Ornoch

## Overview and goals

This is a booking system for one small-to-medium car garage: a public website where customers see priced services and book or enquire, and a back office where staff run the schedule. It is also a portfolio piece, so it must work end to end and be built to professional standards.

**Goals**

- Let customers book fixed-duration services instantly, with no account.
- Send diagnosis and unknown-issue jobs to staff for approval.
- Give staff one editable schedule: bookings, blocked time, opening hours, bays.
- Prevent double-booking by design, enforced in the database as well as in code.
- Show engineering practice: tests at every level, CI, Docker, clear documentation.
- Stay extendable to several garages later, without building that now.

**Non-goals for v1**

- Customer accounts, SMS, quotes and invoices, parts and stock, service history, per-mechanic calendars, multi-garage support.
- Real payments. The deposit runs in Stripe test mode.
- Any spend: every tool and hosting choice must have a free option.

## Decisions log

These decisions are settled. Rows marked *proposed* are my defaults that you accepted in principle; change any of them and the plan adjusts.

| Area | Decision |
| --- | --- |
| Audience | One garage, built as a demo and CV project; selling to other garages is a possible later step. |
| Customers | No accounts. Guest booking with name, phone and email. A private token link in each email lets them view, cancel or reschedule. |
| Staff | Two roles, admin and staff. Everyone sees one shared schedule. |
| Scheduling | Bays only, no per-mechanic calendars. Bays have types (for example MOT ramp, general bay); the detail comes later. |
| Opening hours | Open all week, shorter hours on Saturday and Sunday. *Proposed*: Mon to Fri 08:00 to 17:30, Sat 09:00 to 14:00, Sun 10:00 to 13:00, all editable by the admin. |
| Services | Public prices, fixed or a range. Each has a duration, a required bay type, and an instant or needs-approval flag. |
| Multi-service visits | Allowed. If any selected service needs approval, the whole booking goes to staff. |
| Unknown issues | A separate enquiry flow with structured fields, notes and photos. Staff approve, decline or ask for more information. |
| Deposit | Flat £20 per booking in Stripe test mode, balance paid in person. Refundable when cancelled 24 hours or more ahead. For approval bookings it is requested after approval. |
| Notifications | Email only in v1: confirmation, reminder, cancellation, reschedule, "car ready". SMS can be added later behind the same interface. |
| Garage-initiated changes | If staff cancel or move a booking, the system emails the customer, refunds the deposit and offers a new slot. |
| Policy settings | *Proposed*: booking window 60 days, cut-off 2 hours before a slot, slot hold 5 minutes (shortened from 10 in Milestone 4), free cancellation 24 hours. All stored as settings, not hardcoded. |
| Stack | Python with FastAPI, React with TypeScript, PostgreSQL, Docker Compose, GitHub Actions. |
| Photos | Enquiry photo uploads, stored in S3-compatible object storage. |
| Staff interface | Responsive, usable on a phone or tablet in the workshop. |
| Hosting | Run locally with Docker Compose first, then deploy to a free cloud tier without redesign. |
| Quality bar | Tests at unit, integration, concurrency and end-to-end level, run in CI. Availability engine built test-first. |
| Branding and sample data | Deferred until you ask for them. |

## Users and roles

There are three kinds of user, and only two of them log in.

| Role | Logs in? | Can do |
| --- | --- | --- |
| Customer | No | Browse services, book, send an enquiry, and use their emailed token link to view, cancel or reschedule one booking. |
| Staff | Yes | See the shared schedule, confirm or decline pending bookings and enquiries, move or cancel bookings, block time, mark a job in progress, complete, or "car ready". |
| Admin | Yes | Everything staff can do, plus edit services, prices, bays, opening hours, policy settings, and staff accounts. |

Every staff endpoint checks the role on the server. Hiding a button in the interface is never the only protection.

## Features and scope

Version 1 is the complete demonstration. Everything in the second list is deliberately left out and should not creep in.

**In v1**

- Public site: services page with prices, booking flow, issue-enquiry form, contact details.
- Booking: pick one or more services, enter car details (registration, make, model, notes), choose an open slot, pay the deposit, receive a confirmation email.
- Enquiry: structured fields (registration, make and model, symptoms, urgency), free-text notes and photo upload, with a staff approval queue.
- Token self-service: view, cancel or reschedule from an emailed link, within the policy window.
- Back office: login, shared day and week schedule, booking and enquiry management, blocked time, service and price editing, opening hours, settings, "car ready" button.
- Emails: confirmation, reminder, cancellation, reschedule, garage-initiated change, car ready.
- Operations: audit log of staff changes, seed data for a realistic demo garage, one-command local startup.

**Later, not v1**

- SMS, customer accounts, service history per car, MOT and service reminders, quotes and invoices, parts and stock, per-mechanic scheduling, multi-garage support.

## Core user flows

Six flows cover the whole product. Each should become at least one end-to-end test.

**1. Instant booking (all selected services are instant)**

1. The customer selects one or more services. The system sums their durations and finds a bay type that can take them.
2. The customer sees open slots that fit the total duration and picks one.
3. The slot is held for 5 minutes while the customer enters name, phone, email and car details and pays the £20 deposit.
4. On payment success the booking becomes confirmed and a confirmation email with a token link is sent.
5. If the hold expires before payment, the slot is released and the customer is told.

**2. Booking that needs approval (any selected service is needs-approval)**

1. Steps 1 to 3 as above, but the customer does not pay yet.
2. The booking is saved as pending, with the slot held for a longer, configurable period, and appears in the staff queue.
3. Staff approve, propose another time, or decline. Each outcome sends an email.
4. On approval the customer receives a payment link for the deposit. Payment confirms the booking.

**3. Diagnosis enquiry (unknown issue)**

1. The customer fills in the structured form (registration, make and model, symptoms, urgency), adds notes and optional photos.
2. The enquiry appears in the staff queue as new.
3. Staff reply by email to approve and offer a slot, ask for more information, or decline. An approved enquiry converts into a pending booking.

**4. Customer self-service through the token link**

1. The email link opens that one booking, with no login.
2. The customer can cancel or reschedule while inside the policy window. The deposit is refunded or forfeited by the rule in force.
3. Outside the window the page shows the garage's phone number instead.

**5. Staff schedule management**

1. Staff open the shared day or week view across all bays.
2. They can move or cancel a booking, block time (holiday, breakdown, lunch), and advance a job through in progress, completed and car ready.
3. Every change is written to the audit log.

**6. Garage-initiated cancellation or move**

1. Staff cancel or move a booking and give a reason.
2. The system emails the customer, refunds the deposit, and offers a link to choose a new slot.

## Domain model

This is the conceptual model, not yet a schema. Customer details live on the booking or enquiry, because there are no customer accounts.

| Entity | Key fields | Notes |
| --- | --- | --- |
| Service | name, category, description, duration, price or price range, required bay type, approval mode (instant or needs approval), active | Edited by admin only. Prices are public. |
| BayType | name (for example MOT ramp, general bay) | Detail to be defined later. |
| Bay | name, bay type, active | A bay holds one booking at a time. |
| OpeningHours | weekday, open time, close time, breaks | Per weekday, editable. |
| ScheduleBlock | bay or all bays, start, end, reason | Holidays, breakdowns, lunch, one-off closures. |
| Booking | customer name, phone, email, car registration, make, model, notes, bay, start, end, status, deposit status, token hash, expiry of hold | One continuous block in one bay. |
| BookingItem | booking, service, price at time of booking, duration at time of booking | Snapshots, so later price edits do not rewrite history. |
| Enquiry | same car and contact fields, symptoms, urgency, notes, status, linked booking | Photos attach to it. |
| EnquiryPhoto | enquiry, storage key, content type, size | Validated on upload. |
| Payment | booking, provider reference, amount, kind (deposit or refund), status | Webhook events are stored to make handling idempotent. |
| StaffUser | name, email, password hash, role | Roles: admin, staff. |
| Setting | key, value | Cancellation window, booking window, cut-off, hold time, deposit amount. |
| EmailLog | recipient, template, related booking, sent at, status | Doubles as a test and debugging aid. |
| AuditEntry | staff user, action, entity, before, after, time | Written for every staff change. |

**Booking statuses:** held, pending approval, confirmed, in progress, completed, cancelled, no show, expired.

**Enquiry statuses:** new, needs information, approved, declined, converted to booking.

**Rules that belong in the model**

- A bay cannot have two active bookings or blocks that overlap in time. Enforce this with a PostgreSQL exclusion constraint on the bay and time range, over a single reservation structure that holds both bookings and blocks.
- Times are stored in UTC and shown in the garage's local time.
- Tokens are random, stored only as hashes, and expire.

## Availability engine

One module answers the question "which start times are open for this set of services?" Both the public booking flow and the staff tools call it, so the rules live in exactly one place. It is the most important piece to design and test well.

**Inputs**

- The selected services, giving total duration and the required bay types.
- Opening hours per weekday, in the garage's local time.
- Schedule blocks and existing bookings, including held and pending ones.
- Policy settings: booking window, cut-off before a slot, slot granularity.
- The current time, passed in as a parameter so tests can control it.

**Behaviour**

1. For each day in the booking window, compute the open intervals per bay, by removing blocks, breaks and existing reservations from opening hours.
2. Keep only bays whose type satisfies every selected service.
3. For each bay, list start times on the slot grid where the total duration fits inside one open interval.
4. Drop starts earlier than now plus the cut-off.
5. Merge across bays and return each start time with the bays that can take it.
6. When a slot is chosen, assign a specific bay and reserve it atomically.

**Design points**

- The engine is a pure function over data, with no database calls inside it. That makes it fast to unit test with hundreds of cases.
- Reserving a slot is a separate, transactional step. The check in the engine is advisory; the database constraint is the final authority.
- Bookings and blocks both occupy a bay, so store them in one reservation structure (or a single table) that the overlap constraint can cover. An exclusion constraint cannot span two separate tables.
- Multi-service bookings are one continuous block in one bay in v1. Splitting a visit across bays is out of scope.

**Edge cases to cover**

- Back-to-back bookings with no gap, and with a configured buffer.
- A job that would cross a lunch break or closing time.
- The last valid start of the day, and a duration longer than any open interval.
- Holidays and partial-day blocks on one bay or all bays.
- Different durations and bay types competing for the same bay.
- The clock change days in March and October, where a local day is 23 or 25 hours long.
- Two customers choosing the same slot at the same moment.

## Architecture and tech stack

The system is a React front end, a FastAPI back end and a PostgreSQL database, with a few supporting services, all started together by Docker Compose.

&#91;embedded content: system architecture · 2 front ends, 1 back end, 5 supporting parts\]

Both front ends call the same API, and the availability engine sits in the services layer. The worker handles expiry and reminders, and Stripe reports payments back to the API.

| Layer | Choice | Why |
| --- | --- | --- |
| Front end | React with TypeScript, built with Vite | You know React, and TypeScript adds type safety to the booking forms. |
| Back end | Python with FastAPI | Quick to build, automatic API docs, strong validation through Pydantic. |
| Database | PostgreSQL | Exclusion constraints give database-level double-booking protection. |
| Migrations | Alembic | Versioned schema changes, tested in CI. |
| Background jobs | A small worker process, with a scheduler for periodic tasks | Expires held slots, sends reminders, retries emails. |
| Email | A mail catcher locally, a free-tier provider when deployed | No cost, and the same interface in both. |
| File storage | S3-compatible storage (a local container in development) | Photo uploads work the same locally and in the cloud. |
| Payments | Stripe in test mode | Real integration pattern, no real money. |
| Containers | Docker Compose for local, the same images in the cloud | Moving to hosting should not need a redesign. |
| CI | GitHub Actions | Free, and runs the whole test suite on every push. |

**Shape of the back end**

- A layered structure: API routes, then services holding business rules, then repositories for database access. The availability engine sits in the service layer as pure code.
- A REST JSON API with separate public and staff route groups. Staff routes require login and a role check.
- Notification sending sits behind an interface, so SMS can be added later without touching booking logic.
- Configuration through environment variables, one set per environment, with no secrets in the repository.

**From local to cloud**

- Everything the app needs (database, mail, storage, worker) is a Compose service, and each maps to a hosted equivalent.
- Environment variables decide which provider is used, so deployment means changing configuration, not code.
- Free hosting tiers change often, so check current options when you reach that milestone.

## Testing strategy

Testing is the main thing that separates this from a typical demo project, so it is planned as a first-class part of the build, not added at the end.

| Level | What it covers | Tools |
| --- | --- | --- |
| Unit | Availability engine, price and duration totals, policy rules (cancellation, cut-off, refund), token generation | pytest, with property-based tests (Hypothesis) for the engine |
| Integration | API routes against a real PostgreSQL in a container, migrations, the overlap constraint, auth and role checks | pytest, httpx, Testcontainers or Compose |
| Concurrency | Many parallel attempts to book the same slot: exactly one wins, the rest get a clean conflict response | pytest with threads or async tasks |
| Payments | Deposit success, failure, duplicate and out-of-order webhooks | Stripe test mode and recorded fixtures |
| Front end | Components, form validation, slot picker behaviour | Vitest, React Testing Library |
| End to end | The six core flows in a real browser, including emailed token links | Playwright, against the mail catcher |
| Non-functional | Accessibility checks, basic load on the availability endpoint, security checks | axe, a load tool, dependency and static scans |

**Practices**

- Build the availability engine test-first. Write the edge-case list from the previous section as failing tests before the code.
- Inject the clock into anything time-dependent so tests never depend on the real time.
- Use factories and seed data for repeatable fixtures.
- CI runs lint, type checks, all test levels and a Docker build on every push, and blocks merging on failure.
- Track coverage, but treat it as a prompt to look at untested code, not as the goal.
- Include migration tests that upgrade an empty database and a seeded one.

**Acceptance checks that tie back to the flows**

- Two browsers book the last slot of the day: one succeeds, one is told it is gone.
- A held slot is released automatically after the hold period.
- A booking made just before a clock change keeps the correct local time.
- A staff account cannot reach admin-only endpoints.
- A used or expired token link shows a safe message and changes nothing.

## Security, reliability and privacy checklist

These are the items that usually come only with experience. Each should map to a task or a test.

**Correctness and reliability**

- [ ] Double-booking blocked by a database constraint, not just application code.
- [ ] Slot holds expire through a background job, and expiry is tested.
- [ ] Payment webhooks are idempotent: a repeated or out-of-order event changes nothing twice.
- [ ] Email sending is retried, logged, and never blocks a booking from completing.
- [ ] All times stored in UTC, displayed in garage-local time, tested across clock changes.
- [ ] Policies live in settings, with changes recorded in the audit log.
- [ ] Health check endpoint, structured logs, and clear error pages.

**Security**

- [ ] Staff passwords hashed with a modern algorithm, with login throttling and secure session or token handling.
- [ ] Role check on every staff endpoint, tested for each role.
- [ ] Token links are random, hashed in storage, expiring, and limited to one booking.
- [ ] Rate limiting and a honeypot or CAPTCHA on the booking and enquiry forms.
- [ ] Photo uploads checked for type, size and content, stored outside the web root, and served safely.
- [ ] Input validation on every field, with output escaping in emails and pages.
- [ ] CORS, security headers and HTTPS settings in the deployed environment.
- [ ] Dependency and container image scanning in CI.
- [ ] No secrets in the repository; separate configuration per environment.

**Privacy**

- [ ] Use fake data throughout the demo.
- [ ] Collect only the fields needed to run a booking.
- [ ] Write a short privacy note and a retention rule for old bookings and photos, even though this is a demo.

**User experience**

- [ ] Mobile-first layout for the public site and the staff schedule.
- [ ] Keyboard navigation, labelled form fields and sufficient contrast.

## Build order

There is no deadline, so each milestone has a definition of done and the next one starts only when it is met. The order puts the riskiest logic, availability and concurrency, before the screens that depend on it.

1. **Foundations.** Repository layout, Docker Compose with app, database and mail catcher, migrations, linting and type checks, CI running an empty test suite, seed data command. *Done when* a fresh clone starts with one command and CI is green.
2. **Services and the public catalogue.** Service, bay type, bay and opening hours models, the public services page with prices. *Done when* the services page renders seeded data and the API has integration tests.
3. **Availability engine, test-first.** The pure engine, the edge-case test list, and the overlap constraint in the database. *Done when* every edge case in the engine section has a passing test and the concurrency test shows exactly one winner.
4. **Booking flow with slot hold.** Service selection, slot picker, hold and expiry job, customer details. *Done when* flow 1 passes end to end without payment.
5. **Deposit payments.** Stripe test mode, idempotent webhooks, refund on eligible cancellation. *Done when* success, failure and duplicate-webhook tests pass.
6. **Email and token self-service.** Templates, send log, token links, customer cancel and reschedule within policy. *Done when* flow 4 passes end to end and expired tokens fail safely.
7. **Staff back office.** Login, roles, shared day and week schedule, move, cancel, block time, job status, "car ready", audit log, mobile layout. *Done when* flow 5 and flow 6 pass and role checks are tested.
8. **Approval bookings and enquiries.** Needs-approval services, the staff queue, enquiry form with photo upload, approve, decline and convert. *Done when* flows 2 and 3 pass end to end.
9. **Hardening and polish.** Rate limiting, accessibility pass, error pages, load test of the availability endpoint, security scans, documentation. *Done when* the checklist section is fully ticked.
10. **Deployment.** Cloud environment from the same images, environment configuration, a seeded live demo, and a short walkthrough or recording. *Done when* the live demo passes the end-to-end suite.

## Open questions and next steps

These are the gaps still to close. None blocks milestones 1 to 3, so building can start while they are answered.

- [ ] **Bay types.** Which types exist, which services need which, and how many bays of each? You said more detail later.
- [ ] **Service list.** The actual services, durations, prices and which are instant or need approval. I can draft a fictional list when you ask for branding and sample data.
- [ ] **Opening hours.** Confirm or replace the proposed weekday and weekend hours, and any lunch break.
- [ ] **Slot grid.** Should start times fall every 15, 30 or 60 minutes, and is a buffer needed between jobs?
- [ ] **Needs-approval hold.** How long is a pending booking's slot held while staff decide?
- [ ] **Reschedule rules.** Does a reschedule inside the free window keep the deposit, and can a booking be rescheduled more than once?
- [ ] **No-shows.** Is the deposit forfeited, and who marks a no-show?
- [ ] **Staff accounts.** How are they created and recovered (admin creates them, password reset by email)?
- [ ] **Hosting.** Which free cloud tier to target when the time comes.

**Suggested next steps**

1. Review this document and answer or comment on the open questions.
2. Agree the repository layout and the first milestone's task list.
3. Define the bay types and service list, since the availability engine tests depend on them.
