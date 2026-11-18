# Milestone 7: Staff Back Office — Design

Nov 16, 2026 · Adam Ornoch

Spec: [docs/SPEC.md](../../SPEC.md), "Build order" item 7 and "Core user flows" flows 5 and 6. Builds on Milestone 6 ([design](2026-11-14-milestone-6-email-self-service-design.md)).

## Intent

This is the garage's own side of the system. Staff log in and see every bay's bookings by day or week. They run the workshop from it, at a desk or on a phone in the workshop. They can book a customer in over the phone, move or cancel a booking, block time, and move a job on through in progress and completed. Every change is saved in an audit log that records who made it.

When the garage has to move or cancel a booking, **staff phone the customer first** and agree what happens. The app has nothing to do with that call. Staff then make the change in the app, and the customer gets an email. For a move, the email gives the **new time staff chose**. The customer never chooses a slot.

Admins can do everything staff can, plus manage staff accounts and read the full audit log. Editing services, bays, hours and contact details moves to its own milestone (Milestone 8).

**Done when** flows 5 and 6 (as changed below) pass end to end in CI, and integration tests show that every staff endpoint refuses anonymous users, removed users and, for admin-only endpoints, staff.

## Changes to the spec

Adam decided these on Nov 16. Update `docs/SPEC.md` as part of this milestone:

- **Build order:** split the old item 7. **7. Staff back office** covers login, staff accounts, the schedule, move, cancel, block time, job status, audit log and the mobile layout. A new **8. Admin settings** covers editing services, bays, bay types, opening hours, breaks and contact details, with protection for existing bookings (below). Approvals and enquiries become 9, hardening 10, deployment 11.
- **No "car ready".** Remove it from the roles table, features, emails, flow 5 and the Notifications decision. When the work is done, the mechanic phones the customer if they've gone away, and payment is settled outside the system. Jobs go confirmed → in progress → completed, or no show.
- **Flow 6:** "Staff phone the customer first, then cancel or move the booking, optionally giving a reason. Each change records who made it. The system emails the customer: a move gives the new time staff chose, and a cancellation refunds the deposit." Remove "offers a link to choose a new slot" and the refund on a move.
- **Decisions log, "Garage-initiated changes":** the same wording as flow 6. A moved booking keeps its deposit and **follows the normal refund rules**: if the customer then cancels inside the free-cancellation period, the deposit isn't refunded, even though the garage did the moving. Adam trusts the garage to move bookings fairly.
- **Phone bookings:** add to the decisions log, the features list and flow 5: staff can book a customer who phones in. A phone booking has **no deposit** and the customer's email is **optional**.
- **Roles table:** Staff can see the schedule, make phone bookings, move or cancel bookings, block time, and set job status (approving bookings and enquiries arrives in Milestone 9). Admin can do all of that, plus manage staff accounts, read the audit log, and (from Milestone 8) edit the settings listed below.
- **Admin-editable settings (for Milestone 8),** chosen by Adam: add a service; edit a service's name, category, description, price and duration; set its bay type and its instant or needs-approval mode only when it's created; hide or show a service; change the display order; add, rename, and take a bay out of use or put it back; add a bay type (it can't be renamed); edit opening hours and regular breaks; edit the garage contact details. **The booking rules (window, cut-off, free-cancellation period, deposit, reminder time, slot grid, bay buffer) can't be changed by admins** and stay in setup data. Changes are rare (a few times a year). **A change that clashes with existing bookings is refused** until staff have moved or cancelled each clashing booking. The refusal lists those bookings. This covers taking a bay out of use and cutting hours or adding a break over booked time. Bookings already store their own service name, price and duration, so editing a service never changes existing bookings.
- **Open questions:** tick "Staff accounts": an admin invites someone by email, and they set their own password from the link. Passwords are reset the same way. Tick "No-shows" with the answer in "Job status" below.
- **Domain model:** add `StaffSession` and `PasswordToken`. `ScheduleBlock` becomes `Block` (below). `AuditEntry` gains `reason`. `Booking` gains `source` and `created_by`, and its email becomes optional for phone bookings. The deposit status gains `not_required`.

## Goals

- **Staff logins** with server-side sessions in Postgres and a secure cookie. Passwords are hashed with argon2, and repeated failed logins are throttled.
- **Staff accounts managed by admins:** invite, change role, remove access, send a password reset. A forgotten password can also be reset from the login page.
- **A shared schedule**, by day and by week, across all bays, usable on a phone.
- **Phone bookings:** staff book a customer in, with no deposit and an optional email.
- **Move** a booking to a time and bay staff pick from availability, with the customer emailed the new time.
- **Cancel** a booking as the garage, always refunding the deposit, with the customer emailed.
- **Block time** for one bay or the whole garage, and remove a block.
- **Job status:** in progress, completed, no show, and undo of the last step.
- **An audit log** of every staff change, recording who made it, what it was before and after, and the reason if given.
- **Role checks on the server** for every staff endpoint, tested for each role.

## Non-goals

- **Admin editing of services, bays, hours and contact details** (Milestone 8).
- **Approving needs-approval bookings and enquiries** (Milestone 9).
- **Recording the phone call** or its outcome.
- **"Car ready"**, collection times, final prices or payments on collection.
- **Taking a deposit for a phone booking**, by payment link or otherwise.
- **Editing a booking's services, car or customer details.**
- **Freeing the rest of the slot when a job finishes early.** The booked time stays booked.
- **Repeating blocks.** Regular breaks such as lunch are opening-hours breaks, which admins edit in Milestone 8.
- **Live updates.** The schedule refreshes itself every 30 seconds while it's open (*Claude's call*).
- **Two-factor login, single sign-on and an outside login provider.**

