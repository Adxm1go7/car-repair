import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { SERVICES, TIMETABLES } from '../../testing/fixtures.ts'
import { DAY_SCHEDULE, MOVE_OPTIONS, scheduleUrl } from '../../testing/schedule.ts'
import type { Reply } from '../../testing/staffApi.tsx'
import { STAFF_ME, renderAt, sentBody, stubFetch } from '../../testing/staffApi.tsx'
import type { StaffEnquiry } from '../types.ts'

const URL = '/api/staff/enquiries/7'
const MOT_TIMES = '/api/staff/availability?services=mot-test&date=2026-11-17'

const ENQUIRY: StaffEnquiry = {
  id: 7,
  status: 'new',
  customer_name: 'Jane Smith',
  customer_phone: '07700 900123',
  customer_email: 'jane@example.com',
  registration: 'AB12CDE',
  make: 'Ford',
  model: 'Focus',
  description: 'Rattle from the front left when braking',
  created_at: '2026-11-16T09:00:00+00:00',
  handled_at: null,
  handled_by: null,
  decline_reason: null,
  booking_reference: null,
  actions: ['approve', 'decline'],
}
const BOOKED: StaffEnquiry = {
  ...ENQUIRY,
  status: 'converted',
  handled_at: '2026-11-16T10:00:00+00:00',
  handled_by: 'Sam Staff',
  booking_reference: 'ENQU-IRYB',
  actions: [],
}

function stub(enquiry: StaffEnquiry, routes: Record<string, Reply> = {}) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    '/api/services': { status: 200, body: SERVICES },
    '/api/opening-hours': { status: 200, body: { timetables: TIMETABLES } },
    [`GET ${scheduleUrl('2026-11-17', 1)}`]: { status: 200, body: DAY_SCHEDULE },
    [`GET ${MOT_TIMES}`]: { status: 200, body: MOVE_OPTIONS },
    [`GET ${URL}`]: { status: 200, body: enquiry },
    ...routes,
  })
}

type User = ReturnType<typeof userEvent.setup>

async function chooseMotAt11(user: User): Promise<void> {
  await user.click(await screen.findByRole('checkbox', { name: /MOT test/ }))
  await user.click(await screen.findByRole('button', { name: '11:00' }))
  await user.click(screen.getByRole('button', { name: 'Bay 1' }))
}

afterEach(() => vi.unstubAllGlobals())

it('book enquiry starts from the enquiry', async () => {
  stub(ENQUIRY)
  renderAt('/staff/enquiries/7/book?date=2026-11-17')
  expect(await screen.findByRole('heading', { level: 1, name: 'Book enquiry' })).toBeInTheDocument()
  expect(screen.getByLabelText('Name')).toHaveValue('Jane Smith')
  expect(screen.getByLabelText('Phone')).toHaveValue('07700 900123')
  expect(screen.getByLabelText('Email')).toHaveValue('jane@example.com')
  expect(screen.getByLabelText('Registration')).toHaveValue('AB12CDE')
  expect(screen.getByLabelText('Make')).toHaveValue('Ford')
  expect(screen.getByLabelText('Model')).toHaveValue('Focus')
  expect(screen.getByLabelText('Notes (optional)')).toHaveValue('Rattle from the front left when braking')
  expect(screen.queryByText('No deposit is taken for phone bookings.')).not.toBeInTheDocument()
  expect(screen.getByText('No deposit is taken. The customer is emailed the booking.')).toBeInTheDocument()
})

it('book enquiry needs an email', async () => {
  const mock = stub(ENQUIRY)
  renderAt('/staff/enquiries/7/book?date=2026-11-17')
  const user = userEvent.setup()
  await chooseMotAt11(user)
  await user.clear(await screen.findByLabelText('Email'))
  await user.click(screen.getByRole('button', { name: 'Book it' }))
  expect(screen.getByText('Please enter a valid email address')).toBeInTheDocument()
  expect(mock.mock.calls.some(([url]) => url === `${URL}/approve`)).toBe(false)
})

it('booking it approves the enquiry', async () => {
  const mock = stub(ENQUIRY, { [`POST ${URL}/approve`]: { status: 200, body: BOOKED } })
  renderAt('/staff/enquiries/7/book?date=2026-11-17')
  const user = userEvent.setup()
  await chooseMotAt11(user)
  await user.click(screen.getByRole('button', { name: 'Book it' }))
  expect(await screen.findByText('Booked — the customer has been emailed')).toBeInTheDocument()
  expect(mock.mock.calls.some(([url, init]) => url === '/api/staff/bookings' && init?.method === 'POST')).toBe(false)
  expect(sentBody(mock, `${URL}/approve`)).toEqual({
    services: ['mot-test'],
    start: '2026-11-17T11:00:00+00:00',
    bay_id: 2,
    name: 'Jane Smith',
    phone: '07700 900123',
    email: 'jane@example.com',
    registration: 'AB12CDE',
    make: 'Ford',
    model: 'Focus',
    notes: 'Rattle from the front left when braking',
  })
})

it('already handled says so', async () => {
  stub(ENQUIRY, { [`POST ${URL}/approve`]: { status: 409, body: { detail: 'not_new' } } })
  renderAt('/staff/enquiries/7/book?date=2026-11-17')
  const user = userEvent.setup()
  await chooseMotAt11(user)
  await user.click(screen.getByRole('button', { name: 'Book it' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('This enquiry has already been dealt with')
})

it('a taken time says so', async () => {
  stub(ENQUIRY, {
    [`POST ${URL}/approve`]: { status: 409, body: { detail: 'That time has just been taken' } },
  })
  renderAt('/staff/enquiries/7/book?date=2026-11-17')
  const user = userEvent.setup()
  await chooseMotAt11(user)
  await user.click(screen.getByRole('button', { name: 'Book it' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('That time has just been taken')
})

it('an enquiry already dealt with is not offered for booking', async () => {
  stub(BOOKED)
  renderAt('/staff/enquiries/7/book')
  expect(await screen.findByText('This enquiry has already been dealt with')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Back to the enquiry' })).toHaveAttribute('href', '/staff/enquiries/7')
  expect(screen.queryByRole('button', { name: 'Book it' })).not.toBeInTheDocument()
})
