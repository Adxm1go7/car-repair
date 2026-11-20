import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { chooseMotSlot, enterDetails, expectStripeTestKeys, londonDate, payInStripe } from './booking'
import { waitForEmail } from './mailpit'
import { loginAs } from './staff'

// An automated accessibility check (axe, WCAG 2 A and AA) on the main customer and staff
// pages. It fails on any "serious" or "critical" problem and lists each one, so a CI failure
// says what to fix. Problems are fixed in the markup, never by leaving an element out.

const LINK = /https?:\/\/\S+\/booking\/[A-Z2-9-]+#t=\S+/

async function expectNoSeriousViolations(page: Page, name: string): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
  const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  const report = serious
    .map((v) => `${v.id} (${v.impact}): ${v.help}\n    ${v.nodes.map((n) => n.target.join(' ')).join('\n    ')}`)
    .join('\n')
  expect(serious, `accessibility problems on ${name}:\n${report}`).toEqual([])
}

test('customer pages have no serious accessibility problems', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expectNoSeriousViolations(page, 'the services page')

  await page.getByRole('checkbox', { name: 'MOT test' }).check()
  await expectNoSeriousViolations(page, 'the services page with a service chosen')
  await page.getByRole('link', { name: /^Choose a time/ }).click()
  await expect(page.getByRole('group', { name: 'Day' }).getByRole('button').first()).toBeVisible()
  await expectNoSeriousViolations(page, 'the time picker')

  await chooseMotSlot(page, londonDate(1))
  await expect(page.getByRole('heading', { name: 'Your details' })).toBeVisible()
  await expectNoSeriousViolations(page, 'the details step')

  await page.goto('/enquiry')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expectNoSeriousViolations(page, 'the enquiry form')

  await page.goto('/privacy')
  await expect(page.getByRole('heading', { level: 1, name: 'Privacy' })).toBeVisible()
  await expectNoSeriousViolations(page, 'the privacy note')

  await page.goto('/no-such-page')
  await expect(page.getByRole('heading', { level: 1, name: 'Page not found' })).toBeVisible()
  await expectNoSeriousViolations(page, 'the page-not-found page')
})

test('booking, my-booking and staff pages have no serious accessibility problems', async ({ page, request }) => {
  await expectStripeTestKeys(page)
  const email = `axe+${Date.now()}@example.com`

  await chooseMotSlot(page, londonDate(2))
  await enterDetails(page, email)
  await expectNoSeriousViolations(page, 'the payment step')
  await payInStripe(page)
  await expect(page.getByRole('heading', { name: "You're booked" })).toBeVisible({ timeout: 30_000 })
  await expectNoSeriousViolations(page, 'the booked page')
  const reference = (await page.getByText(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/).textContent()) ?? ''

  const confirmation = await waitForEmail(request, email, /Your booking is confirmed/)
  const link = LINK.exec(confirmation.text)?.[0]
  expect(link, 'the confirmation email has no booking link').toBeTruthy()
  await page.goto(link ?? '')
  await expect(page.getByText(reference)).toBeVisible()
  await expectNoSeriousViolations(page, 'the my-booking page')

  await page.context().clearCookies()
  await page.goto('/staff/login')
  await expect(page.getByRole('button', { name: 'Log in' })).toBeVisible()
  await expectNoSeriousViolations(page, 'the staff login page')

  await loginAs(page, 'admin')
  await expectNoSeriousViolations(page, 'the day schedule')

  await page.goto(`/staff/bookings/${reference}`)
  await expect(page.getByText(reference).first()).toBeVisible()
  await expectNoSeriousViolations(page, 'a booking detail page')

  await page.goto('/staff/settings/services')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expectNoSeriousViolations(page, 'the settings page')
})
