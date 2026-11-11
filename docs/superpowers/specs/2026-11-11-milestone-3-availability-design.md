# Milestone 3: Availability Engine — Design

Nov 11, 2026 · Adam Ornoch

Spec: [docs/SPEC.md](../../SPEC.md), "Build order" item 3 and the "Availability engine" section. Builds on Milestone 2 ([design](2026-11-10-milestone-2-catalogue-design.md), [plan](../plans/2026-11-10-milestone-2-catalogue.md)).

## Intent

Answer one question in exactly one place: **"for these services, on this day, which start times are free?"** The public booking flow (Milestone 4) and the staff tools (Milestone 7) will both call it, so the rules must live in a single, heavily tested module. Alongside it, the database gets the final say on double-booking: two reservations in the same bay can never overlap, however the application code behaves or however many requests arrive at once.

This is the riskiest logic in the project, which is why it comes before any booking screens. It's built test-first.

**Done when** every edge case listed under "Edge cases" has a passing test, the concurrency test shows exactly one winner, and `GET /api/availability` has integration tests against real PostgreSQL and a CI smoke check.

## Goals

- A **pure engine**: a function over plain data with no database calls inside, which returns every valid start time for one local day.
- A **`reservations` table** with a PostgreSQL **exclusion constraint**, so no two active reservations in one bay overlap.
- A **reserve step**: it picks a bay for a chosen start and inserts the reservation in one transaction, with the database constraint as the final authority.
- A **concurrency test**: two simultaneous reserves of the same single-bay slot give exactly one success.
- A public, read-only **`GET /api/availability`** endpoint, with integration tests and a CI smoke check.
- Two new settings, **`slot_grid_minutes`** and **`bay_buffer_minutes`**, seeded under the existing "insert what's missing, never overwrite" rule.

## Non-goals

- The booking record: customer details, statuses, hold expiry, the expiry job, deposits. That's Milestone 4 onwards, and it will link to a reservation.
- Any screen. The slot picker is Milestone 4.
- Staff tools for creating blocks. Blocks exist in this milestone only as table rows that tests insert. The admin UI is Milestone 7.
- **Splitting a visit across bays**, and **one bay serving several bay types**. Both were considered and rejected (see "Decisions").
- Searching several days in one call. The endpoint answers one day at a time.
- Load testing. That's Milestone 9.

## Anti-goals

These would make the milestone a failure even if the endpoint works:

- **Two overlapping reservations in one bay can exist**, through any path: a direct insert, a race, or a forgotten check.
- **The engine and the database disagree about the buffer**, for example the engine allowing a start whose buffer overlaps the next booking, which the constraint then rejects at reserve time.
- **"Today" or times worked out in the server's or browser's timezone** instead of `garage_timezone`, or a clock-change day producing shifted, missing or duplicated slots.
- **Grid size, buffer, lead time, booking window or opening hours hardcoded**. All come from the database.
- The engine reading the clock or the database itself. "Now" and all data are passed in.

## Decisions made with Adam

### Start times

- Starts fall on a **30-minute grid** (`slot_grid_minutes` = 30), anchored at **opening time**. A day opening at 08:15 offers 08:15, 08:45 and so on.
- A start is offered only if one bay is free for the **whole job**, and the job **finishes by closing time**.
- The engine returns **every** valid start. How many to show is the screen's decision.
- **Minimum lead time** uses the existing setting `booking_cutoff_minutes` (120). The 60-day window uses the existing `booking_window_days`.
- Grid size, buffer, lead time and opening hours are settings or data, never constants.

### Buffer

- `bay_buffer_minutes` = **15** by default. It covers moving the car out, cleaning the bay and the handover.
- The buffer belongs to the **bay**, not the customer. Customers see the real finish time, while the bay is occupied from start to **end + buffer**.
- The occupied range, including the buffer, is what's stored and what the exclusion constraint checks.
- **Closing time** is checked against the real end time, so the buffer may run past closing.
- **Blocks** (holidays, a broken ramp) are stored with no buffer of their own, but a booking's buffer can't overlap one.