## Anti-goals

These would make the milestone a failure even if the happy path works:

- **A staff endpoint reachable without a valid session**, or an admin endpoint reachable by staff. Hiding a button is never the only protection.
- **A removed user, or one whose password was reset, still logged in** anywhere after the change.
- **A password, a session token or a password-link token stored in plain text** in the database, logs or a queued email.
- **A move or block that creates a double booking**, or a move that lands outside opening hours, in a break, or in a bay of the wrong type.
- **A staff change without an audit entry**, or an audit entry for a change that was rolled back.
- **An email for a change that was rolled back**, or a committed change that loses its email (the Milestone 6 rule).
- **The login form revealing whether an email has an account**, through either its messages or the forgot-password reply.
- **The garage left with no admin:** removing or demoting the last active admin.

## Decisions made with Adam

1. **Staff phone the customer first**, then move or cancel in the app. The app doesn't record the call.
2. **Staff choose the new time for a move.** There's no customer rescheduling (Nov 14 decision kept).
3. **A moved booking follows the normal refund rules** if the customer cancels it later.
4. **The reason is optional.** Every change records which staff member made it.
5. **No "car ready"** status or email. Jobs end at "completed".
6. **Admin-only:** staff accounts, the full audit log, and (from Milestone 8) the settings Adam listed. Everything else is open to staff and admins.
7. **Logins use server-side sessions with a secure cookie** (approach A below).
8. **Staff accounts are set up by email link**, not by a temporary password an admin types in.
9. **Split the old Milestone 7** into the back office (7) and admin settings (8).
10. **Settings changes that clash with existing bookings are refused** until the clashes are cleared (applies in Milestone 8).
11. **No-shows:** staff mark them after the start time. The deposit is kept, and no email is sent.
12. **Phone bookings:** staff can book a customer who phones in. **No deposit** is taken (chosen over emailing a payment link, and over staff choosing each time). The customer's **email is optional**: with one, they get the usual emails; without one, none are sent.
13. **Login lockout after 10 failed attempts** for one email, and **passwords of at least 8 characters**.

## Approaches considered for logins

