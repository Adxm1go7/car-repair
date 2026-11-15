import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'

// Steps shared by the flows that book through the real page and pay with Stripe (test mode).

const SLOT = /^\d\d:\d\d – \d\d:\d\d$/
const TEST_CARD = '4242 4242 4242 4242'

type Policy = { payment: { provider: string; publishable_key?: string } }

/** Fail at once, with the reason, if the stack is in demo mode: a demo payment must never pass as a real one. */
export async function expectStripeTestKeys(page: Page): Promise<void> {
  const policy = (await (await page.request.get('/api/booking-policy')).json()) as Policy
  expect(
    policy.payment.provider === 'stripe' && policy.payment.publishable_key?.startsWith('pk_test_'),
    'Stripe test keys are not configured — see docs/stripe-setup.md',
  ).toBe(true)
}

/** Today's date at the garage, "YYYY-MM-DD", plus `days`. */
export function londonDate(days = 0): string {
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London' }).format(new Date())
  const noon = new Date(`${today}T12:00:00Z`)
  noon.setUTCDate(noon.getUTCDate() + days)
  return noon.toISOString().slice(0, 10)
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

export type ChosenSlot = { day: string; start: string }

/**
 * From the catalogue, choose MOT test and the first free time on a day no earlier than
 * `earliest` ("YYYY-MM-DD"). Returns that day and the slot's start ("HH:MM").
 */
export async function chooseMotSlot(page: Page, earliest = londonDate()): Promise<ChosenSlot> {
  const lastDate = trackAvailabilityDate(page)

  await page.goto('/')
  await page.getByRole('checkbox', { name: 'MOT test' }).check()
  await page.getByRole('link', { name: /^Choose a time/ }).click()
  await expect(page.getByRole('heading', { name: 'Choose a time' })).toBeVisible()

  // A day may be too early or have no times left, so try open days in order until one fits.
  const slots = page.getByRole('button', { name: SLOT })
  const empty = page.getByText('No times left on this day')
  const days = page.getByRole('group', { name: 'Day' }).getByRole('button')
  await expect(days.first()).toBeVisible() // the strip appears once the booking policy loads
  await expect(slots.first().or(empty)).toBeVisible()
  const dayCount = await days.count()
  let found = false
  for (let i = 0; i < dayCount; i++) {
    const button = days.nth(i)
    if (await button.isDisabled()) continue
    if ((await button.getAttribute('aria-pressed')) !== 'true') {
      const loaded = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/availability')
      await button.click()
      await loaded
    }
    await expect(slots.first().or(empty)).toBeVisible()
    const day = lastDate()
    if (day !== null && day < earliest) continue
    if ((await slots.count()) > 0) {
      found = true
      break
    }
  }
  expect(found, `no free MOT time on or after ${earliest}`).toBe(true)

  const slot = slots.first()
  const start = (await slot.textContent())?.slice(0, 5) ?? ''
  const day = lastDate() ?? ''
  expect(day).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  const chosen = { day, start }
  await slot.click()
  return chosen
}

/** Fill in the customer's details and open the payment step. */
export async function enterDetails(page: Page, email = 'sam@example.com'): Promise<void> {
  await expect(page.getByRole('heading', { name: 'Your details' })).toBeVisible()
  await page.getByLabel('Name').fill('Sam Driver')
  await page.getByLabel('Phone').fill('07700 900123')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Registration').fill('ab12 cde')
  await page.getByLabel('Make').fill('Ford')
  await page.getByLabel('Model').fill('Focus')
  await page.getByRole('button', { name: 'Continue to payment' }).click()

  // If Stripe refuses to start the payment, the page shows why: fail with that, not a timeout.
  const paying = page.getByRole('heading', { name: 'Pay your deposit' })
  const problem = page.getByRole('alert')
  await expect(paying.or(problem)).toBeVisible({ timeout: 15_000 })
  if (await problem.isVisible()) throw new Error(`The payment step didn't start: ${await problem.textContent()}`)
}

/** Stripe's own form, drawn in an iframe inside our page. */
export async function payInStripe(page: Page): Promise<void> {
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

type Slot = { start: string }

/** The start times ("HH:MM") still free for an MOT on `day`. */
export async function freeMotStarts(page: Page, day: string): Promise<string[]> {
  const response = await page.request.get(`/api/availability?services=mot-test&date=${day}`)
  expect(response.ok()).toBe(true)
  const { slots } = (await response.json()) as { slots: Slot[] }
  return slots.map((s) => s.start.slice(11, 16))
}
