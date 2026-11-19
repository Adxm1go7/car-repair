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
| Customers | No accounts. Guest booking with name, phone and email. A private token link in each email lets them view or cancel one booking. To change the time, they phone the garage (decided Nov 14). |
| Staff | Two roles, admin and staff. Everyone sees one shared schedule. An admin invites someone by email, and they set their own password from the link; passwords are reset the same way (decided Nov 16). |
| Scheduling | Bays only, no per-mechanic calendars. Bays have types (for example MOT ramp, general bay); the detail comes later. |
| Opening hours | Open all week, shorter hours on Saturday and Sunday. *Proposed*: Mon to Fri 08:00 to 17:30, Sat 09:00 to 14:00, Sun 10:00 to 13:00, all editable by the admin. |
| Services | Public prices, fixed or a range. Each has a duration, a required bay type, and an instant or needs-approval flag. |
| Multi-service visits | Allowed. If any selected service needs approval, the whole booking goes to staff. |
| Unknown issues | A separate enquiry flow with structured fields and a description, no photos. Staff approve, decline or ask for more information (photos dropped Nov 19). |
| Deposit | Flat £20 per booking in Stripe test mode, balance paid in person. Refundable when cancelled 24 hours or more ahead. For approval bookings it is requested after approval. |
| Notifications | Email only in v1: confirmation, reminder, cancellation, garage-initiated change. SMS can be added later behind the same interface. There is no "car ready" message: when the work is done, the mechanic phones the customer if they've gone away, and payment is settled outside the system (decided Nov 16). |
| Garage-initiated changes | Staff phone the customer first, then cancel or move the booking, optionally giving a reason. Each change records who made it. The system emails the customer: a move gives the new time staff chose, and a cancellation refunds the deposit. A moved booking keeps its deposit and follows the normal refund rules: if the customer then cancels inside the free-cancellation period, the deposit isn't refunded, even though the garage did the moving. The garage is trusted to move bookings fairly (decided Nov 16). |
| Phone bookings | Staff can book a customer who phones in. A phone booking has no deposit, and the customer's email is optional (decided Nov 16). |
| No-shows | Staff mark a no-show. It keeps the deposit and the booked time (nothing is refunded or freed), and sends no email (decided Nov 16). |
| Admin settings | Admins can add a service; edit a service's name, category, description, price and duration; set its bay type and its instant or needs-approval mode only when it's created; hide or show a service; change the display order; add, rename, and take a bay out of use or put it back; add a bay type (it can't be renamed); edit opening hours and regular breaks; and edit the garage contact details. The booking rules (window, cut-off, free-cancellation period, deposit, reminder time, slot grid, bay buffer) can't be changed by admins and stay in setup data. A change that clashes with existing bookings, such as taking a bay out of use or cutting hours or adding a break over booked time, is refused until staff have moved or cancelled each clashing booking, and the refusal lists them. Bookings store their own service name, price and duration, so editing a service never changes existing bookings (decided Nov 16, built in Milestone 8). Opening hours change from a date the admin chooses (tomorrow at the earliest). Several future timetables can be lined up, such as winter and summer hours. Taking a bay out of use takes effect at once and is for a broken or retired bay. Planned time off uses blocks (decided Nov 18). |
| Policy settings | *Proposed*: booking window 60 days, cut-off 2 hours before a slot, slot hold 5 minutes (shortened from 10 in Milestone 4), free cancellation 24 hours. All stored as settings, not hardcoded. |
| Stack | Python with FastAPI, React with TypeScript, PostgreSQL, Docker Compose, GitHub Actions. |
| Staff interface | Responsive, usable on a phone or tablet in the workshop. |
| Hosting | Run locally with Docker Compose first, then deploy to a free cloud tier without redesign. |
| Quality bar | Tests at unit, integration, concurrency and end-to-end level, run in CI. Availability engine built test-first. |
| Branding and sample data | Deferred until you ask for them. |

## Users and roles

There are three kinds of user, and only two of them log in.

| Role | Logs in? | Can do |
| --- | --- | --- |
| Customer | No | Browse services, book, send an enquiry, and use their emailed token link to view or cancel one booking. |
| Staff | Yes | See the shared schedule, make phone bookings, move or cancel bookings, block time, and set job status (in progress, completed, no show). Approving bookings and enquiries arrives in Milestone 9. |
| Admin | Yes | Everything staff can do, plus manage staff accounts, read the audit log, and (from Milestone 8) edit the settings listed under "Admin settings" in the decisions log. |

Every staff endpoint checks the role on the server. Hiding a button in the interface is never the only protection.

## Features and scope

Version 1 is the complete demonstration. Everything in the second list is deliberately left out and should not creep in.

**In v1**

- Public site: services page with prices, booking flow, issue-enquiry form, contact details.
- Booking: pick one or more services, enter car details (registration, make, model, notes), choose an open slot, pay the deposit, receive a confirmation email.
- Enquiry: structured fields (registration, make and model, symptoms, urgency) and a free-text description, with a staff approval queue.
- Token self-service: view and cancel from an emailed link, cancelling only within the policy window. No customer rescheduling: they call the garage.
- Back office: login, staff accounts, shared day and week schedule, phone bookings (no deposit, email optional), move and cancel, blocked time, job status, booking and enquiry management, service and price editing, opening hours and contact details.
- Emails: confirmation, reminder, cancellation, garage-initiated change (move or cancel), staff invite and password reset.
- Operations: audit log of staff changes, seed data for a realistic demo garage, one-command local startup.

**Later, not v1**

- SMS, customer accounts, service history per car, MOT and service reminders, quotes and invoices, parts and stock, per-mechanic scheduling, multi-garage support.

## Core user flows

Seven flows cover the whole product. Each should become at least one end-to-end test.

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

1. The customer fills in the structured form (registration, make and model, symptoms, urgency) and describes the problem.
2. The enquiry appears in the staff queue as new.
3. Staff reply by email to approve and offer a slot, ask for more information, or decline. An approved enquiry converts into a pending booking.

**4. Customer self-service through the token link**

1. The email link opens that one booking, with no login.
2. The customer can cancel while inside the policy window, and the deposit is refunded. They can't reschedule: for a different time, the page asks them to call.
3. Outside the window the page shows the garage's phone number instead.

**5. Staff schedule management**

1. Staff open the shared day or week view across all bays.
2. They can book a customer who phones in (no deposit, email optional), move or cancel a booking, block time (holiday, breakdown, lunch), and advance a job through in progress and completed, or mark a no show.
3. Every change is written to the audit log, with who made it.

**6. Garage-initiated cancellation or move**

1. Staff phone the customer first, then cancel or move the booking, optionally giving a reason. Each change records who made it.
2. The system emails the customer: a move gives the new time staff chose, and a cancellation refunds the deposit.

**7. Admin settings**

1. An admin adds, edits, hides or shows, and reorders services; adds and renames bays and takes them out of use or back; adds bay types; lines up opening hours from a future date; and edits the garage's contact details.
2. A change that would leave a booking outside the opening hours, or in a bay that's out of use, is refused and lists those bookings, each linking to its page. Staff phone the customers, move or cancel the bookings, and try again.
3. Every change is written to the audit log, with who made it.

## Domain model

This is the conceptual model, not yet a schema. Customer details live on the booking or enquiry, because there are no customer accounts.

| Entity | Key fields | Notes |
| --- | --- | --- |
| Service | name, category, description, duration, price or price range, required bay type, approval mode (instant or needs approval), active | Edited by admin only. Prices are public. |
| BayType | name (for example MOT ramp, general bay) | Detail to be defined later. |
| Bay | name, bay type, active | A bay holds one booking at a time. |
| Timetable | start date (garage-local), created by | A week of opening hours, in force from its start date until the next timetable starts. The first starts on 1 Jan 2000, so every date has one. A new one starts tomorrow at the earliest; only future ones can be edited or deleted, so past days keep the hours they had. |
| OpeningHours | timetable, weekday, open time, close time, breaks | One row per weekday of a timetable; a closed day has no times. Breaks lie inside the day's hours. |
| Block | bays (one or all), start, end, note, created by | Holidays, breakdowns, one-off closures. Removing one is audited. |
| Booking | customer name, phone, email (optional for phone bookings), car registration, make, model, notes, bay, start, end, status, deposit status, source (online or phone), created by, token hash, expiry of hold | One continuous block in one bay. Deposit status includes `not_required` for phone bookings. |
| BookingItem | booking, service, price at time of booking, duration at time of booking | Snapshots, so later price edits do not rewrite history. |
| Enquiry | same car and contact fields, symptoms, urgency, description, status, linked booking | No photos (decided Nov 19). |
| Payment | booking, provider reference, amount, kind (deposit or refund), status | Webhook events are stored to make handling idempotent. |
| StaffUser | name, email, password hash, role, active, last login | Roles: admin, staff. A removed account is kept inactive so the audit log can still name it. |
| StaffSession | staff user, token hash, created, last used, expires | Server-side login sessions, carried by a cookie. |
| PasswordToken | staff user, kind (invite or reset), token hash, expires, used | Set-password links. Only the hash is stored. |
| Setting | key, value | The booking rules (cancellation window, booking window, cut-off, hold time, deposit amount, reminder time, slot grid, bay buffer) are setup data that admins can't change. The garage contact details are edited by admins. |
| BookingLink | booking, token hash, expires at, created at | One per email that carries a link. Only the hash is stored; it expires a week after the booking ends. |
| EmailLog | recipient, template, related booking, status, attempts, next attempt at, last error, sent at | The send queue as well as the log. Doubles as a test and debugging aid. |
| AuditEntry | staff user, action, entity, before, after, reason, time | Written for every staff change, in the same transaction. |

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
| End to end | The seven core flows in a real browser, including emailed token links | Playwright, against the mail catcher |
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
- [x] Payment webhooks are idempotent: a repeated or out-of-order event changes nothing twice.
- [x] Email sending is retried, logged, and never blocks a booking from completing.
- [ ] All times stored in UTC, displayed in garage-local time, tested across clock changes.
- [ ] Policies live in settings, with changes recorded in the audit log.
- [ ] Health check endpoint, structured logs, and clear error pages.

**Security**

- [ ] Staff passwords hashed with a modern algorithm, with login throttling and secure session or token handling.
- [ ] Role check on every staff endpoint, tested for each role.
- [x] Token links are random, hashed in storage, expiring, and limited to one booking.
- [ ] Rate limiting and a honeypot or CAPTCHA on the booking and enquiry forms.
- [ ] Input validation on every field, with output escaping in emails and pages.
- [ ] CORS, security headers and HTTPS settings in the deployed environment.
- [ ] Dependency and container image scanning in CI.
- [ ] No secrets in the repository; separate configuration per environment.

**Privacy**

- [ ] Use fake data throughout the demo.
- [ ] Collect only the fields needed to run a booking.
- [ ] Write a short privacy note and a retention rule for old bookings and enquiries, even though this is a demo.

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
6. **Email and token self-service.** Templates, send log, token links, customer cancel within policy (no customer rescheduling). *Done when* flow 4 passes end to end and expired tokens fail safely.
7. **Staff back office.** Login, staff accounts, roles, shared day and week schedule, phone bookings, move, cancel, block time, job status, audit log, mobile layout. *Done when* flow 5 and flow 6 pass and role checks are tested.
8. **Admin settings.** Editing services, bays, bay types, opening hours, breaks and contact details, with clashing changes refused until the bookings in the way are moved or cancelled. *Done when* an admin can make each kind of change from the Settings page; a clashing change (a bay out of use with bookings, or hours that leave bookings outside opening time) is refused with those bookings listed, and nothing changes; the public site and the staff schedule show the right hours for every date, across a change of timetable; every change is in the audit log; and flow 7 passes end to end in CI.
9. **Approval bookings and enquiries.** Needs-approval services, the staff queue, enquiry form, approve, decline and convert. *Done when* flows 2 and 3 pass end to end.
10. **Hardening and polish.** Rate limiting, accessibility pass, error pages, load test of the availability endpoint, security scans, documentation. *Done when* the checklist section is fully ticked.
11. **Deployment.** Cloud environment from the same images, environment configuration, a seeded live demo, and a short walkthrough or recording. *Done when* the live demo passes the end-to-end suite.

## Open questions and next steps

These are the gaps still to close. None blocks milestones 1 to 3, so building can start while they are answered.

- [ ] **Bay types.** Which types exist, which services need which, and how many bays of each? You said more detail later.
- [ ] **Service list.** The actual services, durations, prices and which are instant or need approval. I can draft a fictional list when you ask for branding and sample data.
- [ ] **Opening hours.** Confirm or replace the proposed weekday and weekend hours, and any lunch break.
- [ ] **Slot grid.** Should start times fall every 15, 30 or 60 minutes, and is a buffer needed between jobs?
- [ ] **Needs-approval hold.** How long is a pending booking's slot held while staff decide?
- [x] **Reschedule rules.** No customer rescheduling: customers call the garage for a different time (Nov 14).
- [x] **No-shows.** Staff mark a no-show; it keeps the deposit and the booked time, and sends no email (Nov 16).
- [x] **Staff accounts.** An admin invites someone by email and they set their own password from the link; passwords are reset the same way (Nov 16).
- [ ] **Hosting.** Which free cloud tier to target when the time comes.

**Suggested next steps**

1. Review this document and answer or comment on the open questions.
2. Agree the repository layout and the first milestone's task list.
3. Define the bay types and service list, since the availability engine tests depend on them.