| Approach | Trade-off |
| --- | --- |
| **Server-side sessions in Postgres with a cookie scripts can't read (chosen)** | Removing a user or resetting a password ends their sessions immediately. No outside service, and only a password-hashing library is added. One database lookup per staff request, which is trivial at a garage's scale. |
| Signed tokens (JWT) kept in the browser | Popular, and the server stores nothing. A removed user stays logged in until the token expires unless a block list is added, which rebuilds sessions. Tokens in browser storage are easier to steal through an XSS bug. |
| An outside provider (Auth0, Clerk) | Password resets and security come built in. Adds an account and a dependency, the demo can't run offline, and it's a lot for a handful of staff. |

For the schedule screen, a calendar library was considered. The good ones charge for the "one column per bay" view, and the layout is simple, so **we build our own grid** (*Claude's call*).

## Staff accounts and login

### Accounts

- An **admin invites** someone by entering their name, email and role. The person gets an email with a link to **set their own password**. Until then the account shows as "invited".
- **Change role** between staff and admin. It applies on the person's next request, because the role is read from the database every time.
- **Remove access:** the account is marked inactive, its password is cleared, and all its sessions are deleted. The row is kept so the audit log can still name who did what. An admin can **restore** access, which sends a fresh set-password link. The old password never works again.
- **Send a password reset** (by an admin): clears the password, ends all their sessions at once, and emails the person a link. Until they use it they can't log in, so an admin can lock out an account they think is compromised (*Claude's call*). The account shows as "reset sent".
- **Forgot password** on the login page: the person enters their email, and the page always says "If that address has an account, we've emailed a link". It's throttled like logins. Unlike an admin reset, it **doesn't** clear the current password, so nobody can lock a colleague out just by typing their email. *Claude's call*: without it, a sole admin who forgets their password is locked out.
- **There must always be at least one active admin.** Removing or demoting the last one is refused.
- Emails are stored lowercase and are unique.

### Passwords and links

