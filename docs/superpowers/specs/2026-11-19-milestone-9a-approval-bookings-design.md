# Milestone 9a: Approval Bookings — Design

Nov 19, 2026 · Adam Ornoch

Spec: [docs/SPEC.md](../../SPEC.md), flow 2 ("Booking that needs approval") and "Build order" item 9. Builds on Milestones 5 (deposits), 6 (email and booking links) and 7 (staff back office).

## Intent

Some services need a look before the garage commits to them: a diagnosis, a clutch, a timing belt. Today a customer can't book those online at all; the services page says "Needs approval — call us", and the booking API refuses them ([holds.py](../../../backend/app/api/holds.py)). Only staff can book them, over the phone.

This milestone lets the customer **ask** for one online. They pick a time and give their details as usual, but don't pay. The time is kept for them while staff look at the request. Staff then:
- **approve** it as asked,
- **propose another time** (after phoning the customer, the Milestone 7 way), or
- **decline** it.

Each outcome emails the customer. An approval (or a proposal) asks for the £20 deposit through the customer's booking link, and paying confirms the booking, exactly like an instant booking from then on.

**Done when:**
- A customer can request a needs-approval service from the public site, and it appears in the staff queue.
- Staff can approve, propose another time, or decline it, and each sends the right email.
- The customer pays the deposit from their booking link and the booking is confirmed.
- A request staff don't answer in time, and an approval the customer doesn't pay in time, both free the slot and email the customer.
- Flow 2 passes end to end in CI.

Milestone 9b (enquiries for unknown issues) comes next, with its own design. It reuses this milestone's staff queue and its pending booking.

## Changes to the spec

Adam decided these on Nov 19. Update `docs/SPEC.md` as part of this milestone (the photo removal is done already, with this design):
- **Milestone 9 is split** into 9a (approval bookings) and 9b (enquiries).
- **Enquiries have no photos**: structured fields and a description only. No object storage.
- **"Propose another time"**: staff phone the customer, then pick the new time and approve it in one step. The customer accepts by paying the deposit. There's no separate accept or reject step.
- **The deposit is paid from the booking link** in the approval email, with the same in-page payment form as an instant booking.
- **Waiting times:** a request keeps its slot for up to 48 hours while staff decide; after approval, the customer has 24 hours to pay. A request must be for a slot at least 24 hours ahead, and the customer always gets at least 2 hours to pay. All are setup data, not admin settings. This answers the open question "Needs-approval hold".
- **A new booking status, "awaiting deposit"**, between approval and payment.

## Goals

- Customers can ask for any active service online, not just instant ones.
- Staff see every waiting request in one place, oldest first, with how long is left.
- The payment, confirmation, refund and cancellation rules after payment are exactly those of an instant booking.
- No request or approval keeps a slot forever.

## Non-goals

- **Enquiries** (unknown issues): Milestone 9b.
- **Emailing the garage** when a request comes in. The staff queue and a count in the staff navigation are enough for a demo; the garage email can come later.
- **A customer accept or reject page** for a proposed time. Paying accepts; not paying, cancelling from the link, or phoning declines.
- **Admin-editable waiting times.** They're setup data like the other booking rules.
- **Changing services or details** on a request. Staff decline, or phone the customer and make a phone booking.

## Anti-goals

- A request that quietly expires without the customer being told.
- A customer paying for a time that's no longer theirs and not getting the money back (the existing late-payment rules must cover this status too).
- Two ways to pay. The approved deposit uses the same provider calls, webhook and confirmation email as an instant one.

## Decisions made with Adam

- Photo upload is dropped from enquiries (Nov 19).
- 9a and 9b are separate milestones, each with its own design, plan and PR (Nov 19).
- "Propose another time" and the waiting times were left to Claude; the choices are in "Changes to the spec" above (Nov 19). So were the 24-hour notice for requests, the 2-hour minimum to pay, and the payment-form rules below; they're Claude's calls.
- The customer pays from their booking link (approach A below), chosen Nov 19.

## Approaches considered for paying after approval

- **A. Pay from the booking link (chosen).** The approval email carries the Milestone 6 booking link. That page shows "Pay £20 deposit", which opens the Milestone 5 in-page payment form. It reuses the link, checkout, webhook and confirmation email, and adds one state to the booking page.
- **B. A Stripe-hosted payment link in the email.** The customer pays on Stripe's page. That's a second payment path with its own webhook handling and redirects, built only for this flow.
- **C. Take the deposit upfront and refund it on decline.** Simplest for staff, but it goes against the spec ("requested after approval"), and every decline costs a refund.

