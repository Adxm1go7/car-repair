# Milestone 2: Services and the Public Catalogue — Design

Nov 10, 2026 · Adam Ornoch

Spec: [docs/SPEC.md](../../SPEC.md), "Build order" item 2. Builds on Milestone 1 ([plan](../plans/2026-10-27-milestone-1-foundations.md)).

## Intent

Give the project its first real domain data: the services the garage sells, the bays it does them in, and when it is open. Show that data to customers on a public, phone-first page. Milestone 3's availability engine reads exactly this data, so the shape chosen here has to serve it, not just the page.

**Done when** the public page renders the seeded services, opening hours and contact details, and every new API endpoint has integration tests against real PostgreSQL.

## Goals

- Tables for bay types, bays, services, opening hours and breaks, created by one migration.
- Realistic fictional demo data, loaded by the existing seed command.
- Three read-only public endpoints: services, opening hours, garage details.
- A public page at `/` in the card layout (option B from the mockups), replacing the M1 "API: ok" page.
- Tests at the backend integration level and the frontend component level.

## Non-goals

- Admin screens for editing any of this. That is Milestone 7. Until then, values change through the seed file and a database reset.
- Booking buttons, slot picking or availability. Those are Milestones 3 and 4.
- Letting one bay serve more than one bay type (for example, the MOT bay doing general work when free).
- A router, multiple pages, service images, SEO or branding.
- End-to-end browser tests. Playwright arrives with the first core flow in Milestone 4.

## Anti-goals

These would make the milestone a failure even if the page works:

- Catalogue values hardcoded in app logic or the page. All of it must come from the database.
- Re-running the seed overwrites something an admin changed.
- Rows deleted instead of deactivated. Later bookings will point at services and bays.
- Money held as floats.

## Decisions made with Adam

- **Demo garage data** uses the defaults below. Adam asked for defaults and confirmed them.
- **Everything is editable later**, so the data lives in database rows, never in code paths.
- **The public page shows all three**: services with prices, opening hours, and contact details.
- **Layout B**: one page, a card per service, an "Open today" strip at the top.

## Demo data

