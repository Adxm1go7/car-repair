import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { DAY_SCHEDULE, bookingItem, openDay, scheduleUrl } from '../../testing/schedule.ts'
import { STAFF_ME, renderAt, stubFetch } from '../../testing/staffApi.tsx'
import type { Schedule } from '../types.ts'

const WEEK_DATES = ['16', '17', '18', '19', '20', '21', '22'].map((d) => `2026-11-${d}`)

const WEEK: Schedule = {
  ...DAY_SCHEDULE,
  days: WEEK_DATES.map(openDay),
  items: [
    bookingItem({ reference: 'LATE-LATE', start: '2026-11-18T15:00:00+00:00', end: '2026-11-18T16:00:00+00:00', registration: 'LA7E' }),
    bookingItem({ reference: 'EARL-YYYY', bay_id: 2, start: '2026-11-18T08:00:00+00:00', end: '2026-11-18T09:00:00+00:00', registration: 'EA1Y' }),
    bookingItem({ reference: 'HELD-HELD', start: '2026-11-19T11:00:00+00:00', end: '2026-11-19T12:00:00+00:00', registration: 'HE1D', status: 'held' }),
    { kind: 'block', bay_id: 1, start: '2026-11-20T08:00:00+00:00', end: '2026-11-20T17:30:00+00:00', block_id: 3, note: 'Lift repair' },
  ],
}

function stubWeek(extra = {}) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    [scheduleUrl('2026-11-16', 7)]: { status: 200, body: WEEK },
    ...extra,
  })
}

afterEach(() => vi.unstubAllGlobals())

it('week view starts on Monday', async () => {
  const mock = stubWeek()
  renderAt('/staff/week?date=2026-11-18')

  expect(await screen.findByRole('heading', { level: 1, name: 'Week of 16 Nov' })).toBeInTheDocument()
  const days = await screen.findAllByRole('region')
  expect(days.map((d) => d.getAttribute('aria-label'))).toEqual([
    'Mon 16 Nov',
    'Tue 17 Nov',
    'Wed 18 Nov',
    'Thu 19 Nov',
    'Fri 20 Nov',
    'Sat 21 Nov',
    'Sun 22 Nov',
  ])
  expect(mock.mock.calls.map(([url]) => url)).toContain(scheduleUrl('2026-11-16', 7))
})

it('lists each day in time order, tagged with the bay, and links to the day view', async () => {
  stubWeek()
  renderAt('/staff/week?date=2026-11-18')
  const wed = await screen.findByRole('region', { name: 'Wed 18 Nov' })
  const links = within(wed).getAllByRole('link', { name: /·/ })
  expect(links.map((l) => l.getAttribute('href'))).toEqual(['/staff/bookings/EARL-YYYY', '/staff/bookings/LATE-LATE'])
  expect(links[0]).toHaveTextContent('Bay 1')
  expect(links[1]).toHaveTextContent('MOT bay')
  expect(within(wed).getByRole('link', { name: 'Wed 18 Nov' })).toHaveAttribute('href', '/staff?date=2026-11-18')

  const thu = screen.getByRole('region', { name: 'Thu 19 Nov' })
  expect(within(thu).getByText('Being booked')).toBeInTheDocument()
  expect(within(thu).queryByRole('link', { name: /HE1D/ })).not.toBeInTheDocument()
  const fri = screen.getByRole('region', { name: 'Fri 20 Nov' })
  expect(within(fri).getByText(/Blocked: Lift repair/)).toBeInTheDocument()
})

it('prev and next change the week', async () => {
  const mock = stubWeek({
    [scheduleUrl('2026-11-23', 7)]: { status: 200, body: { ...WEEK, days: [], items: [] } },
  })
  renderAt('/staff/week?date=2026-11-18')
  await screen.findByRole('region', { name: 'Mon 16 Nov' })
  await userEvent.setup().click(screen.getByRole('link', { name: 'Next week' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Week of 23 Nov' })).toBeInTheDocument()
  expect(mock.mock.calls.map(([url]) => url)).toContain(scheduleUrl('2026-11-23', 7))
  expect(screen.getByRole('link', { name: 'Previous week' })).toHaveAttribute('href', '/staff/week?date=2026-11-16')
})

it('has new booking and block time links', async () => {
  stubWeek()
  renderAt('/staff/week?date=2026-11-18')
  expect(await screen.findByRole('link', { name: '+ New booking' })).toHaveAttribute(
    'href',
    '/staff/bookings/new?date=2026-11-18',
  )
  expect(screen.getByRole('link', { name: '+ Block time' })).toHaveAttribute('href', '/staff/blocks/new?date=2026-11-18')
})
