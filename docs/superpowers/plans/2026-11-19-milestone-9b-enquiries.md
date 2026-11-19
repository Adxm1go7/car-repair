# Milestone 9b: Enquiries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A customer with an unknown problem sends a description from the public site. Staff see it in an Enquiries queue and either book it in (a confirmed, no-deposit booking) or decline it, and each step emails the customer.

**Architecture:**
- **Storage:** a new `enquiries` table holds the customer's details and description. Its emails go through the existing outbox, which gains an enquiry path next to the booking and staff ones.
- **Approving** locks the enquiry row and calls the existing `create_phone_booking` with `source="enquiry"`. It then marks the enquiry converted and links it to the booking.
- **Code layout:** the backend rules and actions live in a new `app/enquiries/` package. The frontend adds a public `enquiry/` folder and `staff/enquiries/`. The approve form reuses `NewBookingPage`.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, pytest; React 19 + TypeScript, Vitest + Testing Library; Playwright; Mailpit.

**Spec:** [docs/superpowers/specs/2026-11-19-milestone-9b-enquiries-design.md](../specs/2026-11-19-milestone-9b-enquiries-design.md) (and [docs/SPEC.md](../../SPEC.md) flow 3).

## Global Constraints

- **Enquiry statuses:** `new`, `converted`, `declined`. Approving or declining anything not `new` is refused with 409 `not_new`.
- **Description:** required, 10 to 1000 characters after trimming. Errors:
  - "Please describe the problem" when it's blank.
  - "Please describe the problem in at least 10 characters" when it's too short.
  - "The description can be at most 1000 characters" when it's too long.
- **Customer fields:** name, phone, email (required), registration, make and model, using the existing `clean_*` rules in `app/bookings/rules.py`.
- **Decline reason:** optional, at most 500 characters, using the existing `clean_reason`.
- **New booking source:** `enquiry`. Bookings from it are `confirmed` with `deposit_status = "not_required"`.
- **New email templates:** `enquiry_received` and `enquiry_declined`. Neither has a link.
- **Approval emails:** an approved enquiry queues the existing booking `confirmation` email.
- **New audit actions:**
  - `enquiry.approve`, entity type `enquiry`, with `booking_reference` set to the new booking's reference.
  - `enquiry.decline`, entity type `enquiry`.
- **Handled lists:** newest `handled_at` first, at most 100 rows. The new list is oldest `created_at` first, with no cap.
- **Copy, exactly:**
  - "Ask about a problem" (the public page heading)
  - "Enquiry sent"
  - "Enquiries (n)" / "Enquiries" (the menu link)
  - "No new enquiries." / "No booked enquiries." / "No declined enquiries." (empty tabs)
  - "Approve and book", "Decline", "Decline enquiry"
  - "Booked — the customer has been emailed"
  - "This enquiry has already been dealt with" (the message for `not_new`)
  - "Booked from an enquiry by {who}" (booking history)
  - "From enquiry · no deposit" (the schedule and booking page note)
- **Lock order:**
  1. The enquiry row `FOR UPDATE`.
  2. Then whatever `reserve` takes (`lock_shared`, then the reservation rows).
  - Nothing locks in the other order.
- **Commits:** one short title, "area - what", with no body and no attribution.
- **Windows:** write files as UTF-8 with LF line endings (Edit or Write, or `open(..., encoding="utf-8", newline="\n")`).
- **Backend checks:**
  ```
  cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
  ```
  Use plain `uv run mypy`, as CI does, so the tests are type-checked too.
- **Frontend checks:** `npm run lint && npm run typecheck && npm test`, run from PowerShell in `e:\WORK_FOLDER_OF_FOLDERS\car-repair\frontend`. Vitest fails from Git Bash `/e/` paths.
- **End-to-end:** from PowerShell in the repo root:
  ```
  docker compose up -d --build --wait
  cd e2e; npx playwright test
  ```

## Review Focus