Fictional garage **Hillside Motors**. Phone `01632 960123` (Ofcom's drama range), email `bookings@example.com`, address `12 Station Road, Anytown, AT1 2CD`.

**Bay types and bays:** one `mot` bay type with bay "MOT bay", and one `general` bay type with bays "Bay 1", "Bay 2" and "Bay 3". Each bay has exactly one type, and each service requires exactly one type.

**Services:**

| slug | Name | Category | Duration | Price (pence) | Bay type | Approval |
| --- | --- | --- | --- | --- | --- | --- |
| mot-test | MOT test | MOT | 60 | 5485 | mot | instant |
| oil-filter-change | Oil & filter change | Servicing | 45 | 6900 | general | instant |
| interim-service | Interim service | Servicing | 90 | 12900 | general | instant |
| full-service | Full service | Servicing | 180 | 21900 | general | instant |
| air-con-regas | Air-con regas | Servicing | 60 | 7900 | general | instant |
| front-brake-pads | Front brake pads | Brakes | 90 | 12000–18000 | general | instant |
| battery-replacement | Battery replacement | Electrical | 30 | 9000–18000 | general | instant |
| diagnostic-check | Diagnostic check | Diagnostics | 60 | 6000 | general | needs approval |
| timing-belt | Timing belt | Repairs | 300 | 35000–55000 | general | needs approval |
| clutch-replacement | Clutch replacement | Repairs | 360 | 45000–75000 | general | needs approval |

Each gets a one-line description written by the builder. The table order is the display order.

**Opening hours** (garage local time): Mon to Fri 08:00–17:30 with a 12:30–13:00 lunch break, Sat 09:00–14:00, Sun 10:00–13:00.

## Data model

All of these are Claude's calls unless marked otherwise.

- **`bay_types`**: id, `slug` (unique), name.
- **`bays`**: id, `slug` (unique), name, `bay_type_id` (FK), `active`.
- **`services`**: id, `slug` (unique), name, category (plain text), description, `duration_minutes` (> 0), `price_from_pence` (≥ 0), `price_to_pence` (nullable; when set, ≥ `price_from_pence`; null means a fixed price), `required_bay_type_id` (FK), `approval_mode` (`instant` or `needs_approval`, enforced by a check constraint), `active`, `sort_order`.
- **`opening_hours`**: `weekday` as the primary key (0 = Monday to 6 = Sunday, check constrained), `open_time` and `close_time` as local wall-clock `time` values. Both null means closed that day; otherwise both are set and open < close.
- **`opening_hours_breaks`**: id, `weekday` (FK to `opening_hours`), `start_time`, `end_time`, with start < end. A separate table so a day can have zero or several breaks, which Milestone 3 needs.
- **New settings rows**: `garage_timezone` = `"Europe/London"`, and `garage_contact` = `{name, address, phone, email}`. Opening times are local wall-clock times, and the timezone setting is what turns them into UTC moments in Milestone 3.
- Database constraints back every rule above, so bad data can't get in even through a direct insert.
- Categories have no table. The page orders categories by the lowest `sort_order` among their services.

## Seed behaviour

The seed extends the M1 rule: **insert what's missing, never overwrite**.

- Bay types, bays and services are matched on `slug`; opening hours on `weekday`; settings on `key`.
- Breaks have no natural key, so a day's default breaks are inserted only when that day's opening-hours row is inserted.
- Running the seed twice inserts nothing the second time. Changing a seeded value in the database and re-running the seed leaves the change in place.

## API

Public, read-only, no login. Under `/api`, in a new route module. Routes call query functions and contain no SQL themselves, following the spec's layering.

- **`GET /api/services`**: active services in `sort_order`. Each item has `slug`, `name`, `category`, `description`, `duration_minutes`, `price_from_pence`, `price_to_pence` and `approval_mode`. Bay details are internal and not exposed.
- **`GET /api/opening-hours`**: always 7 entries, Monday first, each with `weekday`, `open`, `close` (as `"HH:MM"`, or null when closed) and `breaks` (a list of `{start, end}`).
- **`GET /api/garage`**: `name`, `address`, `phone`, `email` and `timezone`, from settings.

Responses are Pydantic models, so the OpenAPI docs describe them.

## Public page (layout B)

- **Header** with the garage name.
- **"Open today" strip**: for example "Open today 08:00–17:30", "Closed now, opens 08:00 tomorrow", or "Closed today, opens Mon 08:00". Worked out in the garage's timezone from the API, never the browser's. The current time is injectable so tests control it.
- **Service cards** grouped by category. Each card has the name, description, duration (for example "1h 30m"), price ("£219", or "£450–£750" for a range), and a **needs approval** badge where it applies. No Book button yet.
- **Bottom section** with the weekly hours, including breaks, plus address, phone (a `tel:` link) and email (a `mailto:` link).
- **Loading state** while fetching. **Error state** if any request fails: a short message plus the phone number when it's known.
- Phone-first CSS that still looks right on desktop. Plain CSS with no UI library (Claude's call), and accessible markup: headings in order, lists for the cards, and sufficient contrast.

## Testing

- **Migration**: the existing up/down round trip and `alembic check` cover the new tables. New tests check that the constraints reject bad rows: a negative duration, a price range with the top below the bottom, a duplicate slug, an unknown approval mode, and a break with its end before its start.
- **Seed**: a fresh run inserts the expected counts; a second run inserts nothing; an edited service price survives a re-run.
- **API integration** against Testcontainers PostgreSQL: response shapes, inactive services hidden, ordering, a closed day shown as null, contact details from settings.
- **Frontend** with Vitest and React Testing Library, mocking `fetch`: cards grouped by category, price and duration formatting, the badge, "Open today" for open, before-opening, after-closing and closed days with the clock fixed, and the error state.
- **CI**: the compose smoke test also calls `/api/services` and checks it returns the seeded MOT test.

## Housekeeping

- Add `.superpowers/` (brainstorm mockups) to `.gitignore`.
- Work happens on a new branch off `main` and merges through a PR, since `main` is protected.

## Smaller calls made while reviewing (Claude's)

- The "Open today" strip ignores breaks: during lunch it still says "Open today 08:00–17:30". The breaks are listed in the weekly hours below.
- If the `garage_contact` or `garage_timezone` setting is missing, `GET /api/garage` returns 503 with a JSON error, like `/api/health`, rather than an unhandled 500. The seed always creates both, so this only matters when the data is broken.
- Breaks on a closed day are rejected by the seed's data, not the database. Milestone 7's admin validation will own that rule.

## Left to the builder

- Exact module and file names, as long as they follow the M1 layout.
- Service descriptions and the CSS details.
- Whether the frontend fetches the three endpoints in parallel. It should.
