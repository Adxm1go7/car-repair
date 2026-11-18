import { expect, test } from '@playwright/test'
import { chooseMotSlot, enterDetails, expectStripeTestKeys, londonDate, payInStripe } from './booking'
import { waitForEmail } from './mailpit'
import { loginAs } from './staff'

// Flow 6 from docs/SPEC.md: after phoning the customer, the garage moves their booking
// (they're emailed the new time and the reason), then has to cancel it (they're emailed,
// and the deposit is refunded). Needs Stripe test keys and Mailpit, like flow 4.

const LINK = /https?:\/\/\S+\/booking\/[A-Z2-9-]+#t=\S+/
const TIME = /^\d\d:\d\d$/

/** "2026-11-19" plus one day. */
function nextDay(day: string): string {
  const noon = new Date(`${day}T12:00:00Z`)
  noon.setUTCDate(noon.getUTCDate() + 1)
  return noon.toISOString().slice(0, 10)
}

test('flow 6: the garage moves, then cancels, a customer booking', async ({ page, request }) => {
  await expectStripeTestKeys(page)
  const email = `sam+${Date.now()}@example.com`

  // 1. The customer books and pays.
  const { day, start } = await chooseMotSlot(page, londonDate(2))
  await enterDetails(page, email)
  await payInStripe(page)
  await expect(page.getByRole('heading', { name: "You're booked" })).toBeVisible({ timeout: 30_000 })
  const reference = (await page.getByText(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/).textContent()) ?? ''
  const confirmation = await waitForEmail(request, email, /Your booking is confirmed/)
  const link = LINK.exec(confirmation.text)?.[0] ?? ''
  expect(link, 'the confirmation email has no booking link').toBeTruthy()

  // 2. Staff move it to another free time that day, or on the next day that has one.
  await loginAs(page, 'staff')
  await page.goto(`/staff/bookings/${reference}`)
  await expect(page.getByRole('heading', { level: 1, name: `${reference} · Confirmed` })).toBeVisible()
  await page.getByRole('button', { name: 'Move', exact: true }).click()
  const panel = page.getByRole('region', { name: 'Move booking' })
  const times = panel.getByRole('group', { name: 'Times' }).getByRole('button', { name: TIME })
  const none = panel.getByText('No free times that day')

  let moveDay = day
  let newStart = ''
  for (let tries = 0; tries < 14 && !newStart; tries++) {
    if (tries > 0) {
      moveDay = nextDay(moveDay)
      await panel.getByLabel('Date').fill(moveDay)
    }
    await expect(times.first().or(none)).toBeVisible()
    for (const label of await times.allTextContents()) {
      if (moveDay !== day || label !== start) {
        newStart = label
        break
      }
    }
  }
  expect(newStart, 'no other free MOT time to move to').toBeTruthy()

  await times.filter({ hasText: newStart }).first().click()
  await panel.getByLabel('Reason (optional)').fill('Lift broken')
  await panel.getByRole('button', { name: 'Move booking' }).click()
  await panel.getByRole('button', { name: 'Yes, move it' }).click()
  await expect(page.getByRole('region', { name: 'Move booking' })).toHaveCount(0)
  await expect(page.getByRole('heading', { level: 1, name: `${reference} · Confirmed` })).toBeVisible()

  // 3. The customer is emailed the new time and the reason; their link page shows it too.
  const moved = await waitForEmail(request, email, /Your booking has moved/)
  expect(moved.text).toContain(`, ${newStart} – `)
  expect(moved.text).toContain('Lift broken')
  await page.goto(link)
  await expect(page.getByText(reference)).toBeVisible()
  await expect(page.locator('.booked-when')).toContainText(`${newStart} – `)

  // 4. Staff cancel it.
  await page.goto(`/staff/bookings/${reference}`)
  await page.getByRole('button', { name: 'Cancel booking' }).click()
  await page.getByRole('button', { name: 'Cancel this booking' }).click()
  await page.getByRole('button', { name: 'Yes, cancel it' }).click()
  await expect(page.getByRole('heading', { level: 1, name: `${reference} · Cancelled` })).toBeVisible({
    timeout: 15_000,
  })

  // 5. The customer is told, and their deposit is on its way back.
  await waitForEmail(request, email, /We've had to cancel your booking/)
  await page.goto(link)
  await expect(page.getByText('This booking is cancelled')).toBeVisible()
  await expect(page.getByText(/refund is on its way|has been refunded/)).toBeVisible()
})
