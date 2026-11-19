# Milestone 8: Admin Settings — Design

Nov 18, 2026 · Adam Ornoch

Spec: [docs/SPEC.md](../../SPEC.md), "Build order" item 8 and the "Admin settings" row of the decisions log. Builds on Milestone 7 ([design](2026-11-16-milestone-7-staff-back-office-design.md)).

## Intent

Today the garage's own details are setup data: changing a price, a bay or the opening hours means a developer edits `backend/app/demo_data.py` and resets the database. This milestone lets an **admin** change them from the staff pages:
- **Services:** add, edit, hide or show, and reorder.
- **Bays:** add, rename, and take out of use or put back.
- **Bay types:** add new ones.
- **Opening hours and regular breaks.**
- **Contact details.**

Changes are rare: a few times a year. What matters most is that a change **never quietly breaks a booking a customer already has**. A change that would clash with existing bookings is refused, and the refusal lists those bookings, so staff can phone the customers and move or cancel them first (the Milestone 7 way). Then the change is tried again.

Opening hours change **from a date the admin chooses**, so the garage can set up "winter hours from 1 December" ahead of time, and customers booking further ahead already see the new hours.

**Done when:**
- An admin can make each kind of change from the Settings page.
- A clashing change (a bay out of use with bookings, or hours that leave bookings outside opening time) is refused with those bookings listed, and nothing changes.
- The public site and the staff schedule show the right hours for every date, across a change of timetable.
- Every change is in the audit log.
- The end-to-end test below passes in CI.

## Changes to the spec

Adam decided these on Nov 18. Update `docs/SPEC.md` as part of this milestone:

- **Decisions log, "Admin settings":** add "Opening hours change from a date the admin chooses (tomorrow at the earliest). Several future timetables can be lined up, such as winter and summer hours. Taking a bay out of use takes effect at once and is for a broken or retired bay. Planned time off uses blocks."
- **Domain model:** `OpeningHours` becomes per timetable. Add `Timetable` (start date) and give `OpeningHours` and its breaks a timetable. The `Setting` row's notes: the garage contact details are edited by admins, and the booking rules aren't.
- **Build order, item 8:** *Done when* as above.

## Goals

- Admins can edit everything in the "Admin settings" row of the decisions log, and nothing more.
- Opening hours are **timetables**. Each is a full week (open and close times or closed, plus breaks) with a start date. It applies until the next one starts.
- A change that would leave an existing booking outside the garage's hours, or in a bay that's out of use, is **refused and lists those bookings**. Nothing is half-applied.
- The public site, the booking page's day strip, free times, phone bookings, moves and the staff schedule all use **the timetable in force on each date**.
- Every change writes an audit entry (before and after) in the same transaction, and the audit page describes it in words.

## Non-goals

- **The booking rules** (window, cut-off, free-cancellation period, deposit, reminder time, slot grid, bay buffer, holds) stay as setup data, as decided Nov 16.
- **One-off closures** (a bank holiday, a training day): blocks on all bays already do this.
- **Deleting** a service, bay or bay type. Hiding a service and taking a bay out of use cover it, and the history stays readable.
- **Renaming a bay type**, or changing a service's bay type or instant/needs-approval mode after it's created (decided Nov 16).
- **Bays out of use from a later date** (decided Nov 18): out of use is always immediate.
- **Staff (non-admin) access** to settings, even read-only.
- Photos for services, bulk import, and undo.
- The needs-approval flow itself (Milestone 9): admins can create needs-approval services, but booking them stays as it is now.

## Anti-goals

These would make the milestone a failure even if every page works:

- **An existing booking ends up outside opening hours or in a bay that's out of use**, without staff having moved it first. That includes a booking made at the same moment as the change (see "Racing a booking").
- **A refused change that partly happened**, e.g. a timetable saved but its breaks not, or a bay marked out of use with its clash list shown.
- **Past days rewritten:** the schedule for last month must still show the hours it really had.
- **A customer partway through booking seeing their day change under them.** That's why a new timetable can't start today.
- **Editing a service changes an existing booking's name, price or duration.** Bookings keep their own copy, as now.

## Decisions made with Adam

| Decision | Choice (Nov 18) |
| --- | --- |
| When an hours change takes effect | **From a date the admin chooses** (option B), so future hours can be set up ahead of time. |
| How dated hours are stored | **A timetable table** (approach A below). |
| When a bay goes out of use | **Straight away.** It's only for a broken or retired bay; planned time off is a block. |
| The rest of the list | As in the decisions log (Nov 16): editable service fields, bay type and approval mode fixed at creation, hide/show, display order, bays, bay types (not renamed), contact details, clashes refused with a list. |

