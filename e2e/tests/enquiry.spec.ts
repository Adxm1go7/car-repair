import { expect, test } from '@playwright/test'
import { londonDate } from './booking'
import { waitForEmail } from './mailpit'
import { loginAs, staffSlots } from './staff'

// Flow 3 from docs/SPEC.md: a customer who doesn't know what's wrong describes the problem;
// staff book it in from the Enquiries page; the customer gets the confirmation email, and
// the link in it shows a confirmed booking with nothing to pay. No payment, so no Stripe keys
// needed; Mailpit catches the emails.

const LINK = /https?:\/\/\S+\/booking\/[A-Z2-9-]+#t=\S+/

test('flow 3: an enquiry is booked in', async ({ page, request }) => {
  const stamp = Date.now()
  const email = `sam+${stamp}@example.com`
  const name = `Sam ${stamp}`

  // The customer sends an enquiry from the services page.
  await page.goto('/')
  await page.getByRole('link', { name: 'Describe the problem' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Ask about a problem' })).toBeVisible()
  await page.getByLabel('Name').fill(name)
  await page.getByLabel('Phone').fill('07700 900123')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Registration').fill('AB12 CDE')
  await page.getByLabel('Make').fill('Ford')
  await page.getByLabel('Model').fill('Focus')
  await page.getByLabel('Describe the problem').fill('Rattle from the front left when braking, worse when cold.')
  await page.getByRole('button', { name: 'Send enquiry' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Enquiry sent' })).toBeVisible()
  await waitForEmail(request, email, /We've got your enquiry/)

  // Staff find it in the queue and book it in: a diagnostic check, the first free time from
  // tomorrow.
  await loginAs(page, 'staff')
  let day = ''
  for (let ahead = 1; ahead <= 21 && !day; ahead++) {
    const candidate = londonDate(ahead)
    if ((await staffSlots(page, ['diagnostic-check'], candidate)).length > 0) day = candidate
  }
  expect(day, 'no day in the next three weeks with a free diagnostic check').toBeTruthy()

  await page.getByRole('navigation', { name: 'Staff' }).getByRole('link', { name: /^Enquiries/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Enquiries' })).toBeVisible()
  await page.getByRole('link', { name }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Enquiry · New' })).toBeVisible()
  await expect(page.getByText('Rattle from the front left when braking, worse when cold.')).toBeVisible()
  await page.getByRole('link', { name: 'Approve and book' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Book enquiry' })).toBeVisible()
  await expect(page.getByLabel('Email')).toHaveValue(email)
  await page.getByLabel('Date').fill(day)
  await page.getByRole('checkbox', { name: /Diagnostic check/ }).check()
  await page.getByRole('group', { name: 'Times' }).getByRole('button').first().click()
  await page.getByRole('button', { name: 'Book it' }).click()
  await expect(page.getByText('Booked — the customer has been emailed')).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: 'Enquiry · Booked' })).toBeVisible()

  // The customer's confirmation email links to a confirmed booking with nothing to pay.
  const confirmation = await waitForEmail(request, email, /Your booking is confirmed/)
  const link = LINK.exec(confirmation.text)?.[0]
  expect(link, 'the confirmation email has no booking link').toBeTruthy()
  await page.goto(link ?? '')
  await expect(page.getByRole('heading', { level: 1, name: 'Your booking' })).toBeVisible()
  await expect(page.getByText('AB12CDE · Ford Focus')).toBeVisible()
  await expect(page.getByText('Diagnostic check')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Pay deposit' })).toHaveCount(0)
})