### Breaks (lunch)

- **No job can start during a break.** On a weekday with lunch at 12:30–13:00, 12:30 is never offered, while 12:00 and 13:00 can be.
- **A job that has already started runs straight through the break**, and its finish time ignores the break. A 6-hour clutch job starting at 08:00 finishes at 14:00. The car stays on the ramp.
- Why: when jobs had to finish before lunch, the clutch replacement (6h) could never be booked and the timing belt (5h) only at 09:00 on Saturdays. "Pause the clock over lunch" and "keep the original rule" were offered and declined.
- Breaks stay as they are in the data (`opening_hours_breaks`) and on the page ("Closed 12:30–13:00"). Only the engine rule is new.

### Multi-service visits

- One continuous block in **one bay**, as the spec says. The duration is the sum of the services' durations, and the buffer is added once at the end.
- If the selected services need **different bay types** (for example MOT test plus full service), there are **no times**. The endpoint returns an empty list with a reason, and the Milestone 4 page will tell the customer to book them separately. Splitting the visit across bays and letting the MOT bay do general work were offered and declined.

### Endpoint

- `GET /api/availability` is in this milestone. The reasons: it can be seen working in Swagger, it tests the real data loading and timezone wiring, it settles the API shape early, it shrinks Milestone 4, and it gives CI and Milestone 9 a target.
- It takes one or more service slugs and **one local date**. It returns start and end times in **garage local time with the UTC offset**, and **no bay names**.
- **Needs-approval services get times too**, since a pending booking holds its slot while staff decide.
- With no booking flow yet, the demo site has no reservations, so every slot inside opening hours is free. That's expected.

## Data model

All of these are Claude's calls.

**`reservations`** (new, migration `0003`):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `bay_id` | FK → `bays.id` | |
| `kind` | text, check `IN ('booking', 'block')` | |
| `during` | `tstzrange`, `[)` bounds, not null | The occupied range in UTC. For a booking it runs from start to end + buffer. For a block it's exactly the blocked time. |
| `active` | boolean, default true | Milestone 4 sets it false when a hold expires or a booking is cancelled, so the slot frees up without deleting history. |
| `note` | text, nullable | For example a block's reason. |
| `created_at` | timestamptz, default now | UTC, like every timestamp. |

- The constraint is `EXCLUDE USING gist (bay_id WITH =, during WITH &&) WHERE (active)`. It needs the **`btree_gist`** extension, which the migration creates with `CREATE EXTENSION IF NOT EXISTS`. The downgrade drops the table but leaves the extension.
- Also check `NOT isempty(during)` and `lower_inf(during) = false AND upper_inf(during) = false`, so there are no empty or unbounded ranges.
- A **block covering all bays** is stored as one row per bay. That keeps the constraint simple, and blocks are rare.
- A booking's real end time isn't stored here. Milestone 4's booking record keeps the customer-facing start and end, and the reservation keeps the occupied range. For this milestone, the reserve step returns both.
- `[)` bounds mean a range ending at 10:00 doesn't overlap one starting at 10:00, so back-to-back is allowed.

**Settings** (seeded, never overwritten): `slot_grid_minutes` = 30 and `bay_buffer_minutes` = 15. Both must be whole numbers, with the grid ≥ 5 and the buffer ≥ 0. Changing them is a database edit until Milestone 7's admin screens, just like the Milestone 2 values.

## The engine

A new package, `app/availability/`, holds the engine as **plain dataclasses and functions**. It imports nothing from SQLAlchemy, FastAPI or the clock.

**Inputs** (all passed in):

- the local `date` to search
- the selected services' durations and required bay type IDs
- the active bays with their bay type IDs
- the opening hours and breaks for that weekday, as local wall-clock times
- the active reservations that overlap that local day, as `(bay_id, UTC range)` pairs
- settings: grid minutes, buffer minutes, cut-off minutes, and the garage `ZoneInfo`
- `now`, as an aware UTC datetime