- Hashed with **argon2id** (`argon2-cffi`, default parameters). At least 8 characters (Adam's choice), with no other composition rules.
- A **set-password link** is a random token, stored only as a hash in `password_tokens`, like booking links. It works **once**, and expires after **72 hours for an invite** and **1 hour for a reset** (*Claude's call*). Issuing a new link cancels the person's older unused ones.
- The token goes in the URL **fragment** (`/staff/set-password#t=…`), as booking links do, so it never reaches the server's access logs.
- Setting a password marks the link used, deletes the person's sessions, and logs them in with a new session.

### Sessions

- Logging in creates a `staff_sessions` row holding the **hash** of a random token. The browser gets the plain token in a cookie: `HttpOnly`, `SameSite=Strict`, `Path=/api/staff`, and `Secure` whenever `PUBLIC_BASE_URL` is https.
- A session ends after **7 days without use, or 30 days at most** (*Claude's call*: workshop phones shouldn't need a login every morning). Using it moves `last_used_at` on, written at most once a minute. **Log out** deletes the row.
- **Cross-site protection:** besides `SameSite=Strict`, every staff request that changes something must carry an `Origin` header matching `PUBLIC_BASE_URL`, or it's refused with 403 (*Claude's call*).
- The front end reaches the API on the same origin (the Vite proxy locally, nginx in Compose), so no CORS settings change.

### Throttling

- **Ten failed logins for one email within 15 minutes lock that email out for 15 minutes** (Adam's choice). The same applies to one client IP address at 20 failures (*Claude's call*). While locked, the reply is the same "email or password is wrong" message, so a lockout reveals nothing. Forgot-password requests count towards the same limits.
- Failures are counted in a small `login_attempts` table rather than in memory, so they survive restarts and work with more than one API process.
- The client IP comes from the `X-Forwarded-For` header set by nginx, trusted only from the proxy. The builder decides how, for example uvicorn's `--forwarded-allow-ips`.

### The first admin

- A command creates the first admin: `uv run python -m app.create_admin --name "…" --email "…"`. It **prints** a set-password link (72 hours) to the terminal and sends no email (*Claude's call*: only one token is ever made, and setup doesn't depend on mail working). Its audit entry has no staff user.
- **Sample accounts:** the existing seed (`python -m app.seed`, run on every API start) adds a sample admin and a sample staff member with known passwords, listed in the README, **unless `ENVIRONMENT=production`** (*Claude's call*). Local runs and CI get them, so the end-to-end tests can log in. Whether the live demo in Milestone 11 shows demo logins is decided then.

## The schedule

### Day view `/staff?date=YYYY-MM-DD` (the default page after login)

On a desktop or tablet, bays run across the top and times down the side, from the earliest opening to the latest closing that day. Closed time and breaks are shaded.

```text
 ◀ Tue 17 Nov ▶   [Today]  [Day | Week]                [+ Block time]
        MOT bay           Bay 1               Bay 2
 08:00  ┌───────────────┐                     ░ Blocked: lift ░
        │ AB12 CDE      │ ┌────────────────┐  ░ repair        ░
 09:00  │ MOT           │ │ CD34 EFG       │  ░               ░
        │ ● In progress │ │ Full service   │
 10:00  └───────────────┘ │ ○ Confirmed    │
                          └────────────────┘
 12:30  ░░░░░░░░░░░░░░░░░ lunch ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
```

On a phone the same day is a list, one bay at a time, with tabs to switch bay:

```text
 ◀ Tue 17 Nov ▶            [Day | Week]
 [MOT bay] [Bay 1] [Bay 2]
 08:00–10:00  AB12 CDE · MOT          ● In progress
 10:30–11:00  EF56 GHI · MOT          ○ Confirmed
 12:30–13:30  Lunch (closed)
              [+ Block time]
```

Each booking shows its time, registration, services and status. A held booking (a customer is paying right now) is shown faded as "being booked" and can't be opened. A block shows its note. Tapping a booking opens its detail page.

### Week view `/staff/week?date=YYYY-MM-DD`

Seven days from the Monday of that week. On a desktop each day is a column listing its bookings in time order, each tagged with its bay. On a phone it's one list grouped by day. Tapping a day opens its day view.

### Booking detail `/staff/bookings/:reference`

```text
 ABCD-EFGH · ○ Confirmed
 Tue 17 Nov, 10:30 – 11:00 · MOT bay
 MOT · £54.85
 AB12 CDE · Ford Focus
 Jane Smith · 07700 900123 (tap to call) · jane@example.test
 Notes: "Rattle from the back left"
 Deposit: £20 paid

 [Start job]  [Mark no show]  [Move]  [Cancel booking]

 History
 16 Nov 14:02  Booked by customer
 17 Nov 08:10  Moved from 09:00 by Sam (Staff) — "Lift broken"
```

Which buttons appear depends on the status (see "Job status"). **History** shows this booking's audit entries to all staff, so anyone can see who moved it (*Claude's call*).

### Phone booking `/staff/bookings/new`

A **+ New booking** button sits beside **+ Block time** on the day and week views.

```text
 New phone booking
 Services   [x] MOT   [ ] Full service   [ ] Brake check …
 Date       ◀ Wed 18 Nov ▶
 Time       [09:00 MOT bay] [09:30 MOT bay] [11:00 MOT bay] …
 Customer   Name [          ]  Phone [          ]
            Email (optional) [          ]
 Car        Reg [        ]  Make [        ]  Model [        ]
 Notes      [                                   ]
            No deposit is taken for phone bookings.
            [ Book it ]
```

1. Staff tick the services, pick a date, and choose a time and bay from the free starts.
2. They type in the customer's name, phone, email (optional), car and notes. The same validation as the public form applies (see `app/api/validation.py` and `DetailsForm`).
3. **Book it** creates the booking as **confirmed** straight away, with `deposit_status = 'not_required'`, `source = 'phone'` and `created_by` set to the staff user. Its reservation is made in the same transaction, and the overlap constraint is the final check. If the time was just taken, the page says so and shows the times again.

**Rules** (*Claude's calls*):

- **Free times** follow the move rules below: the same engine, cut-off 0, no booking-window limit, with hours, breaks, blocks, other bookings, bay type and buffer all applying. Durations come from the current services.
- **Any active service can be booked**, including needs-approval ones, because a staff member making the booking is approving it. Services that need different bay types still can't go in one booking, as on the public site.
- **Prices, names and durations are saved on the booking items** at booking time, as for online bookings.
- **With an email**, the customer gets the usual confirmation (with the booking link), the reminder, and any move or cancellation emails. **Without one**, nothing is queued for that booking, and the schedule and detail page show "no email, phone only".
- **No deposit anywhere:** the confirmation email and the customer's link page show no deposit line (their wording already comes from `deposit_status`). If the customer cancels from their link, the free-cancellation rule still decides whether they can, but there's nothing to refund. If the garage cancels, nothing is refunded either.
- The schedule and detail page tag it **"Phone booking · no deposit"**, and its history starts "Booked by phone by Sam (Staff)".

### Move

1. Staff press **Move** and pick a date. The page shows the free start times that day and the bays that can take each one, defaulting to the first.
2. Staff choose a time and bay, optionally type a reason, and confirm. The page says "Have you called the customer? They'll be emailed the new time."
3. The booking's start and end, and its reservation's bay and time, change in one transaction. The database's overlap constraint is the final check. If someone took the time in the meantime, the page says so and shows the times again.

**The rules for a move's available times** (*Claude's call*): the same availability engine the public site uses, with these differences:

- the booking's own reservation isn't counted as occupied, so it can move later the same morning;
- durations come from the booking's own saved items, not the current service settings;
- the cut-off before a slot is 0, and the booking window doesn't apply, so staff can move a job to later today or further ahead than customers can book;
- opening hours, breaks, blocks, other bookings, the bay type and the bay buffer all apply as normal.

Only **confirmed** bookings can be moved. A move to the same time and bay is refused as "no change".

**After a move:** the booking's links get a new expiry (the new end + 7 days), so the customer's link keeps working. The customer can still cancel from their link under the normal rules, counted from the new start. If the reminder was already sent, no second one goes out. If it hasn't been sent, it goes out as normal, 48 hours before the new start.

### Cancel as the garage

Staff press **Cancel booking**, optionally type a reason, and confirm. It calls the existing `cancel_booking(by="garage")`, which always refunds a paid deposit, and queues the garage cancellation email. If the refund can't start because Stripe is unreachable, nothing changes and the page says to try again, as in Milestone 6. Only **confirmed** bookings can be cancelled this way.

### Block time

**+ Block time** opens a form with: the bay, or **all bays**; the start date and time; the end date and time; and a note, which is required ("Holiday", "Lift broken"). A block can run over several days.

- A block is one `blocks` row plus one `reservations` row (`kind = 'block'`) per bay it covers, so the existing overlap constraint protects it.
- **A block that would cover any booking is refused**, and the reply lists the bookings in the way so staff can call those customers and move or cancel them first. This matches Adam's choice for settings changes. A held booking in the way counts too, and the page says to try again in a few minutes.
- A block can be **removed** from its detail panel. It's kept in the audit log.
- Blocks can't be edited. To change one, remove it and add a new one (*Claude's call*).

