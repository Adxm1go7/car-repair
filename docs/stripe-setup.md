# Setting up Stripe (test mode)

The booking site takes a £20 deposit through [Stripe](https://stripe.com). Everything here uses
Stripe's **test mode**: no real money moves, no card is charged, and you don't need a business,
a bank account or any personal details beyond an email address.

Without any of this, the site still works in **demo mode**: the payment step shows a
"Pay £20 (demo)" button instead of Stripe's form. You need Stripe set up to see the real form,
and for the CI end-to-end test, which always uses the real form.

## 1. Create a free account

1. Go to <https://dashboard.stripe.com/register> and sign up with an email address.
2. Skip any "activate your account" or business-details steps. Test mode works without them.
3. Make sure the dashboard is in **test mode**. Look for a "Test mode" switch at the top,
   or a sandbox name. Stripe sometimes calls a test-mode workspace a **sandbox**.
   Test pages show test data, often with an orange "Test" badge.

## 2. Find your two test keys

In the dashboard, open **Developers → API keys** (in test mode). You'll see:

| Key | Starts with | What it's for | Secret? |
| --- | --- | --- | --- |
| Publishable key | `pk_test_` | Sent to the browser to load Stripe's form | No, it's meant to be public |
| Secret key | `sk_test_` | Lets our server create payments and refunds | **Yes**. Click "Reveal" to see it |

Only ever use keys that start with `pk_test_` and `sk_test_` here. Live keys start with
`pk_live_` and `sk_live_` and move real money; they must never go in a file.

## 3. Put the keys in `.env`

From the repository root, in PowerShell:

```powershell
Copy-Item .env.example .env   # only if you don't have a .env yet
notepad .env
```

Fill in the two lines and save:

```ini
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
```

`.env` is ignored by git, so it is never committed. Then restart the stack so it picks them up:

```powershell
docker compose up --build -d --wait
curl.exe -s http://localhost:8080/api/booking-policy
```

The last line should now show `"payment":{"provider":"stripe","publishable_key":"pk_test_..."}`.
It never shows the secret key.

## 4. Pay with a test card

Open <http://localhost:8080>, book an MOT, enter your details and click **Continue to payment**.
Stripe's form appears inside the page. Use:

| Card number | What happens |
| --- | --- |
| `4242 4242 4242 4242` | Payment succeeds |
| `4000 0000 0000 0002` | Card declined. Stripe shows the error and you can try again |
| `4000 0025 0000 3155` | Asks for a 3-D Secure check. Approve it in the pop-up and it succeeds |

Use any future expiry date (for example `12 / 34`), any 3-digit CVC, any name and any postcode.

After paying you should see "Confirming your payment…" briefly, then the booked page with
"Deposit paid: £20". The payment also appears in the dashboard under **Payments**.

## 5. Optional: Stripe's messages on your laptop

When a payment completes, Stripe also sends a message (a **webhook**) to our server. Stripe
can't reach `localhost`, so locally the booking page confirms by asking our server, which asks
Stripe. Everything works without webhooks.

To see webhooks working too, install the Stripe command-line tool (Stripe CLI):

1. Download `stripe_<version>_windows_x86_64.zip` from
   <https://github.com/stripe/stripe-cli/releases> and unzip it, for example to `C:\Tools\stripe`.
2. Log in. This opens the browser to link the CLI to your account:

   ```powershell
   C:\Tools\stripe\stripe.exe login
   ```

3. Get the webhook secret, add it to `.env` as `STRIPE_WEBHOOK_SECRET=whsec_...`, and restart:

   ```powershell
   C:\Tools\stripe\stripe.exe listen --print-secret
   docker compose up -d --wait
   ```

4. Keep this running in its own terminal while you test. It passes Stripe's messages to the API:

   ```powershell
   C:\Tools\stripe\stripe.exe listen --forward-to localhost:8000/api/stripe/webhook `
     --events checkout.session.completed,checkout.session.async_payment_succeeded,checkout.session.expired,refund.created,refund.updated,charge.refund.updated
   ```

   Recent versions of the CLI insist on the `--events` list. Without it they quit straight away.

   Each payment then shows lines like `checkout.session.completed [200]`.

## 6. Run the end-to-end test against real Stripe

With the keys in `.env` and the stack running:

```powershell
cd e2e
npm ci
npx playwright install chromium
npm test
cd ..
```

The test books an MOT and pays with `4242 4242 4242 4242` inside Stripe's form. It fails at
the start, with a clear message, if the stack isn't using Stripe test keys.

## 7. Give CI the keys

GitHub Actions runs the same end-to-end test on every push, so it needs the two test keys too.
It gets them from encrypted **repository secrets**, never from a file:

1. On GitHub, open the repository → **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret** twice:
   - Name `STRIPE_SECRET_KEY`, value your `sk_test_...` key.
   - Name `STRIPE_PUBLISHABLE_KEY`, value your `pk_test_...` key.

CI starts its own `stripe listen` with the secret key, so it needs no webhook secret.
GitHub doesn't give secrets to pull requests from forks or to Dependabot, so the `compose` check
fails on those. That's expected for a single-owner repository.

## Manual checklist

Run through these by hand after changing anything in the payment flow:

- [ ] `4242 4242 4242 4242` books, and the booked page shows "Deposit paid: £20".
- [ ] `4000 0000 0000 0002` shows Stripe's decline message, and the booking stays unpaid.
- [ ] `4000 0025 0000 3155` asks for 3-D Secure inside the page and then books.
- [ ] Leaving the payment step to run out (10 minutes) returns to the times with "You haven't
      been charged", and the session shows as expired in the dashboard.
- [ ] With `stripe listen` running, the payment's webhook shows `[200]`, and Stripe's dashboard
      (**Developers → Webhooks / Events**) shows it delivered.