## Approaches considered for dated opening hours

Three parts of the code read opening hours today: free times (`repositories/availability.py`), the staff schedule (`schedule/view.py`) and the public `GET /api/opening-hours` (home page hours, "open today", and the booking page's bookable days). Each has to ask "which hours apply on this date?"

- **A. A timetable table (chosen).** A new `timetables` table holds an id and a start date. Each weekday's hours and breaks belong to one timetable. The data looks like what admins edit (a week from a date), so adding, editing and deleting is one row plus its days, and the existing database checks (open before close, break start before end) keep working. Cost: a migration that re-keys the hours tables.
- **B. A start date on each weekday row.** A smaller schema change, but "the week from 1 Dec" doesn't exist in the data: it's seven rows that share a date. Showing, editing and deleting it means grouping rows, and a half-saved week becomes possible. Rejected: more fiddly code and more ways to go wrong, to save one table.
- **C. Timetables as one JSON setting.** No table migration, but it loses the database checks, two admins saving at once could overwrite each other, and it goes against how the rest of the catalogue is stored. Rejected.

## Opening hours: timetables

### Data

- `timetables`: `id`, `starts_on` (a garage-local date, **unique**), `created_by` (staff user, null for the first one), `created_at`.
- `opening_hours` gains `timetable_id`. Its key becomes `(timetable_id, weekday)`. Open and close stay nullable together (closed day), with open before close.
- `opening_hours_breaks` belong to `(timetable_id, weekday)`, with start before end. *Claude's call:* the builder adds a check that a break lies inside that day's opening hours, in code if a database check is awkward.
- The **migration** creates one timetable with `starts_on = 2000-01-01` and moves today's hours and breaks into it, so nothing changes for existing data. The seed does the same for an empty database. **Downgrade** refuses with a clear message if more than one timetable exists, and otherwise folds the single timetable back.

### Rules

- **The timetable in force on a date** is the one with the latest `starts_on` on or before that date. There's always one, because the first starts in 2000.
- **A new timetable starts tomorrow at the earliest** (garage-local), so nobody's open booking page changes mid-day. Its start date must not already be taken. *Claude's call:* the form starts as a copy of the timetable in force just before the chosen date, so admins change only what's different.
- **A future timetable** (`starts_on` after today) can be **edited or deleted**. Its start date can't be edited: to move it, delete it and add it again (*Claude's call*, which keeps the clash rules simple).
- **A timetable in force today or in the past is fixed.** To change hours again, add a new timetable from a later date. Past days keep the hours they had.

### The clash check

A timetable change affects a **date range**: from its start date up to (not including) the next timetable's start date, with no end if it's the last one.
- **Add:** the new timetable's range, checked against the new hours.
- **Edit:** its range, checked against the edited hours.
- **Delete:** its range, checked against the timetable **before** it, which now carries on over those dates.

A booking **clashes** if it falls on a date in the range and the hours being checked wouldn't allow it: it starts before opening, ends after closing, overlaps a break, or the day is closed. Bookings that count are **held** (and not past its hold time), **waiting for approval**, **confirmed** and **in progress**. Cancelled, expired, completed and no-show bookings don't count.

On a clash the change is refused with **409** and a list of the bookings: reference, garage-local start, bay, and whether it's a hold being paid for right now. The page says a hold clears in a few minutes, as the Milestone 7 block form does. Nothing is saved.

*Claude's call:* the bay buffer isn't part of the check. It separates jobs, not jobs and closing time, as the availability engine already treats it.

### Who reads it

Every reader asks for the timetable in force on each date. One repository function serves them all:
- **Free times** (public and staff), holds, phone bookings and moves.
- **The staff day and week views.**
- **The public API.** *Claude's call:* `GET /api/opening-hours` changes shape. It returns the timetable in force today and **any that start within the booking window**, each with its start date and its seven days. The front end is the only client and changes with it.
- **The home page** shows today's hours. If a new timetable starts within the booking window, it adds a line like "New hours from Tue 1 Dec" with that week.
- **"Open today"** and **the booking page's day strip** decide each date from the timetable in force on that date. A weekday closed under one timetable and open under the next must show correctly on each side of the change.

## Bays and bay types

