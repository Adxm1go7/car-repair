import { expect, test } from '@playwright/test'
import { chooseSlot, expectStripeTestKeys, fillDetails, londonDate, payInStripe } from './booking'
import { waitForEmail } from './mailpit'
import { loginAs } from './staff'

// Flow 2 from docs/SPEC.md: a customer asks for a service that needs approval, without
// paying; staff approve it from the Requests page; the customer pays the deposit from the
// link in the approval email, and the booking is confirmed. Needs the stack running with
// Stripe test keys (docs/stripe-setup.md) and Mailpit catching the email.

const LINK = /https?:\/\/\S+\/booking\/[A-Z2-9-]+#t=\S+/
const REFERENCE = /^[A-Z2-9]{4}-[A-Z2-9]{4}$/

test('flow 2: a request is approved and paid', async ({ page, request }) => {
  await expectStripeTestKeys(page)
  const email = `sam+${Date.now()}@example.com`

  // The customer sends the request. Requests need a day's notice: two days ahead is safe.
  await chooseSlot(page, 'Diagnostic check', londonDate(2))
  await fillDetails(page, email)
  await expect(page.getByText(/The garage will check your request and email you within 48 hours/)).toBeVisible()
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByRole('heading', { name: 'Request sent' })).toBeVisible({ timeout: 15_000 })
  const reference = (await page.getByText(REFERENCE).textContent()) ?? ''
  expect(reference).toMatch(REFERENCE)
  await waitForEmail(request, email, /We've got your request/)

  // Staff approve it from the queue.
  await loginAs(page, 'staff')
  await page.getByRole('navigation', { name: 'Staff' }).getByRole('link', { name: /^Requests/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Requests' })).toBeVisible()
  await page.getByRole('link', { name: reference }).click()
  await expect(page.getByRole('heading', { level: 1, name: `${reference} · Request` })).toBeVisible()
  await page.getByRole('button', { name: 'Approve' }).click()
  await page.getByRole('button', { name: 'Yes, approve' }).click()
  await expect(page.getByText('Approved — the customer has been emailed')).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: `${reference} · Awaiting deposit` })).toBeVisible()

  // The customer pays from the link in the approval email.
  const approval = await waitForEmail(request, email, /Your booking is approved/)
  const link = LINK.exec(approval.text)?.[0]
  expect(link, 'the approval email has no booking link').toBeTruthy()
  expect(link).toContain(`/booking/${reference}#t=`)
  await page.goto(link ?? '')
  await expect(page.getByText(/Pay the £20 deposit by .+ to confirm\./)).toBeVisible()
  await page.getByRole('button', { name: 'Pay deposit' }).click()
  await payInStripe(page)

  await expect(page.getByText('Your booking is confirmed')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('Deposit: £20 paid')).toBeVisible()
  await waitForEmail(request, email, /Your booking is confirmed/)

  // A refresh asks the server again: still confirmed, nothing left to pay.
  await page.reload()
  await expect(page.getByText('Deposit: £20 paid')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Pay deposit' })).toHaveCount(0)
})
