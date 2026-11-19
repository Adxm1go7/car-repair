import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { londonDate } from './booking'
import { loginAs, referenceFromUrl, staffSlots } from './staff'

// Flow 7 from docs/SPEC.md: an admin adds a service and hides it again, is refused new hours
// that would leave a booking outside them, and adds (then deletes) future hours that clash
// with nothing. It cleans up after itself; the hidden service stays, as services can't be
// deleted.

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function weekdayName(date: string): string {
  const day = new Date(`${date}T12:00:00Z`).getUTCDay() // 0 = Sunday
  return WEEKDAYS[(day + 6) % 7]
}

/** "Tue 1 Dec", as the pages write a date. */
function shortDate(date: string): string {
  return new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' })
    .format(new Date(`${date}T12:00:00Z`))
    .replace(',', '')
}

/** The calendar date after `date`, "YYYY-MM-DD". */
function dayAfter(date: string): string {
  const noon = new Date(`${date}T12:00:00Z`)
  noon.setUTCDate(noon.getUTCDate() + 1)
  return noon.toISOString().slice(0, 10)
}

type Timetable = { id: number; starts_on: string }

/** Deletes future hours a failed earlier run may have left on these dates. Needs an admin page. */
async function deleteHoursFrom(page: Page, dates: string[]): Promise<void> {
  const response = await page.request.get('/api/staff/settings/hours')
  expect(response.ok()).toBe(true)
  for (const timetable of (await response.json()) as Timetable[]) {
    if (!dates.includes(timetable.starts_on)) continue
    const deleted = await page.request.delete(`/api/staff/settings/hours/${timetable.id}`, {
      headers: { Origin: new URL(page.url()).origin },
    })
    expect(deleted.status()).toBe(204)
  }
}

test('flow 7: admin settings: services, a refused clash, and future hours', async ({ page }) => {
  // 1. Add a service; it shows on the home page. Hide it; it's gone.
  const name = `E2E service ${Date.now()}`
  await loginAs(page, 'admin')
  await page.getByRole('navigation', { name: 'Staff' }).getByRole('link', { name: 'Settings' }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'Services' })).toBeVisible()
  await page.getByRole('button', { name: '+ Add a service' }).click()
  const form = page.getByRole('form', { name: 'Add a service' })
  await form.getByLabel('Name').fill(name)
  await form.getByLabel('Category').fill('Testing')
  await form.getByLabel('Description').fill('Added by the end-to-end tests.')
  await form.getByLabel('Duration').selectOption('30')
  await form.getByLabel('Price from (£)').fill('10')
  await form.getByLabel('Bay type').selectOption({ label: 'General bay' })
  await form.getByRole('button', { name: 'Add service' }).click()
  await expect(page.getByRole('status')).toHaveText(`Added ${name}`)

  await page.goto('/')
  await expect(page.getByRole('heading', { level: 3, name })).toBeVisible()

  await page.goto('/staff/settings/services')
  const row = page.getByRole('listitem', { name })
  await row.getByRole('button', { name: 'Hide' }).click()
  await row.getByRole('button', { name: 'Yes, hide' }).click()
  await expect(row.getByText('Hidden')).toBeVisible()
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 2, name: 'Opening hours' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 3, name })).toHaveCount(0)

  // 2. As staff, a phone booking (no email) for the first free MOT at least 2 days ahead.
  await loginAs(page, 'staff')
  let day = ''
  for (let ahead = 2; ahead <= 21 && !day; ahead++) {
    const candidate = londonDate(ahead)
    if ((await staffSlots(page, ['mot-test'], candidate)).length > 0) day = candidate
  }
  expect(day, 'no day in the next three weeks with a free MOT').toBeTruthy()
  const nextDay = dayAfter(day)

  await page.goto(`/staff/bookings/new?date=${day}`)
  await page.getByRole('checkbox', { name: 'MOT test' }).check()
  await page.getByRole('group', { name: 'Times' }).getByRole('button').first().click()
  await page.getByLabel('Name', { exact: true }).fill('Pat Settings')
  await page.getByLabel('Phone').fill('07700 900789')
  await page.getByLabel('Registration').fill(`E2E${String(Date.now()).slice(-4)}`)
  await page.getByLabel('Make').fill('Ford')
  await page.getByLabel('Model').fill('Fiesta')
  await page.getByRole('button', { name: 'Book it' }).click()
  await expect(page.getByRole('heading', { level: 1, name: / · Confirmed$/ })).toBeVisible()
  const reference = referenceFromUrl(page)

  // 3. Hours from that date with its weekday closed are refused, listing the booking.
  await loginAs(page, 'admin')
  await page.goto('/staff/settings/hours')
  await deleteHoursFrom(page, [day, nextDay])
  await page.reload()
  const hours = page.getByRole('list', { name: 'Hours' }).getByRole('listitem')
  await expect(hours.first()).toBeVisible()
  const before = await hours.count()

  await page.getByRole('button', { name: '+ New hours from a date' }).click()
  const newHours = page.getByRole('form', { name: 'New hours' })
  await newHours.getByLabel('Starts on').fill(day)
  await newHours.getByLabel(`Open on ${weekdayName(day)}`).uncheck()
  await newHours.getByRole('button', { name: 'Save' }).click()
  await newHours.getByRole('button', { name: 'Yes, save' }).click()
  const clashes = newHours.getByRole('list', { name: 'Bookings in the way' })
  await expect(clashes.getByRole('link', { name: reference })).toBeVisible()
  await expect(hours).toHaveCount(before)
  await newHours.getByRole('button', { name: 'Cancel' }).click()

  // 4. The same week from the day after clashes with nothing; the home page shows it.
  await page.getByRole('button', { name: '+ New hours from a date' }).click()
  await newHours.getByLabel('Starts on').fill(nextDay)
  await newHours.getByRole('button', { name: 'Save' }).click()
  await newHours.getByRole('button', { name: 'Yes, save' }).click()
  await expect(page.getByRole('status')).toHaveText(`New hours from ${shortDate(nextDay)} saved`)
  await expect(hours).toHaveCount(before + 1)

  await page.goto('/')
  await expect(page.getByRole('heading', { level: 3, name: `New hours from ${shortDate(nextDay)}` })).toBeVisible()

  await page.goto('/staff/settings/hours')
  const added = page.getByRole('listitem', { name: `From ${shortDate(nextDay)}` })
  await added.getByRole('button', { name: 'Delete' }).click()
  await added.getByRole('button', { name: 'Yes, delete' }).click()
  await expect(page.getByRole('status')).toHaveText(`Deleted the hours from ${shortDate(nextDay)}`)
  await expect(added).toHaveCount(0)

  // 5. Clean up: cancel the phone booking.
  await page.goto(`/staff/bookings/${reference}`)
  await page.getByRole('button', { name: 'Cancel booking' }).click()
  await page.getByRole('button', { name: 'Cancel this booking' }).click()
  await page.getByRole('button', { name: 'Yes, cancel it' }).click()
  await expect(page.getByRole('heading', { level: 1, name: `${reference} · Cancelled` })).toBeVisible()
})
