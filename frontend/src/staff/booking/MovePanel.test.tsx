import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { DAY_SCHEDULE, MOVE_OPTIONS, STAFF_BOOKING, scheduleUrl } from '../../testing/schedule.ts'
import type { Reply } from '../../testing/staffApi.tsx'
import { STAFF_ME, renderAt, sentBody, stubFetch } from '../../testing/staffApi.tsx'
import type { StaffBooking } from '../types.ts'

const URL = '/api/staff/bookings/ABCD-EFGH'
const OPTIONS = (date: string): string => `${URL}/move-options?date=${date}`

const MOVED: StaffBooking = {
  ...STAFF_BOOKING,
  start: '2026-11-17T11:00:00+00:00',
  end: '2026-11-17T12:00:00+00:00',
  bay: { id: 2, name: 'Bay 1' },
}

function stubMove(booking: StaffBooking, move: Reply) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    [`GET ${URL}`]: { status: 200, body: booking },
    [`GET ${OPTIONS('2026-11-17')}`]: { status: 200, body: MOVE_OPTIONS },
    [`GET ${OPTIONS('2026-11-18')}`]: { status: 200, body: { ...MOVE_OPTIONS, date: '2026-11-18', slots: [] } },
    [`GET ${scheduleUrl('2026-11-17', 1)}`]: { status: 200, body: DAY_SCHEDULE },
    [`POST ${URL}/move`]: move,
  })
}

function optionCalls(mock: ReturnType<typeof stubFetch>): number {
  return mock.mock.calls.filter(([url]) => url === OPTIONS('2026-11-17')).length
}

async function openMove(): Promise<ReturnType<typeof userEvent.setup>> {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Move' }))
  return user
}

afterEach(() => vi.unstubAllGlobals())

it('move picks a time and bay and confirms', async () => {
  const mock = stubMove(STAFF_BOOKING, { status: 200, body: MOVED })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = await openMove()

  expect(screen.getByLabelText('Date')).toHaveValue('2026-11-17')
  await user.click(await screen.findByRole('button', { name: '11:00' }))
  // The first bay that can take it is chosen, and the others offered.
  expect(screen.getByRole('button', { name: 'MOT bay' })).toHaveAttribute('aria-pressed', 'true')
  await user.click(screen.getByRole('button', { name: 'Bay 1' }))
  expect(screen.getByRole('button', { name: 'Bay 1' })).toHaveAttribute('aria-pressed', 'true')
  await user.type(screen.getByLabelText('Reason (optional)'), 'Lift broken')
  await user.click(screen.getByRole('button', { name: 'Move booking' }))

  expect(screen.getByText('Move to Tue 17 Nov, 11:00 · Bay 1?')).toBeInTheDocument()
  expect(screen.getByText("Have you called the customer? They'll be emailed the new time.")).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Yes, move it' }))

  expect(await screen.findByText('Tue 17 Nov, 11:00 – 12:00 · Bay 1')).toBeInTheDocument()
  expect(sentBody(mock, `${URL}/move`)).toEqual({ start: '2026-11-17T11:00:00+00:00', bay_id: 2, reason: 'Lift broken' })
  expect(screen.queryByRole('button', { name: 'Yes, move it' })).not.toBeInTheDocument()
})

it('sends no reason when none is typed', async () => {
  const mock = stubMove(STAFF_BOOKING, { status: 200, body: MOVED })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = await openMove()
  await user.click(await screen.findByRole('button', { name: '13:00' }))
  await user.click(screen.getByRole('button', { name: 'Move booking' }))
  await user.click(screen.getByRole('button', { name: 'Yes, move it' }))
  await screen.findByText(/Bay 1$/)
  expect(sentBody(mock, `${URL}/move`)).toEqual({ start: '2026-11-17T13:00:00+00:00', bay_id: 2, reason: null })
})

it('a new date loads its times', async () => {
  stubMove(STAFF_BOOKING, { status: 200, body: MOVED })
  renderAt('/staff/bookings/ABCD-EFGH')
  await openMove()
  await screen.findByRole('button', { name: '11:00' })
  fireEvent.change(screen.getByLabelText('Date'), { target: { value: '2026-11-18' } })
  expect(await screen.findByText('No free times that day')).toBeInTheDocument()
})

it('move into a taken time reloads the times', async () => {
  const mock = stubMove(STAFF_BOOKING, { status: 409, body: { detail: 'taken' } })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = await openMove()
  await user.click(await screen.findByRole('button', { name: '11:00' }))
  await user.click(screen.getByRole('button', { name: 'Move booking' }))
  await user.click(screen.getByRole('button', { name: 'Yes, move it' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('That time has just been taken')
  expect(optionCalls(mock)).toBe(2)
  expect(screen.getByRole('button', { name: 'Move booking' })).toBeDisabled()
})

it('a move no longer allowed reloads the booking', async () => {
  const mock = stubMove(STAFF_BOOKING, { status: 409, body: { detail: 'not_allowed' } })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = await openMove()
  await user.click(await screen.findByRole('button', { name: '11:00' }))
  await user.click(screen.getByRole('button', { name: 'Move booking' }))
  await user.click(screen.getByRole('button', { name: 'Yes, move it' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('That has changed since you opened this page')
  expect(mock.mock.calls.filter(([url, init]) => url === URL && (init?.method ?? 'GET') === 'GET')).toHaveLength(2)
  expect(screen.queryByLabelText('Date')).not.toBeInTheDocument()
})

it('phone booking without email warns on move', async () => {
  stubMove({ ...STAFF_BOOKING, source: 'phone', customer_email: null }, { status: 200, body: MOVED })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = await openMove()
  await user.click(await screen.findByRole('button', { name: '11:00' }))
  await user.click(screen.getByRole('button', { name: 'Move booking' }))
  expect(screen.getByText('Have you called the customer? They have no email, so remember to tell them.')).toBeInTheDocument()
})

it('back from the confirm step keeps the choice', async () => {
  stubMove(STAFF_BOOKING, { status: 200, body: MOVED })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = await openMove()
  await user.click(await screen.findByRole('button', { name: '11:00' }))
  await user.click(screen.getByRole('button', { name: 'Move booking' }))
  await user.click(screen.getByRole('button', { name: 'Back' }))
  expect(screen.getByRole('button', { name: '11:00' })).toHaveAttribute('aria-pressed', 'true')
})