## The booking's life

```
held ──send request──▶ pending_approval ──approve / propose──▶ awaiting_deposit ──pay──▶ confirmed
  │ (5-min hold, as today)     │                                    │
  ▼                            ├─decline──▶ cancelled              ├─deadline passes──▶ expired
expired                        ├─customer cancels──▶ cancelled     ├─customer cancels──▶ cancelled
                               └─deadline passes──▶ expired        ├─staff propose again──▶ awaiting_deposit (new deadline)
                                                                    └─staff cancel──▶ cancelled
```

- **New status `awaiting_deposit`.** It counts as taking its time, like `pending_approval` (add it to `COUNTING_STATUSES` and to whatever keeps a reservation live).
- **Deadlines live in `hold_expires_at`**, which `pending_approval` and `awaiting_deposit` must both have (extend the `held_has_expiry` check).
- **Request deadline:** the earlier of *sent + 48 hours* and *start − booking cut-off* (2 hours).
- **Payment deadline:** the earlier of *approved + 24 hours* and *start − booking cut-off*.
- **Requests need notice:** a request's slot must start at least 24 hours ahead, so staff always have a real chance to answer. The public time picker offers only those slots when the visit needs approval.
- **The customer always gets at least 2 hours to pay:** staff can't approve, or propose a time, when the payment deadline would be less than 2 hours away. The propose picker uses staff free times (no customer cut-off), but refuses a time that's too close for that, with "Too soon for the customer to pay — choose a later time".
- **Settings:** `approval_hold_hours` (48), `approval_payment_hours` (24), `approval_lead_hours` (24) and `approval_min_payment_hours` (2), seeded with the other booking rules.
- **Past the deadline counts as expired at once**, as a hold does today: availability, the booking link and staff actions treat it as expired before the worker gets to it.

## The customer's side

