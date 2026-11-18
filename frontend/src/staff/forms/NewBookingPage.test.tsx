import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { TIMETABLES, SERVICES } from '../../testing/fixtures.ts'
import { DAY_SCHEDULE, MOVE_OPTIONS, STAFF_BOOKING, scheduleUrl } from '../../testing/schedule.ts'
import type { Reply } from '../../testing/staffApi.tsx'
import { STAFF_ME, renderAt, sentBody, stubFetch } from '../../testing/staffApi.tsx'

const MOT_TIMES = '/api/staff/availability?services=mot-test&date=2026-11-17'
const MIXED_TIMES = '/api/staff/availability?services=mot-test&services=full-service&date=2026-11-17'
const MIXED = "These services can't be booked together — please book them separately"

function stubForm(post: Reply = { status: 201, body: { reference: 'PHON-EONE' } }) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    '/api/services': { status: 200, body: SERVICES },
    '/api/opening-hours': { status: 200, body: { timetables: TIMETABLES } },
    [`GET ${scheduleUrl('2026-11-17', 1)}`]: { status: 200, body: DAY_SCHEDULE },
    [`GET ${MOT_TIMES}`]: { status: 200, body: MOVE_OPTIONS },
    [`GET ${MIXED_TIMES}`]: {
      status: 200,
      body: { ...MOVE_OPTIONS, unavailable_reason: 'mixed_bay_types', slots: [] },
    },
    'POST /api/staff/bookings': post,
    'GET /api/staff/bookings/PHON-EONE': {
      status: 200,
      body: { ...STAFF_BOOKING, reference: 'PHON-EONE', source: 'phone', customer_email: null },
    },
  })
}

type User = ReturnType<typeof userEvent.setup>

async function fillCustomer(user: User, email = ''): Promise<void> {
  await user.type(screen.getByLabelText('Name'), 'Jane Smith')
  await user.type(screen.getByLabelText('Phone'), '07700 900123')
  if (email) await user.type(screen.getByLabelText('Email (optional)'), email)
  await user.type(screen.getByLabelText('Registration'), 'ab12 cde')
  await user.type(screen.getByLabelText('Make'), 'Ford')
  await user.type(screen.getByLabelText('Model'), 'Focus')
}

async function chooseMotAt11(user: User): Promise<void> {
  await user.click(await screen.findByRole('checkbox', { name: /MOT test/ }))
  await user.click(await screen.findByRole('button', { name: '11:00' }))
}

function posted(mock: ReturnType<typeof stubFetch>): boolean {
  return mock.mock.calls.some(([url, init]) => url === '/api/staff/bookings' && init?.method === 'POST')
}

afterEach(() => vi.unstubAllGlobals())

it('books a phone customer without an email', async () => {
  const mock = stubForm()
  renderAt('/staff/bookings/new?date=2026-11-17')
  expect(await screen.findByRole('heading', { level: 1, name: 'New phone booking' })).toBeInTheDocument()
  expect(screen.getByText('No deposit is taken for phone bookings.')).toBeInTheDocument()

  const user = userEvent.setup()
  await chooseMotAt11(user)
  await user.click(screen.getByRole('button', { name: 'Bay 1' }))
  await fillCustomer(user)
  await user.click(screen.getByRole('button', { name: 'Book it' }))

  expect(await screen.findByRole('heading', { level: 1, name: 'PHON-EONE · Confirmed' })).toBeInTheDocument()
  expect(sentBody(mock, '/api/staff/bookings')).toEqual({
    services: ['mot-test'],
    start: '2026-11-17T11:00:00+00:00',
    bay_id: 2,
    name: 'Jane Smith',
    phone: '07700 900123',
    email: null,
    registration: 'ab12 cde',
    make: 'Ford',
    model: 'Focus',
    notes: null,
  })
})

it('email is optional but checked when given', async () => {
  const mock = stubForm()
  renderAt('/staff/bookings/new?date=2026-11-17')
  const user = userEvent.setup()
  await chooseMotAt11(user)
  await fillCustomer(user, 'not-an-email')
  await user.click(screen.getByRole('button', { name: 'Book it' }))

  expect(screen.getByText('Please enter a valid email address')).toBeInTheDocument()
  expect(posted(mock)).toBe(false)

  await user.clear(screen.getByLabelText('Email (optional)'))
  await user.type(screen.getByLabelText('Email (optional)'), 'jane@example.test')
  await user.click(screen.getByRole('button', { name: 'Book it' }))
  await screen.findByRole('heading', { level: 1, name: 'PHON-EONE · Confirmed' })
  expect(sentBody(mock, '/api/staff/bookings')).toMatchObject({ email: 'jane@example.test' })
})

it('offers needs-approval services too', async () => {
  stubForm()
  renderAt('/staff/bookings/new?date=2026-11-17')
  expect(await screen.findByRole('checkbox', { name: /Clutch replacement/ })).toBeInTheDocument()
})

it('mixed bay types show the API message', async () => {
  stubForm()
  renderAt('/staff/bookings/new?date=2026-11-17')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('checkbox', { name: /MOT test/ }))
  await user.click(screen.getByRole('checkbox', { name: /Full service/ }))
  expect(await screen.findByText(MIXED)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '11:00' })).not.toBeInTheDocument()
})

it('asks for services and a time before sending', async () => {
  const mock = stubForm()
  renderAt('/staff/bookings/new?date=2026-11-17')
  const user = userEvent.setup()
  await screen.findByRole('checkbox', { name: /MOT test/ })
  await fillCustomer(user)
  await user.click(screen.getByRole('button', { name: 'Book it' }))
  expect(screen.getByText('Please choose at least one service')).toBeInTheDocument()

  await user.click(screen.getByRole('checkbox', { name: /MOT test/ }))
  await screen.findByRole('button', { name: '11:00' })
  await user.click(screen.getByRole('button', { name: 'Book it' }))
  expect(screen.getByText('Please choose a time')).toBeInTheDocument()
  expect(posted(mock)).toBe(false)
})

it('a taken time says so and reloads the times', async () => {
  const mock = stubForm({ status: 409, body: { detail: 'That time has just been taken' } })
  renderAt('/staff/bookings/new?date=2026-11-17')
  const user = userEvent.setup()
  await chooseMotAt11(user)
  await fillCustomer(user)
  await user.click(screen.getByRole('button', { name: 'Book it' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('That time has just been taken')
  expect(mock.mock.calls.filter(([url]) => url === MOT_TIMES)).toHaveLength(2)
  expect(screen.getByRole('button', { name: '11:00' })).toHaveAttribute('aria-pressed', 'false')
})

it("shows the server's message when it refuses the booking", async () => {
  stubForm({ status: 422, body: { detail: 'That time has already passed' } })
  renderAt('/staff/bookings/new?date=2026-11-17')
  const user = userEvent.setup()
  await chooseMotAt11(user)
  await fillCustomer(user)
  await user.click(screen.getByRole('button', { name: 'Book it' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('That time has already passed')
})
