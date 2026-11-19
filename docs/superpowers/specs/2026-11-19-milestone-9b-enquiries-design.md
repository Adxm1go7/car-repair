# Milestone 9b: Enquiries — Design

Nov 19, 2026 · Adam Ornoch

Spec: [docs/SPEC.md](../../SPEC.md), flow 3 ("Diagnosis enquiry (unknown issue)") and "Build order" item 9b. Builds on Milestone 7 (staff back office and phone bookings) and Milestone 9a (the staff queue pattern and approval emails).

## Intent

A customer whose car has a problem they can't name can't pick a service, so they can't book. This milestone gives them a form to **describe the problem**, with no time slot and no payment. The enquiry lands in a staff queue. Staff read it, phone the customer if they need to know more, and then either:
- **approve** it by booking the customer in: they pick the service, time and bay, like a phone booking, or
- **decline** it, with an optional reason.

Each outcome emails the customer. An approved enquiry becomes a confirmed booking with no deposit, as a phone booking would. The customer gets the usual confirmation email with their booking link.

**Done when:**
- A customer can send an enquiry from the public site and gets an email saying it arrived.
- It appears in the staff queue as new, with a count in the staff menu.
- Staff can approve it into a confirmed booking or decline it, and each sends the right email.
- Flow 3 passes end to end in CI.

## Changes to the spec

Adam decided these on Nov 19. They're already made in `docs/SPEC.md`, with this design:
- **The form is just a description of the problem.** There are no symptoms or urgency fields, and no photos. Contact and car details stay, the same fields as the booking form.
- **No "ask for more information" action.** Staff phone the customer, outside the app.
- **Approving books the customer in**, confirmed at once with no deposit, like a phone booking.
- **Enquiry statuses** are now: new, converted to booking, declined.

## Goals

- A customer with an unknown problem has an obvious way to get in touch online.
- Staff see every new enquiry in one place, oldest first.
- Approving takes staff straight from the enquiry to a booking without retyping the customer's details.
- The booking that results behaves exactly like a phone booking: the same emails, link, moves, cancellation and job status.

## Non-goals