**Output**: a list of slots in start-time order. Each slot has an aware **local** start, an aware local end (the real end, without the buffer), and the IDs of every bay that can take it. The API drops the bay IDs, and the reserve step uses them.

**Rules**, in order:

1. If the services need more than one distinct bay type, return no slots and the reason `mixed_bay_types`.
2. If the day is closed, return no slots.
3. Candidate bays are active bays of the required type.
4. Candidate starts step through **local wall-clock times** from opening time by `slot_grid_minutes`. Each one becomes an aware datetime in the garage zone (see "Clock changes").
5. A start is valid for a bay when all of these hold:
   - the real end (start + total duration, in **elapsed** time) is no later than closing time
   - the start isn't inside any break (`break start ≤ start < break end`). The job may run through a break.
   - `[start, end + buffer)` doesn't overlap any active reservation in that bay
   - start ≥ now + cut-off
6. Keep starts with at least one valid bay.

The engine doesn't check the booking window or past dates. The endpoint rejects those before calling it, so the engine stays usable by staff tools that may bypass the window.

**Clock changes** (Claude's call). Starts are stepped in local wall-clock time, so customers always see :00 and :30. A local time that doesn't exist (in the spring-forward gap) is skipped. An ambiguous local time (in the autumn fall-back hour) uses its **first** occurrence (`fold=0`). Durations and the buffer are measured in **real elapsed time** on UTC instants. The demo hours never touch 01:00–02:00, but the engine must handle any hours an admin might set, so the tests cover a day whose hours span the change.

## The reserve step

`reserve(session, service_ids, start, now, cutoff_minutes=None) -> ReserveResult` lives with the repositories, since it touches the database.

- **Returns** (Claude's call) a small result dataclass holding the inserted `Reservation` row plus the customer-facing local start and real end, so Milestone 4 can store those on the booking without working out the end again.
- **Doesn't check the booking window or past dates** (Claude's call), matching the engine. Callers enforce them: the GET endpoint now, and Milestone 4's `POST` the same way.
- **`cutoff_minutes`** defaults to the `booking_cutoff_minutes` setting when `None`. Staff tools in Milestone 7 can pass 0 to book inside the cut-off.

1. Load the same inputs the endpoint loads, then run the engine for the start's local date.
2. If the requested start isn't among the slots, raise `SlotUnavailable`.
3. Try the slot's bays in a **stable order** (bay `id` ascending). For each one, insert the reservation inside a savepoint. If PostgreSQL raises an exclusion violation (SQLSTATE `23P01`), roll back the savepoint and try the next bay.
4. If every bay fails, raise `SlotUnavailable`. The caller commits.

The engine check is advisory: it makes the common case fast and the error clear. The constraint is the authority, so a race between steps 1 and 3 can only ever make a reserve fail, never double-book.

This milestone exposes no HTTP route for reserving. Milestone 4 adds `POST` for holds, on top of this function.

## API

**`GET /api/availability?services=<slug>&services=<slug>&date=YYYY-MM-DD`**. Public, read-only, no login.

Response (`200`):

```json
{
  "date": "2026-11-12",
  "timezone": "Europe/London",
  "duration_minutes": 270,
  "unavailable_reason": null,
  "slots": [
    { "start": "2026-11-12T08:00:00+00:00", "end": "2026-11-12T12:30:00+00:00" }
  ]
}
```

- `unavailable_reason` is `null`, or `"mixed_bay_types"` when the services can't share a bay. A closed day just gives an empty `slots` list.
- **422** with a JSON detail when: `services` is missing or empty, a slug is unknown or inactive, a slug appears twice, `date` isn't a valid date, `date` is before today in the garage's timezone, or `date` is more than `booking_window_days` after today.
- **503** with JSON when a needed setting is missing or invalid (the timezone, grid, buffer, cut-off or window), matching `GET /api/garage`.
- The route calls repository functions to load the data and then calls the engine. It contains no SQL and no scheduling logic, following the Milestone 2 layering.

## Edge cases

Each needs at least one test, mostly at the unit level on the engine with a fixed `now`.

### From the spec

- Back-to-back bookings with **no gap** (buffer 0) and with the **15-minute buffer**.
- A job that **runs through the lunch break** (allowed, with the finish time unchanged), and one that would cross **closing time** (not offered).
- The **last valid start** of the day, and a **duration longer than any open interval** (no slots).
- **Blocks**: a full-day block on one bay, a partial-day block on one bay, and a block on all bays.
- **Competing durations and bay types**: a long job fits one general bay but not another. An MOT bay booking doesn't affect general-bay slots.
- **Clock changes**: the last Sunday in March (23-hour day) and the last Sunday in October (25-hour day), with hours spanning 01:00–02:00, checking skipped and ambiguous starts and elapsed-time durations. Also the demo hours on those dates, checking the offsets in the output (`+00:00` before, `+01:00` after).
- **Two customers, one slot**: the concurrency test (below).

### From the decisions

- A job may end exactly at closing time, and its buffer runs past it.
- No start inside a break: 12:30 is never offered, while 12:00 and 13:00 are. A 6-hour job at 08:00 is offered and ends at 14:00.
- A booking's buffer may not overlap a block that starts right after the job ends.
- `mixed_bay_types` returns no slots and the reason.
- The cut-off: on a day with no breaks, with `now` at 10:05 local and a 120-minute cut-off, the first start is 12:30, because 12:05 isn't on the grid and 12:00 is too early.
- A start exactly at now + cut-off is allowed.
- A grid anchored at an opening time like 08:15.
- A closed day, a day with no breaks, and a day with two breaks.
- Inactive reservations are ignored. (The engine receives only active ones; the repository test checks that filter.)

### Database

- The constraint rejects overlapping active reservations in one bay, allows the same range in different bays, allows back-to-back `[)` ranges, and allows an overlap when one row is inactive.
- The concurrency test: two threads with **separate connections** wait on a barrier, then both reserve the MOT test at the same start (the MOT bay is the only bay of its type). Exactly one returns a reservation, the other raises `SlotUnavailable`, and the table holds one active row. The test runs several rounds, so a lucky pass isn't mistaken for safety.

**API integration** (Testcontainers PostgreSQL, using the seeded demo garage)

- Shape and offsets, a single service, a multi-service sum, `mixed_bay_types`, a closed or blocked day, each 422 case, the 503 case, and a reservation inserted by the test removing a slot.

**CI smoke check**: in the `compose` job, call the endpoint for `mot-test` on tomorrow's date (computed in the shell) and check the response contains at least one slot.

## Review focus

1. **Buffer consistency between the engine and the constraint**, at closing and next to blocks.
2. **Clock-change days**, plus `now` given in UTC while the day is computed in local time, around midnight.
3. **The concurrency test really runs in parallel**, on separate connections with a barrier, not two calls one after the other in one session.
4. **The reserve step treats the engine as advisory**: a constraint violation means try the next bay, never a 500.
5. **Validation at the edges of the window**: today, the last day of the window, and the day after it.

## Housekeeping

- Work goes on a new branch, `milestone3-availability`, off an up-to-date `main`, and merges through a PR.
- No new runtime dependencies. `zoneinfo` is in the standard library. The Docker image needs `tzdata` only if the base image lacks the zone files; the builder should check that `ZoneInfo("Europe/London")` loads inside the API container.
- The README's Quick start table gains a row for the availability endpoint, with an example URL.

## Left to the builder

- Exact module, function and dataclass names, as long as they follow the Milestone 1 and 2 layout.
- How the repository loads the inputs (one query per kind is fine).
- Whether the engine works internally in UTC instants or local times, as long as the rules above hold.
- The wording of 422 error details.