1. **Approving into a slot that's just been taken** must leave the enquiry `new`, with no booking, no audit entry and no email, so staff can pick another time. Pinned in Task 4 (`test_approve_taken_slot_leaves_enquiry_new`).
2. **Two staff approving the same enquiry at once** must give one booking and one `not_new`, never two bookings. Pinned in Task 4 (`test_two_approvals_make_one_booking`).
3. **A description of exactly 10 or exactly 1000 characters** is accepted, and 9 or 1001 is refused. Surrounding whitespace doesn't count towards either limit. Pinned in Task 2 (`test_description_limits`).
4. **Markup in the description or the name** (`<b>`, `<script>`) appears as text in the HTML email, never as markup. Pinned in Task 2 (`test_enquiry_email_escapes_description`).
5. **A double click on "Send"** on the public form sends one enquiry: the button is disabled while sending. Pinned in Task 6 (`the send button is disabled while sending`).

---

### Task 1: Enquiry model and migration

**Files:**
- Create: `backend/app/models/enquiry.py`, `backend/migrations/versions/0011_enquiries.py`
- Modify:
  - `backend/app/models/__init__.py` (export `Enquiry`)
  - `backend/app/models/booking.py` (`BOOKING_SOURCES` gains `"enquiry"`; `not_required_only_by_phone` allows `source IN ('phone', 'enquiry')`; the email-required rule in `CONFIRMED_HAS_DETAILS` stays phone-only)
  - `backend/app/models/email.py` (`EMAIL_TEMPLATES` gains the two templates; `enquiry_id` column and relationship; `has_one_subject` becomes "exactly one of `booking_id`, `staff_user_id`, `enquiry_id`")
- Test: create `backend/tests/integration/test_enquiry_constraints.py`; modify `test_email_constraints.py`; `test_migrations.py` covers the round trip unchanged.

**Interfaces:**
- Produces:
  - `ENQUIRY_STATUSES: Final = ("new", "converted", "declined")`.
  - `class Enquiry(Base)`, table `enquiries`, with these columns:
    - `id`, `status` (String(10), server default `new`), `created_at` (server default now)
    - `customer_name` (100), `customer_phone` (20), `customer_email` (254), `car_registration` (8), `car_make` (50), `car_model` (50)
    - `description` (Text)
    - `handled_at`, `handled_by` (FK `staff_users.id`), `decline_reason` (String(500), nullable)
    - `booking_id` (FK `bookings.id`, unique, nullable)
  - Its relationships are `handler: StaffUser | None` and `booking: Booking | None`.
  - Its checks: `status_valid`; `booking_only_when_converted`, which is `(status = 'converted') = (booking_id IS NOT NULL)`; and `handled_unless_new`, which is `(status = 'new') = (handled_at IS NULL AND handled_by IS NULL)`.
  - It has an index on `(status, created_at)`.
  - `EmailLog.enquiry: Mapped[Enquiry | None]`.

- [ ] **Step 1: Write the failing tests.**
  - `test_converted_needs_booking`: an enquiry with `status="converted"` and no booking raises IntegrityError on `ck_enquiries_booking_only_when_converted`. The same check fails for `status="new"` with a booking.
  - `test_handled_needs_who_and_when`: a `declined` enquiry with no `handled_at` fails `ck_enquiries_handled_unless_new`.
  - `test_enquiry_booking_needs_no_deposit_and_may_be_confirmed`: a confirmed booking with `source="enquiry"` and `deposit_status="not_required"` flushes. A `source="online"` booking with `not_required` still fails.
  - `test_enquiry_email_has_one_subject`: an EmailLog with `enquiry_id` alone flushes. One with both `enquiry_id` and `booking_id` fails `ck_email_log_has_one_subject`.
  - `test_enquiry_templates_allowed`: both new templates flush.
