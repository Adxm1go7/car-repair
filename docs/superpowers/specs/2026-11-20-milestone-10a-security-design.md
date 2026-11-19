# Milestone 10a: Security hardening — Design

Nov 20, 2026 · Adam Ornoch

Spec: [docs/SPEC.md](../../SPEC.md), "Security, reliability and privacy checklist" and "Build order" item 10. Builds on every earlier milestone; it changes no flows.

## Intent

The app is a portfolio piece that must show professional standards. Milestone 10 hardens it, and Adam wants that done to a **basic, solid level, nothing extensive or niche** (Nov 20). Milestone 10 is split in two:

- **10a, security (this design):** rate limits and a honeypot on the public forms, security headers, dependency and image scans in CI, and the few security-flavoured fixes left over from earlier milestones.
- **10b, polish (a later design):** error pages, structured logs, an accessibility check, a load test, a privacy note with a retention rule, and ticking the checklist with evidence.

**Done when:**
- Every public form route refuses a visitor who goes over its limit, with a friendly message, and the forms show that message.
- A bot that fills in the hidden honeypot field gets nowhere, and a person never sees the field.
- The site sends the security headers below, and the Stripe payment form still works under them (flows 1, 2 and 4 pass).
- CI fails on a known vulnerability with a fix in the Python packages, or on a high or critical one in the npm packages or the built images.
- The four leftover fixes below are made, each with a test.

## Changes to the spec