- **Add a bay:** name and bay type. It can be booked straight away. *Claude's call:* the slug is made from the name, made unique, and never changes.
- **Rename a bay:** the name only. Bay names must be unique among bays (*Claude's call*, so the schedule and clash lists aren't ambiguous).
- **Take a bay out of use:** it takes effect at once. It's **refused with 409 and a clash list** while the bay has bookings that count (as above) ending after now. Its future blocks are left alone. If it's the last bay in use of its type, the confirm step warns that the services needing that type can't be booked until one is back, and lets the admin go ahead.
- **Put a bay back in use:** at once, with no clash check needed.
- **Blocks on all bays cover new bays too.** *Claude's call:* when a bay is added or put back in use, every block on all bays that hasn't ended yet is extended to it, in the same transaction. A bank holiday already blocked then covers the new bay as well. Where the bay already has its own block over part of that time, the existing block stands and the all-bays block skips that part. It never refuses: a bay that has just been added or put back has no bookings that could be in the way.
- **The schedule keeps showing an out-of-use bay where it has history.** *Claude's call:* on any day where a bay that's out of use has bookings or blocks (last month's jobs, say), the day and week views still show its column, marked "Out of use". On other days it's hidden, as now. Free times never offer it.
- **Add a bay type:** a name (and a slug made from it). It can't be renamed. On its own it does nothing until a bay and a service use it.

## Services

- **Add:** name, category, description, duration, price (fixed, or from and to), bay type, and instant or needs approval. The last two can't be changed afterwards. It goes to the end of the display order, shown.
- **Edit:** name, category, description, duration and price.
- **Hide or show.** A hidden service isn't offered for new bookings, and its existing bookings carry on.
- **Reorder** with up and down buttons, which swap a service with its neighbour.
- None of these can clash: bookings keep their own copy of the name, price and duration.

Rules (*Claude's call* where the spec is silent):
- The name is required and unique among services.
- The category is picked from the existing ones, or a new one is typed.
- The duration is 15 to 480 minutes, in steps of 15.
- Prices are in pounds and pence, at least £0, with "to" above "from" when given.
- The description is required and at most 500 characters.
- The slug is made from the name once and never changes, because it's in booking links (`?services=`).
- If the chosen bay type has no bay in use, the form warns that the service can't be booked until one is added, and lets the admin go ahead.

## Contact details

The name, address, phone and email in the `garage_contact` setting. All four are required, and the email and phone are checked like a customer's. A change shows at once on the site and in **every email sent from then on**, including ones queued earlier but not yet sent, because the worker reads the details when it sends (*Claude's call*: that's how it works today, and old details in a late email would be worse). Emails already sent keep the old details.

## Racing a booking

A customer can be taking a hold, or staff making a phone booking or a move, at the same moment an admin takes a bay out of use or saves a timetable. Each side checks first and then writes, so without care both can succeed and leave a booking in a bay that's out of use or outside the hours.

**Requirement:** these must take turns. Either the booking sees the new state and is offered something else (or refused as taken), or the admin's clash check sees the booking and refuses.

*Claude's call:* use one PostgreSQL transaction-level advisory lock for "the garage's hours and bays":
- Anything that creates or moves a booking takes it **shared**: holds, phone bookings, moves.
- Taking a bay out of use and adding, editing or deleting a timetable take it **exclusive**, then run their clash check.

Bookings don't wait on each other, and admin changes are rare. The builder may choose another way to serialise, but it needs a concurrency test either way.

### Bookings that come back

Two existing paths bring a booking back into a bay without going through free times. Neither may land it in a bay that's out of use or outside the hours in force:

- **A late deposit payment** for a hold that has run out. `_take_time_back` in `payments/service.py` turns the hold's time back on, and today its only check is the database overlap rule. *Claude's call:* it also takes the shared lock and checks that the bay is in use and the booking fits the hours in force on its date. If either check fails, the payment is refunded, the same as when the time has been taken by someone else. The clash check keeps ignoring holds past their time. This needs its own test: hold, expire, take the bay out of use, then pay late, and the payment must end refunded with no booking in that bay.
- **Undoing a no-show or a completed job.** *Claude's call:* the undo is refused with 409 if the bay is now out of use. These are past or same-day jobs, so the hours aren't checked: a day already worked keeps the hours it had.

## The Settings page

`/staff/settings` (admin only; staff see "You don't have access to this page"), with a **Settings** link in the top bar for admins. It has four tabs, and the URL keeps the tab (`/staff/settings/services` and so on).

```
Settings   [Services] [Bays] [Hours] [Contact]

Services                                   [+ Add a service]
  ▲▼  MOT test             MOT        1h     £54.85     Shown    [Edit] [Hide]
  ▲▼  Oil & filter change  Servicing  45m    £69.00     Shown    [Edit] [Hide]
  ▲▼  Diagnostic check     Diagnosis  1h     £45–£90    Hidden   [Edit] [Show]

Bays                                       [+ Add a bay] [+ Add a bay type]
  MOT bay   MOT ramp      In use       [Rename] [Take out of use]
  Bay 3     General bay   Out of use   [Rename] [Put back in use]

Hours
  Now (since the start)  Mon–Fri 08:00–17:30, break 12:30–13:00 · Sat 09:00–14:00 · Sun 10:00–13:00
  From Tue 1 Dec         Mon–Fri 08:00–17:00 · Sat closed · Sun closed        [Edit] [Delete]
  [+ New hours from a date]
```

- Every change that affects customers (hide, take out of use, delete or save hours) asks to confirm first.
- A 409 shows the bookings in the way, each linking to its booking page, so staff can call, move or cancel, and then try again.
- It works on a phone, like the rest of the staff pages.

## API

Admin only, under `/api/staff/settings`. These routers use the Milestone 7 Origin check and `require_admin`, and the prefix joins `ADMIN_STAFF_PREFIXES` so the route-guard walk covers it.

| Endpoint | Does |
| --- | --- |
| `GET /services` | Every service, shown and hidden, in display order. |
| `POST /services` | Add. 422 for a bad field, 409 for a name already used. |
| `PATCH /services/{id}` | Edit the editable fields, or `active`. |
| `POST /services/{id}/move` | `{"direction": "up" \| "down"}` swaps with its neighbour. |
| `GET /bays`, `POST /bays` | List (in use and out of use) and add. |
| `PATCH /bays/{id}` | `name` and/or `active`. 409 with clashes for out of use. |
| `GET /bay-types`, `POST /bay-types` | List and add. |
| `GET /hours` | Every timetable with its days and breaks, marked past, current or future. |
| `POST /hours` | Add from a date. 409 with clashes. |
| `PUT /hours/{id}` | Replace a future timetable's days and breaks. 409 with clashes. |
| `DELETE /hours/{id}` | Delete a future timetable. 409 with clashes. |
| `GET /contact`, `PUT /contact` | Read and save the contact details. |

Public: `GET /api/opening-hours` changes as described under "Who reads it". `GET /api/services` and `GET /api/garage` are unchanged, apart from now reflecting edits.

## Audit log

The same `record_audit`, in the same transaction, with before and after:

| Action | Entity |
| --- | --- |
| `service.create`, `service.update`, `service.hide`, `service.show`, `service.move` | service |
| `bay.create`, `bay.rename`, `bay.out_of_use`, `bay.back_in_use` | bay |
| `bay_type.create` | bay_type |
| `hours.create`, `hours.update`, `hours.delete` | timetable (the snapshot is the whole week) |
| `contact.update` | setting (*Claude's call:* entity id 0, since settings are keyed by name) |

The audit page gets readable wording for each, e.g. "Took Bay 3 out of use" or "New hours from Tue 1 Dec". A refused (409) change writes nothing.

## Testing

- **Unit:** finding the timetable in force (before, on and after a start date, and the first one); the clash check for add, edit and delete (start before opening, end after closing, over a break, closed day, statuses that count and don't, a hold past its time); slug-making; service field rules.
- **Integration:**
  - Each endpoint's happy path and its 409 or 422.
  - Admin-only enforcement through the route-guard walk.
  - The audit entry for each change, and none for a refused one.
  - Free times and the staff schedule on each side of a timetable change, including a clock change between them.
  - The public opening-hours shape.
  - The migration upgrade (existing hours become the first timetable), plus the downgrade with one timetable and its refusal with two.
- **Concurrency:** a hold racing a bay out of use, and a hold racing a timetable that cuts its time. Exactly one wins in each. A late payment after the bay went out of use ends refunded.
- **Integration (bays):** all-bay blocks extended to a new or restored bay; the schedule showing an out-of-use bay only on days with history; an undo refused in an out-of-use bay.
- **Frontend (Vitest):**
  - each tab's list and forms, the confirm steps, and the clash list with links
  - the day strip and home page across a timetable change
  - the access message for staff
- **End to end (one new flow):** the admin adds a service and sees it on the public site; hides it again; makes a booking (or uses one already in place) and tries a timetable that would leave it outside hours, sees it listed and nothing saved; then adds a future timetable that clashes with nothing and sees it on the home page. It cleans up after itself, as flow 5 does.

## Left to the builder

- The exact form layouts and wording, following the Milestone 7 staff pages.
- How the slug is made unique (e.g. a number suffix).
- Whether the hours editor is one form per timetable or edits a day at a time, as long as a save is all or nothing.
- The advisory lock's key, or another serialisation with the same guarantee and a concurrency test.
- How the public opening-hours response is shaped in detail, within "Who reads it".
- File layout, following the existing pattern (likely `app/settings/` for the rules and clash checks, and `app/api/staff_settings*.py` for the routes).
