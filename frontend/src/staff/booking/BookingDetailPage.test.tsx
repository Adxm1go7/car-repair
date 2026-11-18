import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { STAFF_BOOKING } from '../../testing/schedule.ts'
import type { Reply } from '../../testing/staffApi.tsx'
import { STAFF_ME, renderAt, sentBody, stubFetch } from '../../testing/staffApi.tsx'
import type { StaffBooking } from '../types.ts'

const URL = '/api/staff/bookings/ABCD-EFGH'

function stubBooking(booking: StaffBooking, extra: Record<string, Reply> = {}) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    [`GET ${URL}`]: { status: 200, body: booking },
    ...extra,
  })
}

function buttonNames(): string[] {
  const actions = screen.getByRole('group', { name: 'Actions' })
  return within(actions)
    .getAllByRole('button')
    .map((b) => b.textContent ?? '')
}

function bookingCalls(mock: ReturnType<typeof stubFetch>): number {
  return mock.mock.calls.filter(([url, init]) => url === URL && (init?.method ?? 'GET') === 'GET').length
}

afterEach(() => vi.unstubAllGlobals())

it('shows the booking laid out as the sketch', async () => {
  stubBooking(STAFF_BOOKING)
  renderAt('/staff/bookings/ABCD-EFGH')
  expect(await screen.findByRole('heading', { level: 1, name: 'ABCD-EFGH · Confirmed' })).toBeInTheDocument()
  expect(screen.getByText('Tue 17 Nov, 09:30 – 10:30 · MOT bay')).toBeInTheDocument()
  expect(screen.getByText('MOT test')).toBeInTheDocument()
  expect(screen.getByText('AB12CDE · Ford Focus')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '07700 900123' })).toHaveAttribute('href', 'tel:07700900123')
  expect(screen.getByText('jane@example.test')).toBeInTheDocument()
  expect(screen.getByText('Notes: "Rattle from the back left"')).toBeInTheDocument()
  expect(screen.getByText('Deposit paid')).toBeInTheDocument()
})

it('shows only the allowed buttons', async () => {
  stubBooking(STAFF_BOOKING)
  renderAt('/staff/bookings/ABCD-EFGH')
  await screen.findByRole('heading', { level: 1 })
  expect(buttonNames()).toEqual(['Start job', 'Move', 'Cancel booking'])
})

it('shows complete and undo start for a job in progress', async () => {
  stubBooking({ ...STAFF_BOOKING, status: 'in_progress', actions: ['complete', 'undo_start'] })
  renderAt('/staff/bookings/ABCD-EFGH')
  await screen.findByRole('heading', { level: 1, name: 'ABCD-EFGH · In progress' })
  expect(buttonNames()).toEqual(['Complete job', 'Undo start'])
})

it('shows no buttons when nothing is allowed', async () => {
  stubBooking({ ...STAFF_BOOKING, status: 'completed', actions: [] })
  renderAt('/staff/bookings/ABCD-EFGH')
  await screen.findByRole('heading', { level: 1, name: 'ABCD-EFGH · Completed' })
  expect(screen.queryByRole('group', { name: 'Actions' })).not.toBeInTheDocument()
})

it('start on another day asks first', async () => {
  const started: StaffBooking = { ...STAFF_BOOKING, status: 'in_progress', actions: ['complete', 'undo_start'] }
  const mock = stubBooking(
    { ...STAFF_BOOKING, starts_on_another_day: true },
    { [`POST ${URL}/status`]: { status: 200, body: started } },
  )
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Start job' }))

  expect(screen.getByText('This job is booked for Tue 17 Nov. Start it now?')).toBeInTheDocument()
  expect(mock.mock.calls.some(([url]) => url === `${URL}/status`)).toBe(false)

  await user.click(screen.getByRole('button', { name: 'Yes, start it' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'ABCD-EFGH · In progress' })).toBeInTheDocument()
  expect(sentBody(mock, `${URL}/status`)).toEqual({ action: 'start' })
})

it('start on the day itself does not ask', async () => {
  const started: StaffBooking = { ...STAFF_BOOKING, status: 'in_progress', actions: ['complete', 'undo_start'] }
  stubBooking(STAFF_BOOKING, { [`POST ${URL}/status`]: { status: 200, body: started } })
  renderAt('/staff/bookings/ABCD-EFGH')
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Start job' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'ABCD-EFGH · In progress' })).toBeInTheDocument()
})

it('a status change no longer allowed reloads the booking', async () => {
  const mock = stubBooking(STAFF_BOOKING, {
    [`POST ${URL}/status`]: { status: 409, body: { detail: 'not_allowed' } },
  })
  renderAt('/staff/bookings/ABCD-EFGH')
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Start job' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('That has changed since you opened this page')
  expect(bookingCalls(mock)).toBe(2)
})

it('history lists entries', async () => {
  stubBooking(STAFF_BOOKING)
  renderAt('/staff/bookings/ABCD-EFGH')
  const history = await screen.findByRole('list', { name: 'History' })
  const rows = within(history).getAllByRole('listitem')
  expect(rows.map((r) => r.textContent)).toEqual([
    '16 Nov 14:02Booked online',
    '17 Nov 08:10Moved from Tue 17 Nov 09:00 by Sam Staff — "Lift broken"',
  ])
})

it('shows a phone booking with no email and no deposit', async () => {
  stubBooking({ ...STAFF_BOOKING, source: 'phone', customer_email: null, deposit_status: 'not_required' })
  renderAt('/staff/bookings/ABCD-EFGH')
  expect(await screen.findByText('No email, phone only')).toBeInTheDocument()
  expect(screen.getByText('Phone booking · no deposit')).toBeInTheDocument()
})

it('says so when the booking does not exist', async () => {
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'GET /api/staff/bookings/NOPE-NOPE': { status: 404, body: { detail: 'No such booking' } },
  })
  renderAt('/staff/bookings/NOPE-NOPE')
  expect(await screen.findByRole('alert')).toHaveTextContent("couldn't find that booking")
})