Update `docs/SPEC.md` as part of this milestone:
- **Build order:** split item 10 into "10a. Security hardening" (done when this design's list is done) and "10b. Polish" (done when the checklist is fully ticked).
- **Checklist:** tick "Rate limiting and a honeypot or CAPTCHA on the booking and enquiry forms" and "Dependency and container image scanning in CI" when they're done. Ticking the rest is 10b.

## Goals

- Abuse of the public forms costs a bot something, without bothering real customers.
- The browser is told the basics: no sniffing, no framing, a sensible referrer, and a content policy that still lets Stripe's form work.
- A known-vulnerable dependency fails CI before it can ship.
- No public input can cause a server error.

## Non-goals

- **A CAPTCHA**, or any third-party bot service.
- **Rate limits in nginx.** Approach B below was set aside. It could be added later as an outer guard.
- **HTTPS, HSTS and the live-site settings.** These come in Milestone 11 (deployment). HSTS only makes sense once HTTPS exists.
- **Limits on staff routes.** They need a login, and logins are already throttled.
- **A formal security audit**, penetration test or code scanning (SAST).
- **The rest of the small-issues backlog** that isn't security-related.

## Anti-goals

- A real customer hitting a limit while booking normally. This includes picking several times in a row, refreshing, and polling the payment status.
- A honeypot that a screen reader announces or that a password manager fills in.
- A content policy that breaks the Stripe form in some browsers but not in the tests.
- A scan that fails CI on low-severity or unfixable noise every week.

## Decisions made with Adam

- Hardening is kept basic, nothing too extensive (Nov 20).
- The scope list and the split into 10a and 10b were agreed as proposed (Nov 20).
- The rate limits are counted in the database, in the app, like the login throttle (approach A, Nov 20).
- The rate limits are off in development, so local runs never trip them (option (a), Nov 20).

## Approaches considered for rate limiting

- **A. In the app, counted in the database (chosen).** One row per attempt, keyed by action and visitor IP, checked by a helper at the top of each limited route. It's the same pattern as `app/staff/throttle.py`, it's shared by every API process, it survives restarts, it's testable in pytest, and each action gets its own limit.
- **B. nginx `limit_req`.** A few config lines, but only a blunt per-request rate. It only exists in Docker, so pytest can't test it, and it needs a custom 429 reply for the forms.
- **C. A Python library (slowapi).** Counts in memory per process by default, so the counts are wrong with more than one process or after a restart. Fixing that needs Redis.

## Rate limits

**A new table, `request_counts`:**
- **Columns:** `id`, `action` (String(30)), `ip` (String(45)), `at` (timestamptz).
- **Index:** `(action, ip, at)`.
- **Clean-up:** the worker deletes rows older than a day in its existing housekeeping pass, next to `delete_old_attempts`.

**The limits**, all *Claude's call*, set so a normal customer never meets them:

| Action | Routes | Limit per IP |
|---|---|---|
| `hold` | `POST /api/holds` | 30 per 15 minutes |
| `pay` | `POST /api/holds/{ref}/checkout`, `POST /api/bookings/{ref}/pay` | 10 per 15 minutes |
| `request` | `POST /api/holds/{ref}/request` | 5 per hour |
| `enquiry` | `POST /api/enquiries` | 5 per hour |
| `link` | `POST /api/bookings/{ref}/cancel` | 30 per 15 minutes |

- **Unlimited routes:**
  - `POST /api/holds/{ref}/status` is polled while a customer pays.
  - `POST /api/bookings/{ref}/view` is polled once a second while a customer pays from their link, and it's called again on every reload. *(Claude's call, after the builder check: a limit here could block a real customer. The link's random token already makes guessing hopeless.)*
  - `DELETE /api/holds/{ref}` gives back a hold.
  - The demo checkout only exists without Stripe keys.
  - The staff login and forgot-password routes already have their own lockout.
- **How a check works:**
  - It counts the rows for this action and IP inside the window.
  - At or over the limit, the route replies **429** with `{"detail": "Too many attempts. Please wait a few minutes and try again."}` and a `Retry-After` header in seconds. It records nothing and changes nothing.
  - Under the limit, it records one row and carries on.
  - The check runs before any other work, so a refused request never reaches the payment provider or sends email.
- **Counting:** an attempt counts whether it then succeeds or fails, because a failed attempt is still load. The count isn't strictly atomic: two requests at the same moment can both slip in at the limit. That's acceptable for abuse control.
- **The visitor's IP** comes from the existing `client_ip(request)`. Behind nginx, uvicorn's trusted-proxy setting (Milestone 7) already makes that the real visitor's address.
- **The limits are code constants**, like `throttle.py`'s, not admin settings.
- **They apply only when `ENVIRONMENT` is `test` or `production`** (Adam, Nov 20).
  - In `development`, which is what the local Docker stack runs as, the check does nothing and records nothing. Local e2e runs and manual testing never trip it, because all local traffic comes from one IP.
  - The pytest client fixtures in `tests/conftest.py` build `AppConfig(..., environment="test")`, so the suite exercises the limits fully. Today they use the default, which is development. Other behaviour that changes with the environment, such as the extra dev-server origin, must still pass its existing tests. Any test that relied on development gets that setting explicitly.
  - The e2e suite never reaches a limit, in CI or locally.
- **The frontend:** every limited form shows the server's `detail` for a 429. The plan checks each one: picking a time, the details step, sending a request, the enquiry form, paying from the link, and cancelling from the link. None may show a generic error instead.

## Honeypot

- **A hidden text field, `website`**, goes on the details step (checkout and request) and on the enquiry form.
  - It's hidden visually with the existing visually-hidden CSS, not `display: none`, because some bots skip fields that aren't displayed.
  - It has `tabindex="-1"`, `autocomplete="off"` and `aria-hidden="true"`, so keyboards, screen readers and password managers skip it. Its label says "Leave this empty".
- **The API** accepts an optional `website: str | None` on those three bodies.
- **When it's filled in:**
  - **On `POST /api/enquiries`**, the reply is the normal 201 with the email, but nothing is stored and no email is sent. A bot learns nothing.
  - **On checkout and request**, a fake success isn't possible, so the reply is 422 `{"detail": "Please check your details and try again."}` and the hold is left alone.
  - Either way it's logged at warning level, with the route and the IP and no form contents.
- A request that sets the honeypot still counts towards the rate limit.

## Security headers

Set in [frontend/nginx.conf](../../../frontend/nginx.conf) for every reply, `/api/` included, using `add_header ... always`:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`, with `frame-ancestors 'none'` in the content policy as well
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(self "https://js.stripe.com" "https://checkout.stripe.com")`. The checkout frame needs `payment`, or Apple Pay and Google Pay are quietly hidden. *(Claude's call, after the builder check.)* The builder may widen it to what Stripe documents, as for the content policy.
- **`Content-Security-Policy`**, set so Stripe Embedded Checkout works:
  - `default-src 'self'`
  - `script-src 'self' https://js.stripe.com`
  - `frame-src https://js.stripe.com https://checkout.stripe.com`
  - `connect-src 'self' https://api.stripe.com https://checkout.stripe.com`
  - `img-src 'self' data: https://*.stripe.com`
  - `style-src 'self' 'unsafe-inline'`, because React and Stripe set inline styles
  - `font-src 'self'`
  - `object-src 'none'`
  - `base-uri 'self'`
  - `form-action 'self'`
  - `frame-ancestors 'none'`

  *The builder confirms this exact list against Stripe's current documentation for Embedded Checkout, and widens it only as far as flows 1, 2 and 4 need.*
- **Page caching:** `index.html` is served with `Cache-Control: no-cache`, so a new release is picked up. Hashed assets can stay cacheable.

The FastAPI app itself adds `X-Content-Type-Options: nosniff` to its JSON replies, so the API is covered even when it's reached without nginx, as in tests and the dev server.

A CI step checks the headers with `curl -sI http://localhost:8080/` and greps for each one. The e2e suite proves Stripe still works.

## Dependency and image scans (CI)

A new `scan` job in `.github/workflows/ci.yml` (*Claude's call to make it a job of its own*):
- **Python:** `uv export --frozen --no-dev --format requirements-txt`, then `pip-audit`, which fails on any known vulnerability that has a fix, whatever its severity. *(Claude's call, after the builder check: pip-audit can't filter by severity, and Python issues with a fix are rare and fixable. The npm and image scans keep the high-or-critical rule.)*
- **npm:** `npm audit --omit=dev --audit-level=high` in `frontend/` and `e2e/`.
- **Images:** build the `api` and `web` images, then scan each with Trivy (`aquasecurity/trivy-action`, pinned to a version).
  - It reports `HIGH,CRITICAL` only, `ignore-unfixed: true`, and fails with `exit-code: 1`.
- **Allowed exceptions** live in a committed `.trivyignore` and in pip-audit `--ignore-vuln` flags, each with a one-line reason. It starts empty.
- **Anything a scan finds** when this is first built is fixed by upgrading, if that's simple. Otherwise it's listed with its reason, and the user decides.

## Leftover fixes

1. **A NUL character in any public text field gives a 500.** The shared rules in `app/bookings/rules.py` (`_length` and the other `clean_*`) and `clean_description` refuse `\x00` with "Please remove unusual characters". This covers the booking, request and enquiry forms, and the staff forms that use the same rules.
2. **An out-of-range id in a staff URL gives a 500.** Every `int` path parameter (`enquiry_id`, `block_id`, `service_id`, `bay_id`, `bay_type_id`, `user_id`, `timetable_id`) gets `Path(ge=1, le=2_147_483_647)`, so a bad id is a 422, never a database error. The staff enquiry page treats a non-number id as "No such enquiry".
3. **A time with a time zone in the opening-hours editor gives a 500.** `DayIn` (and break times) refuse times that carry a time zone or seconds, with a 422.
4. **Production starts without `STRIPE_WEBHOOK_SECRET`.** `AppConfig.check_stripe_keys` refuses to start in production with Stripe keys but no webhook secret, because without it payments never confirm.

## Testing

- **Unit:** the limit rule (under, at and over the limit; the window edge), the NUL rule, the time rule, and the config check.
- **API (pytest):**
  - For each limited action, the limit plus one attempt gives 429 with `Retry-After`, and a different IP or action isn't affected.
  - A refused hold creates no hold. A refused enquiry stores nothing and sends no email.
  - The status poll and the link view are never limited.
  - In `development` no limit applies and no row is recorded.
  - The worker clears old rows.
  - Honeypot: a filled-in enquiry gives 201 with nothing stored or emailed; filled-in checkout and request give 422 with the hold unchanged; an empty `website` changes nothing.
  - NUL in each public route gives 422. Out-of-range ids give 422. A tz time gives 422.
  - The API sets `X-Content-Type-Options`.
- **Frontend (Vitest):** each form shows the 429 detail. The honeypot field is in the DOM, hidden, unlabelled for assistive technology, sent when filled, and empty by default.
- **CI:** the header check, the scan job, and the whole e2e suite, which proves Stripe works under the content policy.

## Left to the builder

- Module layout (for example `app/limits.py` for the counter, and a FastAPI dependency or a call at the top of each route).
- The exact Trivy and pip-audit invocations and action versions.
- Exact wording of the log lines.
- Whether the headers sit in a shared nginx include or inline.
