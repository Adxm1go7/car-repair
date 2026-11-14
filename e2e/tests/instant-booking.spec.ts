import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// Flow 1 from docs/SPEC.md: a customer books an instant service and pays the £20 deposit
// in Stripe's embedded form (test mode). MOT test uses the MOT bay, the only bay of its type,
// so once booked its start must disappear from availability.
//
// It needs the stack running with Stripe test keys (docs/stripe-setup.md). It never falls
// back to demo mode: a broken real payment must not pass as a working demo one.

const SLOT = /^\d\d:\d\d – \d\d:\d\d$/

type Slot = { start: string; end: string }
type Policy = { payment: { provider: string; publishable_key?: string } }

const TEST_CARD = '4242 4242 4242 4242'

/** Stripe's own form, drawn in an iframe inside our page. */
async function payInStripe(page: Page): Promise<void> {
  const stripe = page.locator('.stripe-checkout iframe').first().contentFrame()
  const card = stripe.getByPlaceholder('1234 1234 1234 1234')
  await expect(card).toBeVisible({ timeout: 30_000 })
  await card.fill(TEST_CARD)
  await stripe.getByPlaceholder('MM / YY').fill('12 / 34')
  await stripe.getByPlaceholder('CVC').fill('123')
  // Stripe asks for these depending on the account's settings and where the browser is.
  // CI runs in the US, where Stripe defaults to a US ZIP code and offers to save the card
  // with Link (which then wants a phone number): pin the country and opt out.
  const name = stripe.getByLabel(/cardholder name|name on card/i)
  if (await name.isVisible()) await name.fill('Sam Driver')
  const country = stripe.getByLabel(/country or region/i)
  if (await country.isVisible()) await country.selectOption('GB')
  const postcode = stripe.getByLabel(/postal code|postcode|zip/i).or(stripe.getByPlaceholder(/postal code|postcode|zip/i))
  if (await postcode.first().isVisible()) await postcode.first().fill('SW1A 1AA')
  const link = stripe.getByRole('checkbox', { name: /save my information/i })
  if ((await link.count()) > 0 && (await link.isChecked())) await link.uncheck()
  await stripe.getByRole('button', { name: /^pay/i }).click()
}

/** The date of the most recent availability request the page made. */
function trackAvailabilityDate(page: Page): () => string | null {
  let date: string | null = null
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname === '/api/availability') date = url.searchParams.get('date')
  })
  return () => date
}

test('flow 1: instant booking with a deposit', async ({ page, request }) => {
  const policy = (await (await request.get('/api/booking-policy')).json()) as Policy
  expect(
    policy.payment.provider === 'stripe' && policy.payment.publishable_key?.startsWith('pk_test_'),
    'Stripe test keys are not configured — see docs/stripe-setup.md',
  ).toBe(true)

  const lastDate = trackAvailabilityDate(page)

  await page.goto('/')
  await page.getByRole('checkbox', { name: 'MOT test' }).check()
  await page.getByRole('link', { name: /^Choose a time/ }).click()
  await expect(page.getByRole('heading', { name: 'Choose a time' })).toBeVisible()

  // Today may have no times left, so try open days in order until one has a slot.
  const slots = page.getByRole('button', { name: SLOT })
  const empty = page.getByText('No times left on this day')
  const days = page.getByRole('group', { name: 'Day' }).getByRole('button')
  await expect(days.first()).toBeVisible() // the strip appears once the booking policy loads
  const dayCount = await days.count()
  for (let i = 0; i < dayCount; i++) {
    const day = days.nth(i)
    if (await day.isDisabled()) continue
    if ((await day.getAttribute('aria-pressed')) !== 'true') await day.click()
    await expect(slots.first().or(empty)).toBeVisible()
    if ((await slots.count()) > 0) break
  }
  await expect(slots.first()).toBeVisible()

  const slot = slots.first()
  const bookedStart = (await slot.textContent())?.slice(0, 5) ?? ''
  const bookedDay = lastDate()
  expect(bookedDay).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  await slot.click()

  await expect(page.getByRole('heading', { name: 'Your details' })).toBeVisible()
  await page.getByLabel('Name').fill('Sam Driver')
  await page.getByLabel('Phone').fill('07700 900123')
  await page.getByLabel('Email').fill('sam@example.com')
  await page.getByLabel('Registration').fill('ab12 cde')
  await page.getByLabel('Make').fill('Ford')
  await page.getByLabel('Model').fill('Focus')
  await page.getByRole('button', { name: 'Continue to payment' }).click()

  // If Stripe refuses to start the payment, the page shows why: fail with that, not a timeout.
  const paying = page.getByRole('heading', { name: 'Pay your deposit' })
  const problem = page.getByRole('alert')
  await expect(paying.or(problem)).toBeVisible({ timeout: 15_000 })
  if (await problem.isVisible()) throw new Error(`The payment step didn't start: ${await problem.textContent()}`)
  await expect(page.getByText('Deposit £20, balance paid at the garage')).toBeVisible()
  await payInStripe(page)

  await expect(page.getByRole('heading', { name: "You're booked" })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('Deposit paid: £20')).toBeVisible()
  await expect(page.getByText(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/)).toBeVisible()
  await expect(page.getByText('AB12CDE · Ford Focus')).toBeVisible()

  const response = await request.get(`/api/availability?services=mot-test&date=${bookedDay}`)
  expect(response.ok()).toBe(true)
  const { slots: left } = (await response.json()) as { slots: Slot[] }
  expect(left.map((s) => s.start.slice(11, 16))).not.toContain(bookedStart)
})
