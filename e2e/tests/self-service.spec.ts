import { expect, test } from '@playwright/test'
import { chooseMotSlot, enterDetails, expectStripeTestKeys, freeMotStarts, londonDate, payInStripe } from './booking'
import { waitForEmail } from './mailpit'

// Flow 4 from docs/SPEC.md: the customer opens the private link from their confirmation
// email and cancels inside the free-cancellation window. Needs the stack running with
// Stripe test keys (docs/stripe-setup.md) and Mailpit catching the email.

const LINK = /https?:\/\/\S+\/booking\/[A-Z2-9-]+#t=\S+/

test('flow 4: cancel from the emailed link', async ({ page, request }) => {
  await expectStripeTestKeys(page)
  const email = `sam+${Date.now()}@example.com`

  // Two days ahead, so the booking is well outside the 24-hour window and can be cancelled.
  const { day, start } = await chooseMotSlot(page, londonDate(2))
  await enterDetails(page, email)
  await payInStripe(page)
  await expect(page.getByRole('heading', { name: "You're booked" })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText("We've emailed you a link to view or cancel your booking.")).toBeVisible()
  const reference = (await page.getByText(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/).textContent()) ?? ''
  expect(await freeMotStarts(page, day)).not.toContain(start)

  const confirmation = await waitForEmail(request, email, /Your booking is confirmed/)
  const link = LINK.exec(confirmation.text)?.[0]
  expect(link, 'the confirmation email has no booking link').toBeTruthy()
  expect(link).toContain(`/booking/${reference}#t=`)
  await page.goto(link ?? '')

  await expect(page.getByText(reference)).toBeVisible()
  await expect(page.getByText(/Need a different time\? Call us on/)).toBeVisible()
  await page.getByRole('button', { name: 'Cancel booking' }).click()

  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toContainText(/^Cancel your booking on .+ at \d\d:\d\d\?/)
  await expect(dialog).toContainText("You'll get your £20 deposit back.")
  await expect(dialog).toContainText('If you just need a different time, please call us on')
  await dialog.getByRole('button', { name: 'Yes, cancel it' }).click()

  await expect(page.getByText('This booking is cancelled')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/refund is on its way|has been refunded/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel booking' })).toHaveCount(0)

  // A refresh asks the server again: still cancelled.
  await page.reload()
  await expect(page.getByText('This booking is cancelled')).toBeVisible()

  const cancellation = await waitForEmail(request, email, /Your booking is cancelled/)
  expect(cancellation.text).toContain('being refunded')

  expect(await freeMotStarts(page, day)).toContain(start)
})

test('a made-up link fails safely', async ({ page }) => {
  await page.goto('/booking/ABCD-EFGH#t=nope')
  await expect(page.getByText("This link isn't valid any more")).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel booking' })).toHaveCount(0)
})
