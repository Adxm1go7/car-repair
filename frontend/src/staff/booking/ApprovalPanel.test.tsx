import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { DAY_SCHEDULE, MOVE_OPTIONS, STAFF_BOOKING, scheduleUrl } from '../../testing/schedule.ts'
import type { Reply } from '../../testing/staffApi.tsx'
import { STAFF_ME, renderAt, sentBody, stubFetch } from '../../testing/staffApi.tsx'
import type { StaffBooking } from '../types.ts'

const URL = '/api/staff/bookings/ABCD-EFGH'

const REQUEST: StaffBooking = {
  ...STAFF_BOOKING,
  status: 'pending_approval',
  services: ['Clutch replacement'],
  deposit_status: 'unpaid',
  deadline: '2026-11-18T09:00:00+00:00',
  actions: ['approve', 'propose', 'decline'],
  history: [],
}
const APPROVED: StaffBooking = {
  ...REQUEST,
  status: 'awaiting_deposit',
  deadline: '2026-11-17T09:00:00+00:00',
  actions: ['propose', 'cancel'],
  history: [{ at: '2026-11-16T09:00:00+00:00', text: 'Approved by Sam Staff' }],
}
const DECLINED: StaffBooking = { ...REQUEST, status: 'cancelled', deadline: null, actions: [] }

function stub(booking: StaffBooking, routes: Record<string, Reply> = {}) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    [`GET ${URL}`]: { status: 200, body: booking },
    [`GET ${URL}/move-options?date=2026-11-17`]: { status: 200, body: MOVE_OPTIONS },
    [`GET ${scheduleUrl('2026-11-17', 1)}`]: { status: 200, body: DAY_SCHEDULE },
    ...routes,
  })
}

function buttonNames(): string[] {
  return within(screen.getByRole('group', { name: 'Actions' }))
    .getAllByRole('button')
    .map((b) => b.textContent ?? '')
}

afterEach(() => vi.unstubAllGlobals())

it('a request offers approve, propose and decline, and says when to reply by', async () => {
  stub(REQUEST)
  renderAt('/staff/bookings/ABCD-EFGH')
  expect(await screen.findByRole('heading', { level: 1, name: 'ABCD-EFGH · Request' })).toBeInTheDocument()
  expect(screen.getByText('Reply by Wed 18 Nov, 09:00')).toBeInTheDocument()
  expect(buttonNames()).toEqual(['Approve', 'Propose another time', 'Decline'])
})

it('approve asks to confirm, then says the customer has been emailed', async () => {
  const mock = stub(REQUEST, { [`POST ${URL}/approve`]: { status: 200, body: APPROVED } })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Approve' }))
  expect(
    screen.getByText('Approve this request? The customer will be emailed to pay the £20 deposit within 24 hours.'),
  ).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Yes, approve' }))
  expect(await screen.findByText('Approved — the customer has been emailed')).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 1, name: 'ABCD-EFGH · Awaiting deposit' })).toBeInTheDocument()
  expect(screen.getByText('Deposit due by Tue 17 Nov, 09:00')).toBeInTheDocument()
  expect(sentBody(mock, `${URL}/approve`)).toEqual({})
})

it('approve too close to the time says so', async () => {
  stub(REQUEST, { [`POST ${URL}/approve`]: { status: 409, body: { detail: 'too_soon' } } })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Approve' }))
  await user.click(screen.getByRole('button', { name: 'Yes, approve' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Too soon for the customer to pay — propose a later time',
  )
})

it('propose picks a new time after phoning the customer', async () => {
  const proposed = { ...APPROVED, start: '2026-11-17T11:00:00+00:00', end: '2026-11-17T12:00:00+00:00' }
  const mock = stub(REQUEST, { [`POST ${URL}/propose`]: { status: 200, body: proposed } })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Propose another time' }))
  expect(screen.getByRole('heading', { name: 'Propose another time' })).toBeInTheDocument()
  expect(screen.getByText('Phone the customer first and agree the new time.')).toBeInTheDocument()
  await user.click(await screen.findByRole('button', { name: '11:00' }))
  await user.click(screen.getByRole('button', { name: 'Propose this time' }))
  expect(screen.getByText('Propose Tue 17 Nov, 11:00 · MOT bay?')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Yes, propose it' }))
  expect(await screen.findByText('New time proposed — the customer has been emailed')).toBeInTheDocument()
  expect(sentBody(mock, `${URL}/propose`)).toEqual({
    start: '2026-11-17T11:00:00+00:00',
    bay_id: 1,
    reason: null,
  })
})

it('propose too soon for the customer to pay says so', async () => {
  stub(REQUEST, { [`POST ${URL}/propose`]: { status: 409, body: { detail: 'too_soon' } } })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Propose another time' }))
  await user.click(await screen.findByRole('button', { name: '11:00' }))
  await user.click(screen.getByRole('button', { name: 'Propose this time' }))
  await user.click(screen.getByRole('button', { name: 'Yes, propose it' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Too soon for the customer to pay — choose a later time')
})

it('decline takes an optional reason and confirms', async () => {
  const mock = stub(REQUEST, { [`POST ${URL}/decline`]: { status: 200, body: DECLINED } })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Decline' }))
  await user.type(screen.getByLabelText('Reason (optional)'), 'We need to see it first')
  await user.click(screen.getByRole('button', { name: 'Decline request' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'ABCD-EFGH · Cancelled' })).toBeInTheDocument()
  expect(sentBody(mock, `${URL}/decline`)).toEqual({ reason: 'We need to see it first' })
})

it('an approval waiting for its deposit can be proposed again or cancelled', async () => {
  stub(APPROVED)
  renderAt('/staff/bookings/ABCD-EFGH')
  await screen.findByRole('heading', { level: 1, name: 'ABCD-EFGH · Awaiting deposit' })
  expect(buttonNames()).toEqual(['Propose another time', 'Cancel booking'])
})