**Services page.** A needs-approval service shows "Needs approval" (not "call us") and can be chosen. If any chosen service needs approval, the whole visit is a request (the spec's existing rule). Mixed bay types are still refused.

**Booking page.** The same steps as an instant booking: pick a time (the usual 5-minute hold), then details. For a request:
- The details step explains that the garage will check the request and email within 48 hours, and that the £20 deposit is asked for only after approval.
- The button says **"Send request"**, and there's no payment step.
- Sending turns the held booking into `pending_approval` with its deadline, keeps the details, and queues a **"request received"** email with a booking link.
- The page then shows "Request sent" with the reference.

**Booking link page** gains two states:
- **Pending:** "We're checking your request and will email you by {deadline}." A Cancel button (nothing is paid, so nothing to refund).
- **Awaiting deposit:** the time (the new one, after a proposal), "Pay the £20 deposit by {deadline} to confirm", a **Pay deposit** button that opens the same embedded form as the booking page, and a Cancel button.
- After payment the page shows the confirmed booking, as today.

## The staff side

**Requests page** at `/staff/requests`, for every staff member (not admin only). A **Requests** link in the staff navigation shows the count of waiting requests. The page lists `pending_approval` bookings oldest first: reference, customer, services, requested time and bay, and time left. Each links to the booking's page. Milestone 9b adds enquiries to this page.

**Booking page** (Milestone 7), for a `pending_approval` booking:
- **Approve:** confirm, then the booking becomes `awaiting_deposit` and the customer gets the approval email.
- **Propose another time:** "Phone the customer first" (as for a move), then the Milestone 7 move picker. Saving moves the booking and approves it in one step: `awaiting_deposit`, a new payment deadline, and the "new time proposed" email.
- **Decline:** an optional reason, confirm, then `cancelled` and the decline email (with the reason, if given).

For an `awaiting_deposit` booking: **Propose another time** (resets the payment deadline and sends the email again) and the usual **Cancel**. Job status buttons (in progress, completed, no show) stay for confirmed bookings only.

**Schedule.** Day and week views show requests and awaiting-deposit bookings in their slot, marked differently from confirmed ones ("Request", "Awaiting deposit").

**Audit.** New actions `booking.approve`, `booking.propose` (before and after time and bay) and `booking.decline` (with the reason), in the same transaction, with who did it. The audit page describes them in words, like the others.

## Emails

New templates, in the existing style (HTML and text, with the booking link where there's something to do):

| Template | When | Says |
| --- | --- | --- |
| `request_received` | Customer sends a request | What was asked for, the time, "we'll reply by {deadline}", link |
| `approved` | Staff approve | Confirmed time, pay £20 by {deadline} to confirm, link |
| `proposed` | Staff propose a time | We can't do {old}, we can do {new}; pay by {deadline} to confirm, or call us; link |
| `declined` | Staff decline | Sorry, reason if given, call us |
| `request_expired` | Request deadline passes | Sorry we couldn't reply in time, please call us |
| `deposit_expired` | Payment deadline passes | The time has been released, please call us |

Payment then sends the existing `confirmation` email. A customer cancelling a request or an awaiting-deposit booking gets the existing `cancellation` email, worded for no deposit.

## API

Public (no login), alongside the existing hold endpoints:
- `POST /api/holds` accepts needs-approval services (the refusal goes).
- `POST /api/holds/{reference}/request` with the hold token and the same details as checkout: turns the hold into a request. 409 if the hold has expired.

Booking link (token in the body, as today):
- The existing view returns the new states and the deadline.
- `POST /api/my-booking/{reference}/pay` opens or reuses the deposit form for an `awaiting_deposit` booking. It returns what the booking page's checkout returns.
- The existing view completes a payment the provider already has, like `hold_status` does, so the page doesn't depend on the webhook.
- Cancel works for `pending_approval` and `awaiting_deposit` at any time.

Staff (logged in, origin checked):
- `GET /api/staff/requests`: the queue. The navigation count comes from the same data.
- `POST /api/staff/bookings/{reference}/approve`
- `POST /api/staff/bookings/{reference}/propose` with the new start and bay (the move body).
- `POST /api/staff/bookings/{reference}/decline` with an optional reason.

Each refuses a booking in the wrong status with 409 and changes nothing.

## Payment rules for awaiting deposit

- `complete_deposit` confirms an `awaiting_deposit` booking just as it confirms a `held` one.
- Opening a payment form must **not** shorten the payment deadline. Today `start_checkout` resets `hold_expires_at` to the 10-minute form time; for an awaiting-deposit booking the deadline stays put, and the form's own lifetime is the provider session's, as today. A later click reuses an open form or opens a new one.
- When the booking expires, is proposed a new time, or is cancelled, its open form is closed (the worker retries a close that fails, as today).
- A payment that arrives after the deadline follows the existing rule for an expired hold: the booking is confirmed if its time is still free, otherwise the deposit is refunded.
- A payment that gets in on a booking that's been cancelled or moved meanwhile is refunded, never kept silently (today `complete_deposit` keeps a payment on a cancelled booking; that changes for these statuses).

## Expiry

The worker already releases expired holds every cycle. It also expires `pending_approval` and `awaiting_deposit` bookings past their deadline: status `expired`, the time freed, the open payment form closed, and the `request_expired` or `deposit_expired` email queued in the same transaction.

## Racing

Approve, propose, decline, customer cancel, payment and expiry can all hit the same booking. They follow the Milestone 8 lock order: the shared hours-and-bays lock first, then the booking row `FOR UPDATE`, then a re-check of the status. The loser gets a 409 (staff and customer) or does nothing (worker). Propose also re-checks the new time is free, as move does.

## Testing

- **Unit:** the two deadlines (48 hours, 24 hours, cut by the cut-off); the 24-hour notice; the 2-hour minimum to pay for approve and propose.
- **API:** each endpoint's happy path and its wrong-status 409; request with an expired hold; pay with a bad link (404); staff routes need a login and the origin check.
- **Payments:** an awaiting-deposit payment confirms; a late payment is taken back or refunded; a form never outlives the deadline.
- **Worker:** both expiries free the time and queue the right email, once.
- **Concurrency:** approve against customer cancel (one wins); payment against expiry.
- **Emails:** each new template renders with the right time, deadline and link.
- **Frontend:** services page selection; the request steps; both booking-link states; the Requests page and count; approve, propose and decline on the booking page; audit wording.
- **End to end (flow 2):** a customer requests a needs-approval service; staff approve it from the Requests page; the customer opens the link from Mailpit, pays through the Stripe test form, and sees the booking confirmed.

## Left to the builder

- The migration (new status, settings, check constraints) and the exact column use, as long as the rules above hold.
- Whether the request and pay endpoints share code with `start_checkout` and `hold_status`, or sit beside them.
- The exact wording of emails and pages, in the style of the existing ones.
- How the Requests count refreshes (on navigation is enough).