### Job status

| From | To | Button | When |
| --- | --- | --- | --- |
| confirmed | in progress | Start job | Any time. If it isn't the booking's day (garage-local), the page asks "This job is booked for Thu 19 Nov. Start it now?" first. |
| in progress | completed | Complete job | Any time |
| confirmed | no show | Mark no show | Only after the booking's start time |
| in progress | confirmed | Undo start | Any time |
| completed | in progress | Undo complete | Within 24 hours of completing |
| no show | confirmed | Undo no show | Within 24 hours of marking |

*Claude's calls*: Start job isn't limited to the booking's day, because a car can arrive early, and the end-to-end test can't count on a booking existing today. Undo is there because a wrong tap on a phone is easy to make, and every change, undo included, is in the audit log. **Adam decided (Nov 16):** a no-show **keeps the deposit and the booked time** (nothing is refunded or freed), and it sends no email. The garage can phone the customer if they want to. Once a booking is in progress, completed or a no show, it can't be moved or cancelled. The customer's link page already shows these statuses with the phone number.

## Audit log

Every staff change writes an `audit_entries` row **in the same transaction as the change**:

| Action | Before → after |
| --- | --- |
| `booking.create` | the booking's time, bay, services, customer and car (phone bookings) |
| `booking.move` | start, end, bay |
| `booking.cancel` | status, deposit status |
| `booking.status` | status |
| `block.create`, `block.remove` | the block's bays, times and note |
| `staff.invite`, `staff.role`, `staff.remove`, `staff.restore`, `staff.reset_password` | name, email, role, active (never a password or token) |