- **Asking for more information in the app**, and any customer reply page. Staff phone them.
- **A customer page for an enquiry.** There's no token link for an enquiry. The customer gets a link once a booking exists.
- **Expiry.** An enquiry stays new until staff act on it.
- **Emailing the garage** when an enquiry arrives. The queue and the menu count are enough, as in 9a.
- **Spam protection** (rate limiting, honeypot). That's Milestone 10, as the spec's checklist says.
- **Editing or deleting an enquiry**, and retention of old ones (Milestone 10's privacy item).
- **A deposit** for the resulting booking.

## Anti-goals

- An enquiry approved twice, giving two bookings, or approved after it was declined.
- A customer told nothing: every enquiry gets a "received" email and then exactly one outcome email.
- A second booking-creation path. Approving goes through the phone-booking code (`create_phone_booking` in [phone.py](../../../backend/app/schedule/phone.py)), not a copy of it.

## Decisions made with Adam

- Description only, no symptoms, urgency or photos (Nov 19).
- No "ask for more information"; staff phone (Nov 19).
- The approved booking is confirmed straight away with no deposit, option (b) (Nov 19).
- The approach and outline below, approved Nov 19.
- Handled enquiries stay findable: the Enquiries page has New, Booked and Declined tabs (Nov 19).

## Approaches considered

- **A. A separate `enquiries` table; approving reuses the phone booking (chosen).** The enquiry holds the customer's details and description. Approving runs the phone-booking code and links the new booking back to the enquiry.
- **B. Store an enquiry as a booking with an "enquiry" status.** This doesn't fit: every booking owns a reserved time slot, and an enquiry has none. It would also leak a slot-less row into every schedule and booking query.
- **C. An enquiry form that only sends an email to the garage.** Cheapest, but there's no queue, no status and no conversion, so flow 3 isn't met.

## The enquiry's life

```
new ──approve──▶ converted to booking   (a confirmed booking exists, linked)
 └───decline──▶ declined
```

Both are final. Approving or declining something no longer new is refused (409 `not_new`). The two staff actions lock the enquiry row (`FOR UPDATE`) first, so two staff acting at once get one success and one `not_new`.

## Data

A new table `enquiries` (migration 0011):
- `id`, `status` (`new`, `converted`, `declined`; check constraint), `created_at`.
- The customer: `customer_name`, `customer_phone`, `customer_email`, `car_registration`, `car_make`, `car_model`, all required. They use the same lengths as `bookings` and the same `clean_*` rules as the booking form. Email is required here, unlike a phone booking, because the outcome is sent by email.
- `description`: text, required, 10 to 1000 characters after trimming. *(Claude's call. 1000 matches the booking notes limit in `clean_notes`, so a description always fits the approve form's notes, which start as the description.)*
- `handled_at`, `handled_by` (staff user), `decline_reason` (optional, up to 500 characters), `booking_id` (unique, nullable).
- Check constraints: `booking_id` is set if and only if the status is `converted`; `handled_at` and `handled_by` are set if and only if the status isn't `new`.

Changes to existing tables, in the same migration:
- `bookings.source` gains `enquiry`. The rule that only phone bookings may have `deposit_status = 'not_required'` widens to phone or enquiry.
- `email_logs` gains `enquiry_id`. The "exactly one subject" rule now covers booking, staff user or enquiry.
- The email template check gains the two new templates below.

## The customer's side

- **A new public page, `/enquiry`**, titled "Ask about a problem". It's linked from the services page with a line like "Not sure what's wrong? Describe the problem and we'll get back to you."
  - The fields are name, phone, email, registration, make, model, and "Describe the problem". The description is a textarea with a short hint: what happens, when, and any warning lights or noises.
  - Validation messages match the booking form.
- **On sending**, the page shows "Enquiry sent": we've got it, the garage will be in touch by phone or email, and the garage's phone number.
- **Email `enquiry_received`**: confirms what they sent (car and description) and says the garage will be in touch. It has no link.
- **Email `enquiry_declined`**: says the garage can't take it on, with the reason if staff gave one, and the garage's phone number. It has no link.
- **On approval**, the customer gets the existing `confirmation` email for the new booking, with its booking link. From there it's an ordinary confirmed booking with no deposit.

## The staff side

- **Menu link "Enquiries (n)"**, showing how many are new and no count when there are none, like "Requests (n)".
- **`/staff/enquiries`** has three tabs:
  - **New** (the default): oldest first.
  - **Booked:** newest handled first.
  - **Declined:** newest handled first.
  - Each row shows the name, the car (registration, make and model), the first line of the description, and when it was sent; handled ones also show when they were handled. Each row links to its page.
  - An empty tab says so, for example "No new enquiries." The tab is kept in the URL (`?status=`), so the back button returns to it.
- **`/staff/enquiries/:id`** shows the status, the contact and car details, the full description and when it was sent. For a new enquiry it has two actions:
  - **Approve and book:** opens a booking form filled in from the enquiry. Staff choose the services and a time and bay with the same picker as a phone booking (`TimePickerGrid`), and can correct the details. The notes start as the description. The email can't be blanked. Confirming creates the booking, and the page then says "Booked — the customer has been emailed", with a link to the booking.
  - **Decline:** an optional reason, then "Decline enquiry". Afterwards the page shows it as declined.
- **A handled enquiry** shows who handled it and when, and, if converted, links to its booking.
- **The booking's history** shows "Booked from an enquiry by {staff}" where a phone booking says "Booked by phone by {staff}". It links back to the enquiry.
- **The staff URL uses the enquiry's id.** The customer is never shown an enquiry reference. *(Claude's call: there's no customer page to look one up on, and staff find a caller by name.)*

## API

Public:
- `POST /api/enquiries`: the details and description. It returns 201 and queues `enquiry_received`. It returns 422 with field errors in the booking form's shape.

Staff (logged in, any role):
- `GET /api/staff/enquiries?status=new|converted|declined`: the status defaults to `new`. New ones come oldest first; handled ones come newest `handled_at` first, capped at the latest 100. *(Claude's call on the cap. There's no paging, as with the audit page.)* Any other status returns 422.
- `GET /api/staff/enquiries/{id}`: one enquiry, with its status, `handled_by` name, `handled_at`, `decline_reason`, booking reference, and `actions` (`["approve", "decline"]` when new, otherwise `[]`).
- `POST /api/staff/enquiries/{id}/approve`: the body is the phone-booking body (services, start, bay_id and the details, email required). It creates the booking through `create_phone_booking`, with source `enquiry`. It sets the enquiry converted, links it, and audits `enquiry.approve`, alongside the booking's own `booking.create` entry. It returns the enquiry. Errors are the phone booking's (slot taken, mixed services) plus 409 `not_new`.
- `POST /api/staff/enquiries/{id}/decline`: `{reason: string | null}`. It sets the enquiry declined, queues `enquiry_declined`, audits `enquiry.decline`, and returns the enquiry. 409 `not_new`.

## Emails

- The two new templates follow the existing ones (HTML and text, the shared layout and footer).
- Enquiry emails are sent by the worker like the others. The outbox needs an enquiry path beside the booking and staff ones.
- An `enquiry_received` email still queued when staff act is still sent. It's accurate when it was written, and the outcome email follows. *(Claude's call.)*

## Testing

- Unit tests:
  - the description rules;
  - the enquiry and booking constraints (migration-level);
  - the outbox rendering both templates.
- API tests:
  - sending an enquiry (good, missing fields, description too short or long) queues one email;
  - the staff list for each status, in its order, and a bad status returning 422;
  - approve creates a confirmed, no-deposit booking with source `enquiry`, links it, queues `confirmation`, and audits;
  - a slot taken returns the phone booking's error and leaves the enquiry new;
  - decline with and without a reason;
  - `not_new` for both actions after either;
  - two approves at once: one booking.
- Frontend tests (Vitest): the public form and its sent page; the staff list and its tabs, the menu count, the enquiry page, approve and decline.
- End to end (Playwright), flow 3:
  1. The customer sends an enquiry and the received email arrives.
  2. Staff log in, open Enquiries, open it, approve it with "Diagnostic check" at a free time, and confirm.
  3. The confirmation email arrives with a booking link.
  4. The link page shows the booking confirmed, with no deposit to pay.

## Left to the builder

- Module and component layout, following 9a's (for example `app/enquiries/` for the rules and actions, `frontend/src/enquiry/` and `frontend/src/staff/enquiries/`).
- Whether the approve form is a panel on the enquiry page or a reuse of the new-booking page with the enquiry passed in. Either way, the time picker and the validation are shared, not copied.
- Exact wording of the emails and page copy, within the meanings above.
- How the enquiry page is reached from a converted booking's page, as long as one link exists each way.
