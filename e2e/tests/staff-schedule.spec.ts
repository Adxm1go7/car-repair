import { expect, test } from '@playwright/test'
import { londonDate } from './booking'
import { daySchedule, freeHour, loginAs, referenceFromUrl, staffSlots } from './staff'

// Flow 5 from docs/SPEC.md: a staff member books a customer in over the phone, blocks a
// bay, runs the job through to completed, and the admin finds it all in the audit log.

const NOTE = 'Lift broken (e2e)'

test('flow 5: phone booking, block time, start and complete, audit log', async ({ page }) => {
  await loginAs(page, 'staff')

  // From tomorrow, the first day with a free MOT and a free hour on Bay 1 to block.
  let day = ''
  let blockFrom: string | null = null
  let bay1 = 0
  for (let ahead = 1; ahead <= 21 && !blockFrom; ahead++) {
    const candidate = londonDate(ahead)
    if ((await staffSlots(page, ['mot-test'], candidate)).length === 0) continue
    const schedule = await daySchedule(page, candidate)
    bay1 = schedule.bays.find((b) => b.name === 'Bay 1')?.id ?? 0
    blockFrom = freeHour(schedule, candidate, bay1)
    day = candidate
  }
  expect(blockFrom, 'no day in the next three weeks with a free MOT and a free hour on Bay 1').toBeTruthy()
  const blockTo = `${String(Number(blockFrom?.slice(0, 2)) + 1).padStart(2, '0')}:00`

  // 1. A phone booking without an email: MOT, the first free time on that day.
  const registration = `E2E${String(Date.now()).slice(-4)}`
  await page.goto(`/staff/bookings/new?date=${day}`)
  await expect(page.getByRole('heading', { level: 1, name: 'New phone booking' })).toBeVisible()
  await page.getByRole('checkbox', { name: 'MOT test' }).check()
  await page.getByRole('group', { name: 'Times' }).getByRole('button').first().click()
  await expect(page.getByRole('group', { name: 'Bays' }).getByRole('button', { name: 'MOT bay' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await page.getByLabel('Name', { exact: true }).fill('Pat Caller')
  await page.getByLabel('Phone').fill('07700 900456')
  await page.getByLabel('Registration').fill(registration)
  await page.getByLabel('Make').fill('Vauxhall')
  await page.getByLabel('Model').fill('Corsa')
  await page.getByRole('button', { name: 'Book it' }).click()

  await expect(page.getByRole('heading', { level: 1, name: / · Confirmed$/ })).toBeVisible()
  const reference = referenceFromUrl(page)
  await expect(page.getByText('Phone booking · no deposit')).toBeVisible()
  await expect(page.getByText('No email, phone only')).toBeVisible()

  // 2. It's on that day's view, in the MOT bay.
  await page.goto(`/staff?date=${day}`)
  const booking = page.getByRole('region', { name: 'MOT bay' }).getByRole('link', { name: new RegExp(registration) })
  await expect(booking).toBeVisible()

  // 3. Block an hour on Bay 1 the same day.
  await page.getByRole('link', { name: '+ Block time' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Block time' })).toBeVisible()
  await page.getByLabel('Bay').selectOption({ label: 'Bay 1' })
  await page.getByLabel('Start date').fill(day)
  await page.getByLabel('Start time').fill(blockFrom ?? '')
  await page.getByLabel('End date').fill(day)
  await page.getByLabel('End time').fill(blockTo)
  await page.getByLabel('Note').fill(NOTE)
  await page.getByRole('button', { name: 'Block time' }).click()

  const block = page.getByRole('region', { name: 'Bay 1' }).getByRole('button', { name: new RegExp(`Blocked: ${NOTE}`.replace(/[()]/g, '\\$&')) })
  await expect(block).toBeVisible()

  // 4. Open the booking, Start job (it isn't today, so it asks), then Complete job.
  await booking.click()
  await expect(page.getByRole('heading', { level: 1, name: `${reference} · Confirmed` })).toBeVisible()
  await page.getByRole('button', { name: 'Start job' }).click()
  await page.getByRole('button', { name: 'Yes, start it' }).click()
  await expect(page.getByRole('heading', { level: 1, name: `${reference} · In progress` })).toBeVisible()
  await page.getByRole('button', { name: 'Complete job' }).click()
  await expect(page.getByRole('heading', { level: 1, name: `${reference} · Completed` })).toBeVisible()

  // 5. The admin sees all three changes, made by Sam Staff, in the audit log.
  await loginAs(page, 'admin')
  await page.goto(`/staff/audit?reference=${reference}`)
  const changes = page.getByRole('list', { name: 'Changes' }).getByRole('listitem')
  await expect(changes).toHaveCount(3)
  // Newest first.
  await expect(changes.nth(0)).toContainText('Sam Staff')
  await expect(changes.nth(0)).toContainText('Status changed to Completed')
  await expect(changes.nth(1)).toContainText('Sam Staff')
  await expect(changes.nth(1)).toContainText('Status changed to In progress')
  await expect(changes.nth(2)).toContainText('Sam Staff')
  await expect(changes.nth(2)).toContainText('Phone booking')

  // 6. Clean up: remove the block.
  await page.goto(`/staff?date=${day}`)
  await block.click()
  await page.getByRole('button', { name: 'Remove block' }).click()
  await page.getByRole('button', { name: 'Yes, remove it' }).click()
  await expect(block).toHaveCount(0)
})

test('staff see no Team or Audit links and team shows the access message', async ({ page }) => {
  await loginAs(page, 'staff')
  const nav = page.getByRole('navigation', { name: 'Staff' })
  await expect(nav.getByRole('link', { name: 'Day' })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Team' })).toHaveCount(0)
  await expect(nav.getByRole('link', { name: 'Audit' })).toHaveCount(0)

  await page.goto('/staff/team')
  await expect(page.getByText("You don't have access to this page")).toBeVisible()
  await page.goto('/staff/audit')
  await expect(page.getByText("You don't have access to this page")).toBeVisible()
})