The entry records the staff user, the time, the entity (type and id, and the booking reference where there is one), and the optional reason. Logins, logouts and failed logins aren't audit entries. They go to the application log, and each account shows a `last_login_at` (*Claude's call*).

**Audit page `/staff/audit` (admin only):** newest first, filterable by date range, staff member and booking reference, 50 per page. Booking history on the detail page reads the same entries.

## Emails

New templates, each with HTML and plain text, queued with the existing `queue_email` in the same transaction and sent by the worker:

- **Booking moved:** "Your booking has moved", giving the old time, the new time, the reason if one was given, the booking link, and "if the new time doesn't suit, please call us on …". It mentions the free-cancellation deadline counted from the new start, using the same rule as the confirmation email.
- **Cancelled by the garage:** "We've had to cancel your booking", giving the reason if one was given, that the £20 deposit is being refunded (wording from `deposit_status`, as in Milestone 6), and the phone number to book another time.
- **Staff invite:** "You've been invited to {garage} bookings", with the set-password link.
- **Password reset:** "Reset your password", with the link, valid for 1 hour.

`email_log` changes:

- **`staff_user_id`**, nullable, for the two staff emails. A check makes sure each row has a booking or a staff user, never both (enquiries arrive in Milestone 9 and may change this check).
- **`context`**, nullable JSONB, for what the template needs that the booking no longer holds: the reason, and for a move the previous start, end and bay. It never holds a token.

As with booking links, **the worker creates the password token when it sends** the invite or reset email, so the plain token is never in the database. A queued invite or reset for a removed user is marked `skipped`.

A cancellation by the garage makes any queued reminder or confirmation for that booking `skipped`, as Milestone 6 already does for customer cancellations.

## Data model

One migration. Everything goes through `get_session`, as before (see the multi-garage direction).

### Changes to `bookings`

- **`source`**: `online` or `phone` (check constraint), with existing rows set to `online`.
- **`created_by`**: nullable FK to staff_users, set for phone bookings.
- **`deposit_status`** gains **`not_required`**. The `confirmed_has_deposit` check allows `paid`, `waived` or `not_required`, and a check says `not_required` only goes with `source = 'phone'`.
- The `confirmed_has_details` check no longer requires `customer_email` when `source = 'phone'`. Every other detail is still required.
- `queue_email` is never called for a booking without an email. The reminder query skips such bookings too. The builder decides whether the callers check first or `queue_email` returns nothing, but a phone booking without an email must never raise an error when it's moved, cancelled or reaches reminder time.

### `staff_users`

`id`, `name`, `email` (unique, lowercase), `password_hash` (null until the invite is accepted), `role` (`admin` or `staff`, check constraint), `active` (bool), `created_at`, `last_login_at`.

### `staff_sessions`

`id`, `staff_user_id` (FK, cascade delete), `token_hash` (unique), `created_at`, `last_used_at`, `expires_at` (the 30-day cap). The worker deletes expired sessions in its existing loop.

