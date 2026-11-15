import { expect, test } from '@playwright/test'
import { chooseMotSlot, enterDetails, expectStripeTestKeys, freeMotStarts, payInStripe } from './booking'

// Flow 1 from docs/SPEC.md: a customer books an instant service and pays the £20 deposit
// in Stripe's embedded form (test mode). MOT test uses the MOT bay, the only bay of its type,
// so once booked its start must disappear from availability.
//
// It needs the stack running with Stripe test keys (docs/stripe-setup.md). It never falls
// back to demo mode: a broken real payment must not pass as a working demo one.

test('flow 1: instant booking with a deposit', async ({ page }) => {
  await expectStripeTestKeys(page)

  const { day, start } = await chooseMotSlot(page)
  await enterDetails(page)
  await expect(page.getByText('Deposit £20, balance paid at the garage')).toBeVisible()
  await payInStripe(page)

  await expect(page.getByRole('heading', { name: "You're booked" })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('Deposit paid: £20')).toBeVisible()
  await expect(page.getByText(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/)).toBeVisible()
  await expect(page.getByText('AB12CDE · Ford Focus')).toBeVisible()

  expect(await freeMotStarts(page, day)).not.toContain(start)
})