- [ ] **Step 2: Run them.** Run `uv run pytest tests/integration/test_enquiry_constraints.py tests/integration/test_email_constraints.py -q`. Expected: FAIL (there's no `Enquiry`).
- [ ] **Step 3: Implement.**
  - Migration 0011 creates the table, adds `email_log.enquiry_id` (with an index), and replaces `bookings.source_valid`, `bookings.not_required_only_by_phone`, `email_log.has_one_subject` and `email_log.template_valid`. It uses 0010's `_replace_check` and copies the constraint text rather than importing it.
  - The downgrade refuses (RuntimeError) while any booking has `source = 'enquiry'`. It then deletes enquiry email rows, restores the old checks, and drops the column and the table.
- [ ] **Step 4: Run the backend checks.** Expected: all pass, `test_migrations` included.
- [ ] **Step 5: Commit.** `backend - enquiry model and migration`

### Task 2: Description rule and the two enquiry emails

**Files:**
- Create:
  - `backend/app/enquiries/__init__.py`
  - `backend/app/enquiries/rules.py`
  - `backend/app/email/templates/enquiry_received.{txt,html}.j2`
  - `backend/app/email/templates/enquiry_declined.{txt,html}.j2`
- Modify: `backend/app/email/message.py`, `backend/app/email/render.py`, `backend/app/email/queue.py`, `backend/app/email/outbox.py`
- Test: create `backend/tests/unit/test_enquiry_rules.py`; modify `backend/tests/unit/test_render_email.py`, `backend/tests/integration/test_outbox.py`, `test_queue_email.py`

**Interfaces:**
- Consumes: Task 1's `Enquiry` and `EmailLog.enquiry`.
- Produces:
  - `clean_description(value: str) -> str` in `app/enquiries/rules.py`. It trims, and raises ValueError with the Global Constraints messages.
  - `EnquiryTemplate = Literal["enquiry_received", "enquiry_declined"]` in `message.py`.
  - `@dataclass(frozen=True) class EnquiryEmailContext` in `render.py`, with the fields `customer_name, registration, make, model, description, reason: str | None, garage: dict[str, str]`.
  - `render_enquiry_email(template: EnquiryTemplate, to: str, context: EnquiryEmailContext) -> OutgoingEmail` in `render.py`. The subjects are "We've got your enquiry" and "We can't take on your enquiry".
  - `queue_enquiry_email(session, template: EnquiryTemplate, enquiry: Enquiry, context: dict | None = None) -> EmailLog` in `queue.py`. It flushes and doesn't commit.
  - In `outbox._prepare`, a row with `enquiry_id` goes to `_prepare_enquiry`. It always sends `enquiry_received`, and sends `enquiry_declined` only while the enquiry is `declined`. The reason is read from the row's `context["reason"]`.

- [ ] **Step 1: Write the failing tests.**
  - `test_description_limits` (unit, parametrized):
    - `"x" * 10` and `"x" * 1000` pass. `"  " + "x" * 10 + "  "` returns the trimmed value.
    - `"x" * 9` raises "Please describe the problem in at least 10 characters".
    - `"x" * 1001` raises "The description can be at most 1000 characters".
    - `"   "` raises "Please describe the problem".
  - `test_render_enquiry_received`: the subject is "We've got your enquiry". The text contains the customer's name, `AB12 CDE · Ford Focus` and the description. It contains no `/booking/`.
  - `test_render_enquiry_declined_with_and_without_reason`: with a reason, the text contains `Reason: Too busy this month`. Without one, there's no `Reason:` line. Either way it contains the garage phone number.
  - `test_enquiry_email_escapes_description`: a description `<script>alert(1)</script>` appears in the HTML as `&lt;script&gt;`.
  - `test_outbox_sends_enquiry_emails` (integration): queue both templates for a declined enquiry and run `send_due_emails`. Both are sent to the enquiry's email.
  - `test_outbox_sends_received_after_decline`: received is still sent after the enquiry is declined.
- [ ] **Step 2: Run them.** Expected: FAIL (import errors).
- [ ] **Step 3: Implement.** The templates follow `declined.*.j2`: the shared layout and `_footer.txt.j2`. They show the car line and the description (received) or the reason (declined). The declined email says "If you'd like to talk it through, please call us on {phone}." The received email says the garage will be in touch by phone or email.
- [ ] **Step 4: Run the backend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `backend - enquiry rules and emails`

### Task 3: Customer sends an enquiry

**Files:**
- Create: `backend/app/enquiries/actions.py`, `backend/app/api/enquiries.py`
- Modify: `backend/app/main.py` (include the router under `/api`), `backend/tests/factories.py`
- Test: create `backend/tests/integration/test_enquiries_api.py`

**Interfaces:**
- Consumes: Task 2's `clean_description` and `queue_enquiry_email`.
- Produces:
  - `@dataclass(frozen=True) class EnquiryDetails: name, phone, email, registration, make, model, description: str` in `actions.py`.
  - `create_enquiry(session, details: EnquiryDetails, now: datetime) -> Enquiry` adds the enquiry and queues `enquiry_received`. It doesn't commit.
  - `POST /api/enquiries`:
    - The body is `EnquiryIn {name, phone, email, registration, make, model, description}`, each with its `clean_*` validator.
    - It returns 201 `EnquirySentOut {email: str}` (the cleaned email, for the sent page).
    - Bad input returns the app's usual 422 `{"detail": "<field>: <message>"}`.
  - `make_enquiry(session, *, status="new", created_at=None, description="Rattle from the front left when braking") -> Enquiry` in `tests/factories.py`. A handled status fills `handled_at` and `handled_by` (it makes a staff user if needed). `converted` also makes a booking.

- [ ] **Step 1: Write the failing tests.**
  - `test_send_enquiry`: 201 with `{"email": "sam@example.com"}`. One `new` enquiry is stored with trimmed fields, and one `enquiry_received` email is queued for it.
  - `test_send_enquiry_missing_description`: 422 with `detail` starting `description:`. Nothing is stored.
  - `test_send_enquiry_bad_email`: 422 `email: Please enter a valid email address`.
  - `test_send_enquiry_needs_no_login_or_origin`: works without a staff cookie.
- [ ] **Step 2: Run them.** Expected: FAIL (404).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the backend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `backend - customer enquiry route`

### Task 4: Staff approve and decline

**Files:**
- Modify: `backend/app/enquiries/actions.py`, `backend/app/schedule/phone.py`
- Test: create `backend/tests/integration/test_enquiry_actions.py`; modify `test_phone_bookings.py` (default source unchanged)

**Interfaces:**
- Consumes: Task 3's `make_enquiry`; `create_phone_booking`, `PhoneDetails` and `SlotUnavailable`.
- Produces:
  - `create_phone_booking(..., now, *, source: Literal["phone", "enquiry"] = "phone") -> Booking`. Its `booking.create` audit `after` gains `"source"`.
  - `class EnquiryNotNew(Exception)` in `actions.py`.
  - `approve_enquiry(session, staff, enquiry_id: int, services, start, bay_id, details: PhoneDetails, now) -> Enquiry`:
    - It raises LookupError (unknown), EnquiryNotNew, or SlotUnavailable, and in that last case changes nothing.
    - It locks the enquiry `FOR UPDATE`, creates the booking with `source="enquiry"`, and sets `status="converted"`, `booking`, `handled_at=now` and `handled_by=staff.id`.
    - It records `enquiry.approve` with `booking_reference`.
  - `decline_enquiry(session, staff, enquiry_id: int, reason: str | None, now) -> Enquiry`:
    - It locks the row, sets `declined` and the reason, queues `enquiry_declined` with `context={"reason": reason}`, and records `enquiry.decline` with `reason`.
  - Neither action commits.

- [ ] **Step 1: Write the failing tests.**
  - `test_approve_makes_confirmed_no_deposit_booking`:
    - The booking has `status="confirmed"`, `source="enquiry"`, `deposit_status="not_required"` and the given time and bay, and its email is the one given.
    - The enquiry is `converted` and linked, with `handled_by` set.
    - One `confirmation` email is queued for the booking.
    - The audit has `booking.create` and `enquiry.approve`.
  - `test_approve_taken_slot_leaves_enquiry_new`: make a confirmed booking in that bay and time first. SlotUnavailable is raised. After `session.rollback()` the enquiry is `new`, with no booking, no `enquiry.approve` entry and no email queued.
  - `test_decline_with_reason`: `declined`, with `decline_reason` set. One `enquiry_declined` email with `context == {"reason": "Too busy this month"}`.
  - `test_decline_without_reason`: the reason is None.
  - `test_not_new_refused`, parametrized over `converted` and `declined` × approve and decline: each raises EnquiryNotNew.
  - `test_two_approvals_make_one_booking`: two sessions approve the same enquiry at different free times, using the threading pattern from `test_hold_concurrency.py`. Exactly one succeeds and the other raises EnquiryNotNew. One booking has `source="enquiry"`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the backend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `backend - approve and decline enquiries`

### Task 5: Staff enquiry routes, and the booking's link back

**Files:**
- Create: `backend/app/api/staff_enquiries.py` (a router with prefix `/staff` and the same `check_origin` and `current_staff` dependencies as `staff_bookings.py`)
- Modify:
  - `backend/app/main.py`
  - `backend/app/api/staff_bookings.py`:
    - Pull the mixed-services and past-start checks out of `create_booking` into `check_new_booking(services, start, now) -> None`.
    - `StaffBookingOut` gains `enquiry_id: int | None`.
    - `_history_text` takes the booking's source, so `booking.create` reads "Booked from an enquiry by {who}" for source `enquiry`.
- Test: create `backend/tests/integration/test_staff_enquiries_api.py`; modify `test_staff_route_guards.py` and `test_staff_booking_changes.py` (or wherever the booking page history is tested)

**Interfaces:**
- Consumes: Tasks 3 and 4.
- Produces:
  - `GET /api/staff/enquiries?status=new|converted|declined` (default `new`, otherwise 422) returns `list[EnquiryRowOut]`.
    - `EnquiryRowOut = {id, status, customer_name, registration, make, model, summary, created_at, handled_at: str | None}`.
    - `summary` is the description's first line, cut to 80 characters.
    - Times are garage-local ISO via `local_iso`.
  - `GET /api/staff/enquiries/{id}` returns `StaffEnquiryOut`, or 404 "No such enquiry".
    - `StaffEnquiryOut = {id, status, customer_name, customer_phone, customer_email, registration, make, model, description, created_at, handled_at, handled_by: str | None (name), decline_reason, booking_reference: str | None, actions: list["approve" | "decline"]}`.
  - `POST /api/staff/enquiries/{id}/approve`:
    - The body is `EnquiryApproveIn`, which is `PhoneBookingIn` with `email: Annotated[str, AfterValidator(clean_email)]` (required).
    - It returns `StaffEnquiryOut`.
    - Errors: 404; 409 `not_new`; 409 `TAKEN` when the slot is taken (rolling back first); and the `check_new_booking` 422s.
  - `POST /api/staff/enquiries/{id}/decline` with `CancelIn` returns `StaffEnquiryOut`. Errors: 404 and 409 `not_new`.

- [ ] **Step 1: Write the failing tests.**
  - `test_list_new_oldest_first`: three new enquiries come back in `created_at` order. Handled ones aren't listed.
  - `test_list_handled_newest_first`: `?status=declined` returns declined enquiries by `handled_at` descending. `?status=converted` likewise.
  - `test_list_bad_status`: `?status=open` returns 422.
  - `test_detail`: all fields are returned. A new enquiry has `actions == ["approve", "decline"]`, a converted one has `[]` and its `booking_reference`, and an unknown id returns 404.
  - `test_approve_route`:
    - 200, with `status == "converted"` and a `booking_reference`.
    - `GET /api/staff/bookings/{ref}` then shows `source == "enquiry"`, `enquiry_id == id`, and the first history line "Booked from an enquiry by Sam Staff".
  - `test_approve_needs_email`: a blank email returns 422.
  - `test_approve_taken_returns_409`: the detail is `TAKEN`, and the enquiry is still new.
  - `test_approve_and_decline_not_new`: each returns 409 `{"detail": "not_new"}`.
  - `test_decline_route`: 200, `declined`, with the reason given.
  - Route guards: add the four paths to the logged-out (401) and bad-origin (403) lists.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the backend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `backend - staff enquiry routes`

### Task 6: Public enquiry page

**Files:**
- Create: `frontend/src/enquiry/EnquiryPage.tsx`, `frontend/src/enquiry/EnquiryPage.test.tsx`, `frontend/src/enquiry/api.ts`
- Modify:
  - `frontend/src/App.tsx`: add the route `/enquiry`. Under the service list, `CataloguePage` gets a paragraph: "Not sure what's wrong?", then a link "Describe the problem" to `/enquiry`, then "and we'll get back to you."
  - `frontend/src/booking/validation.ts`: export `checkDescription(value: string): string | null`, with the backend's messages.
  - `App.test.tsx`
  - `App.css` (as needed)

**Interfaces:**
- Consumes: Task 3's route.
- Produces:
  - `EnquiryDetails = Omit<CustomerDetails, 'notes'> & { description: string }`.
  - `sendEnquiry(details: EnquiryDetails): Promise<Result<{ email: string }>>` in `enquiry/api.ts`, using `request` and `post` from `booking/api.ts`.
  - `EnquiryPage({ garage })`. It has the form state and, after sending, the sent state, both on the same route.

- [ ] **Step 1: Write the failing tests.**
  - `the services page links to the enquiry form`: a link "Describe the problem" with href `/enquiry`.
  - `sends the enquiry and shows it was sent`:
    - Fill in Name, Phone, Email, Registration, Make, Model and "Describe the problem", then press "Send enquiry".
    - The POST body equals the trimmed fields.
    - The heading "Enquiry sent" appears, along with text containing the email and the garage phone.
  - `shows each field's problem and sends nothing`: an empty submit shows "Please describe the problem" and the existing details messages, and fetch isn't called.
  - `the send button is disabled while sending`: with a pending fetch, the button is disabled, and a second click makes no second call.
  - `a server error is shown`: a 422 `{detail: "email: Please enter a valid email address"}` shows an alert with that message, without the field name. A network failure shows "Sorry, we couldn't send your enquiry. Please try again, or call us on {phone}."
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Reuse `validateDetails`, leaving out its `notes` key. The description is a textarea with the hint "What happens, when it happens, and any warning lights or noises." and `maxLength` 1000.
- [ ] **Step 4: Run the frontend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `frontend - public enquiry form`

### Task 7: Staff Enquiries list, page and decline

**Files:**
- Create: `frontend/src/staff/enquiries/EnquiriesPage.tsx`, `EnquiryPage.tsx`, and their `.test.tsx` files
- Modify:
  - `frontend/src/staff/StaffApp.tsx`: the routes `enquiries` and `enquiries/:id`.
  - `StaffLayout.tsx`: the "Enquiries (n)" link after Requests, fetched with the requests count.
  - `api.ts`, `types.ts`, `labels.ts`
  - `admin/AuditPage.tsx`: `enquiry.approve` → "Booked enquiry", `enquiry.decline` → "Declined enquiry".
  - `staff.css`
- Test: `RequestsPage.test.tsx` (the nav tests now also stub `GET /api/staff/enquiries`), `AuditPage.test.tsx`, and any other test whose stubbed routes now miss the enquiries call.

**Interfaces:**
- Consumes: Task 5's routes.
- Produces:
  - In `types.ts`: `EnquiryStatus = 'new' | 'converted' | 'declined'`, `StaffEnquiryRow`, and `StaffEnquiry`, matching Task 5's shapes.
  - In `api.ts`, all returning `StaffResult`:
    - `fetchEnquiries(status: EnquiryStatus = 'new')`
    - `fetchEnquiry(id: number)`
    - `approveEnquiry(id: number, booking: PhoneBookingIn & { email: string })`
    - `declineEnquiry(id: number, reason: string | null)`
  - `ENQUIRY_STATUS_LABEL: Record<EnquiryStatus, string> = { new: 'New', converted: 'Booked', declined: 'Declined' }` in `labels.ts`.

- [ ] **Step 1: Write the failing tests.**
  - `lists new enquiries, oldest first`: at `/staff/enquiries`, the heading is "Enquiries". The New tab is selected. Each row has a link with the customer name, href `/staff/enquiries/{id}`, the car line, the summary and "Sent {Wed 18 Nov, 09:00}".
  - `the tabs show booked and declined`: clicking "Declined" fetches `?status=declined`, puts `?status=declined` in the URL, and shows "Handled {time}". An empty tab shows "No declined enquiries."
  - `the menu shows how many enquiries are new`: "Enquiries (2)", and plain "Enquiries" for none.
  - `an enquiry page shows the details and its actions`: the heading is "Enquiry · New". The phone, email, car and full description are shown. "Approve and book" is a link to `/staff/enquiries/{id}/book`, and there's a button "Decline".
  - `decline takes an optional reason`: type a reason, press "Decline enquiry". The body is `{reason}`, and the heading becomes "Enquiry · Declined" with "Declined by Sam Staff".
  - `decline already handled says so`: a 409 `not_new` shows the alert "This enquiry has already been dealt with".
  - `a booked enquiry links to its booking`: the heading is "Enquiry · Booked", there's a link to `/staff/bookings/{ref}`, and there are no actions.
  - Audit page: the two new action labels.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the frontend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `frontend - staff enquiries queue`

### Task 8: Book an enquiry, and its booking

**Files:**
- Create: `frontend/src/staff/enquiries/BookEnquiryPage.tsx` and its test
- Modify:
  - `frontend/src/staff/forms/NewBookingPage.tsx`: an optional `enquiry?: StaffEnquiry` prop.
  - `StaffApp.tsx`: the route `enquiries/:id/book`.
  - `booking/BookingDetailPage.tsx`: a "From enquiry" link when `enquiry_id` is set.
  - `labels.ts`: `NO_DEPOSIT_NOTE: Record<'phone' | 'enquiry', string>`.
  - `schedule/parts.tsx`: the note uses `NO_DEPOSIT_NOTE` by source.
  - `types.ts`: `source` gains `'enquiry'`; `StaffBooking.enquiry_id`.
  - `enquiries/EnquiryPage.tsx`: shows the notice from navigation state.
- Test: `NewBookingPage.test.tsx` (unchanged behaviour without the prop), `BookingDetailPage.test.tsx`, `DayView.test.tsx`

**Interfaces:**
- Consumes: Task 7's `fetchEnquiry` and `approveEnquiry`.
- Produces:
  - `BookEnquiryPage` loads the enquiry and renders `<NewBookingPage enquiry={enquiry} />`. An enquiry that isn't new shows "This enquiry has already been dealt with", with a link back.
  - With `enquiry`, `NewBookingPage` behaves like this:
    - The heading is "Book enquiry".
    - The details start from the enquiry, and the notes start as the description.
    - The email label is "Email", and a blank email is an error.
    - Submitting calls `approveEnquiry`.
    - On success it navigates to `/staff/enquiries/{id}` with state `{ notice: 'Booked — the customer has been emailed' }`.
    - A 409 `not_new` shows "This enquiry has already been dealt with". A 409 taken behaves as today.

- [ ] **Step 1: Write the failing tests.**
  - `book enquiry starts from the enquiry`:
    - At `/staff/enquiries/7/book`, the heading is "Book enquiry".
    - Name, Phone, Email, Registration, Make and Model hold the enquiry's values, and Notes holds its description.
  - `book enquiry needs an email`: clearing Email and pressing "Book it" shows "Please enter a valid email address", and nothing is sent.
  - `booking it approves the enquiry`:
    - Choose "Diagnostic check" and a time, then press "Book it".
    - POST `/api/staff/enquiries/7/approve` with the phone-booking body, its email included.
    - The page lands on the enquiry page showing "Booked — the customer has been emailed".
  - `already handled says so`: a 409 `not_new` shows the alert "This enquiry has already been dealt with".
  - `a booking from an enquiry links back`: the booking page with `source: 'enquiry', enquiry_id: 7` shows a link "From enquiry" to `/staff/enquiries/7` and the note "From enquiry · no deposit".
  - Day view: an enquiry-source item shows "From enquiry · no deposit". A phone one still shows "Phone booking · no deposit".
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the frontend checks.** Expected: PASS.
- [ ] **Step 5: Commit.** `frontend - book an enquiry`

### Task 9: End-to-end flow 3 and README

**Files:**
- Create: `e2e/tests/enquiry.spec.ts`
- Modify: `README.md`

- [ ] **Step 1: Write the test** `flow 3: an enquiry is booked in`. It needs no Stripe keys. The steps:
  1. Open `/` and click "Describe the problem". Fill in the form with a unique email `sam+${stamp}@example.com` and a unique name `Sam ${stamp}`, so old runs' rows never match. Press "Send enquiry". Expect "Enquiry sent", then `waitForEmail(request, email, /We've got your enquiry/)`.
  2. `loginAs(page, 'staff')`. Open the menu link `/^Enquiries/`, then the row for the customer's name, then "Approve and book".
  3. Choose "Diagnostic check", and pick a date from tomorrow with a free time. Use `staffSlots` from `e2e/tests/staff.ts` to find the first day with a slot. Pick the first time and press "Book it".
  4. Expect "Booked — the customer has been emailed" and the heading "Enquiry · Booked".
  5. `waitForEmail(request, email, /Your booking is confirmed/)`. Take the booking link with the `LINK` pattern from `approval-booking.spec.ts`, and open it. Expect "Your booking is confirmed", and no "Pay deposit" button.
- [ ] **Step 2: Run it against the rebuilt stack.** Run the end-to-end commands from Global Constraints. Expected: `enquiry.spec.ts` passes, then the whole suite passes (9 tests).
- [ ] **Step 3: Update README.md.** Add flow 3 to the flows list, and a line on the Enquiries page beside the Requests line.
- [ ] **Step 4: Commit.** `e2e - enquiry flow; readme`