### `password_tokens`

`id`, `staff_user_id` (FK), `purpose` (`invite` or `reset`), `token_hash` (unique), `expires_at`, `used_at`, `created_at`.

### `login_attempts`

`id`, `email` (lowercase, as typed), `ip`, `succeeded`, `at`, indexed on `(email, at)` and `(ip, at)`. The worker deletes rows older than a day.

### `blocks`

`id`, `note`, `start_at`, `end_at`, `all_bays` (bool), `created_by` (FK to staff_users), `created_at`, `removed_at`. **`reservations` gains a nullable `block_id`** (FK). A check says a reservation with `kind = 'block'` has a `block_id`. Removing a block sets `removed_at` and makes its reservations inactive.

### `audit_entries`

`id`, `staff_user_id` (FK), `action`, `entity_type`, `entity_id`, `booking_reference` (nullable, indexed), `before` (JSONB), `after` (JSONB), `reason` (nullable text), `at`. Indexed on `at` and on `staff_user_id`.

## API

All staff routes live under **`/api/staff`** in their own router. Every route depends on `current_staff`, which reads the cookie, looks up the session, checks the user is active, and returns the user. Admin routes add `require_admin`. The only routes without that dependency are login, forgot password and set password. A test checks this (see Testing).

| Method and path | Who | Does |
| --- | --- | --- |
| `POST /login` | anyone | email, password → sets the cookie and returns the user. 401 with one generic message for a wrong email, wrong password, inactive account or lockout. |
| `POST /logout` | staff | Deletes the session. |
| `GET /me` | staff | The current user (name, role). The front end uses it to check who's logged in. |
| `POST /forgot-password` | anyone | email → always 202. Queues a reset if the account exists and is active. |
| `POST /set-password` | anyone | token, new password → sets it, logs in. 400 for a bad, used or expired token, with one message. |
| `GET /schedule?from=YYYY-MM-DD&days=1..7` | staff | Bays, each day's hours and breaks, and the reservations in range, with booking summaries and block notes. |
| `GET /availability?services=…&date=` | staff | Free starts and bays for those services that day, using the staff rules. |
| `POST /bookings` | staff | services, start, bay, customer and car details (email optional) → the new confirmed booking. 409 if the time was taken. |
| `GET /bookings/{reference}` | staff | Full details, the allowed actions, and its history. |
| `GET /bookings/{reference}/move-options?date=` | staff | Free starts and bays for that day, using the move rules. |
| `POST /bookings/{reference}/move` | staff | start, bay, optional reason → 409 if the time was taken, or if the booking isn't confirmed. |
| `POST /bookings/{reference}/cancel` | staff | optional reason → 409 if not confirmed, 503 if the refund can't start. |
| `POST /bookings/{reference}/status` | staff | the new status → 409 if the change isn't allowed now. |
| `POST /blocks` | staff | bay or all, start, end, note → 409 with the bookings in the way. |
| `DELETE /blocks/{id}` | staff | Removes it. |
| `GET /team` | admin | Staff accounts, with invited, active or removed. |
| `POST /team` | admin | Invite: name, email, role. 409 if the email exists. |
| `PATCH /team/{id}` | admin | role and/or active → 409 for the last admin. |
| `POST /team/{id}/reset-password` | admin | Queues a reset and ends their sessions. |
| `GET /audit?from=&to=&staff=&reference=&page=` | admin | Audit entries. |

Each change locks the booking row first, as the existing code does, then applies the change, writes the audit entry, queues any email, and commits. A booking's actions are worked out once, on the server, and the page just shows the buttons it's given.

## Front end

Staff pages live in the same React app under **`/staff`** (`frontend/src/staff/`), with their own layout: a top bar with the garage name, Day/Week, and for admins Team and Audit, plus the user's name and Log out.

