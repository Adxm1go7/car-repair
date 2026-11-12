import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// Flow 1 from docs/SPEC.md: a customer books an instant service, without payment.
// MOT test uses the MOT bay, the only bay of its type, so once booked its start must
// disappear from availability.

const SLOT = /^\d\d:\d\d – \d\d:\d\d$/

type Slot = { start: string; end: string }

/** The date of the most recent availability request the page made. */
function trackAvailabilityDate(page: Page): () => string | null {
  let date: string | null = null
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname === '/api/availability') date = url.searchParams.get('date')
  })
  return () => date
}

test('flow 1: instant booking without payment', async ({ page, request }) => {
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
  await page.getByRole('button', { name: 'Confirm booking' }).click()

  await expect(page.getByRole('heading', { name: "You're booked" })).toBeVisible()
  await expect(page.getByText(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/)).toBeVisible()
  await expect(page.getByText('AB12CDE · Ford Focus')).toBeVisible()

  const response = await request.get(`/api/availability?services=mot-test&date=${bookedDay}`)
  expect(response.ok()).toBe(true)
  const { slots: left } = (await response.json()) as { slots: Slot[] }
  expect(left.map((s) => s.start.slice(11, 16))).not.toContain(bookedStart)
})