- `/staff/login`, `/staff/forgot-password`, `/staff/set-password#t=…`
- `/staff` (day), `/staff/week`, `/staff/bookings/new`, `/staff/bookings/:reference`
- `/staff/team` and `/staff/audit` (admin only; staff who open them see "You don't have access to this page")

Going to any staff page without a session goes to the login page and returns to the page afterwards. A 401 from any call does the same. Staff pages shouldn't wait for the public catalogue load in `App.tsx` that customer pages use today. The builder decides how to separate the two.

**Mobile first:** every staff page works at 360px wide, with buttons at least 44px tall. The day grid becomes the per-bay list below about 700px.

## Testing

- **Unit:** the job status rules (each change, including the "booking's day", "after start" and 24-hour undo limits across a clock change); move-time rules (own reservation excluded, saved durations, cut-off 0); password rules; throttle counting at its limits; session expiry (idle and cap); email rendering for the four new templates, including HTML escaping of a reason such as `<script>`.
- **Integration** (real Postgres, injected clock):
  - **Role checks for every staff route:** a test walks every route the app has under `/api/staff` and, except for the three public ones, checks that no cookie gets 401, a removed user's old cookie gets 401, an expired session gets 401, and staff get 403 on admin routes. A new route without the dependency fails this test.
  - A cross-site request (wrong or missing `Origin`) that changes something gets 403.
  - Login: success, wrong password, unknown email and inactive account all give the same 401; the lockout after 10 failures, and its end.
  - Invite → email queued → the worker sends it and creates the token → set password → logged in; the token works once; it expires; issuing a new one cancels the old one.
  - Reset and removal end every session for that user. A role change takes effect on the next request. The last admin can't be removed or demoted.
  - Move: success (booking, reservation, links' expiry, audit entry, email with context); into a taken time (409, nothing changes); a booking that isn't confirmed (409); two staff moving the same booking at once (one wins).
  - Phone booking: with an email (confirmed, `not_required`, confirmation queued, audited); without an email (no email queued, and a later move, cancel and reminder run without errors or emails); into a taken time (409); a needs-approval service is allowed; mixed bay types are refused; the customer's link page and email show no deposit.
  - Garage cancel: refunded, audited, email queued, queued reminder skipped; Stripe unavailable (503, nothing changes, no email, no audit entry).
  - Blocks: one bay and all bays; refused over a booking, with the list; removed; the public availability no longer offers blocked times.
  - Every change writes exactly one audit entry, and a rolled-back change writes none.
- **Frontend** (Vitest): login and its error, the redirect to login and back, the day grid and the phone list, the booking detail buttons for each status, the move picker, the block form and its "bookings in the way" message, the team page, and the access message for staff on admin pages.
- **E2E** (Playwright):
  - **Flow 5:** log in as the demo staff member → add a phone booking without an email → it appears on the day view → add a block on another bay → open the booking → Start job (confirming the "not today" question if it appears) → Complete job → log in as the demo admin → the audit page shows those entries with the staff member's name.
  - **Flow 6:** a customer books and pays → staff log in, move it with a reason → the move email in Mailpit has the new time and the reason → its link shows the new time → staff cancel it → the garage cancellation email arrives → the customer's page shows the refund.
  - A staff login sees no Team or Audit links, and opening `/staff/team` shows the access message.

## Left to the builder

- The exact grid rendering (CSS grid or absolutely positioned blocks), colours, and how statuses are shown, keeping contrast and labels accessible.
- How the front end separates staff pages from the public catalogue load.
- How the worker fits session, login-attempt and email clean-up into its loop.
- How the trusted-proxy IP is configured for uvicorn and nginx.
- File layout, following the existing `api / services / repositories` pattern (likely `app/staff/` for auth, accounts and audit, and `app/schedule/` for schedule, move, blocks and status).
- Whether `GET /schedule` returns local or UTC times, as long as the page shows garage-local times and is correct across a clock change.
- The wording of pages and emails, following the tone of the Milestone 6 emails.
