import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import type { Reply } from '../../testing/staffApi.tsx'
import { STAFF_ME, renderAt, sentBody, stubFetch } from '../../testing/staffApi.tsx'
import type { StaffEnquiry } from '../types.ts'

const URL = '/api/staff/enquiries/7'

const ENQUIRY: StaffEnquiry = {
  id: 7,
  status: 'new',
  customer_name: 'Jane Smith',
  customer_phone: '07700 900123',
  customer_email: 'jane@example.com',
  registration: 'AB12CDE',
  make: 'Ford',
  model: 'Focus',
  description: 'Rattle from the front left when braking.\nWorse when cold.',
  created_at: '2026-11-18T09:00:00+00:00',
  handled_at: null,
  handled_by: null,
  decline_reason: null,
  booking_reference: null,
  actions: ['approve', 'decline'],
}
const DECLINED: StaffEnquiry = {
  ...ENQUIRY,
  status: 'declined',
  handled_at: '2026-11-19T10:15:00+00:00',
  handled_by: 'Sam Staff',
  decline_reason: 'Too busy this month',
  actions: [],
}
const BOOKED: StaffEnquiry = {
  ...ENQUIRY,
  status: 'converted',
  handled_at: '2026-11-19T10:15:00+00:00',
  handled_by: 'Sam Staff',
  booking_reference: 'ABCD-EFGH',
  actions: [],
}

function stub(enquiry: StaffEnquiry, routes: Record<string, Reply> = {}) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    [`GET ${URL}`]: { status: 200, body: enquiry },
    ...routes,
  })
}

afterEach(() => vi.unstubAllGlobals())

it('an enquiry page shows the details and its actions', async () => {
  stub(ENQUIRY)
  renderAt('/staff/enquiries/7')
  expect(await screen.findByRole('heading', { level: 1, name: 'Enquiry · New' })).toBeInTheDocument()
  expect(screen.getByText('Jane Smith')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '07700 900123' })).toHaveAttribute('href', 'tel:07700900123')
  expect(screen.getByText('jane@example.com')).toBeInTheDocument()
  expect(screen.getByText('AB12CDE · Ford Focus')).toBeInTheDocument()
  expect(screen.getByText(/Rattle from the front left when braking\.\s+Worse when cold\./)).toBeInTheDocument()
  expect(screen.getByText('Sent Wed 18 Nov, 09:00')).toBeInTheDocument()
  const actions = within(screen.getByRole('group', { name: 'Actions' }))
  expect(actions.getByRole('link', { name: 'Approve and book' })).toHaveAttribute('href', '/staff/enquiries/7/book')
  expect(actions.getByRole('button', { name: 'Decline' })).toBeInTheDocument()
})

it('decline takes an optional reason', async () => {
  const mock = stub(ENQUIRY, { [`POST ${URL}/decline`]: { status: 200, body: DECLINED } })
  renderAt('/staff/enquiries/7')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Decline' }))
  await user.type(screen.getByLabelText('Reason (optional)'), ' Too busy this month ')
  await user.click(screen.getByRole('button', { name: 'Decline enquiry' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Enquiry · Declined' })).toBeInTheDocument()
  expect(screen.getByText('Declined — the customer has been emailed')).toBeInTheDocument()
  expect(screen.getByText('Declined by Sam Staff, Thu 19 Nov, 10:15')).toBeInTheDocument()
  expect(screen.getByText('Reason: Too busy this month')).toBeInTheDocument()
  expect(sentBody(mock, `${URL}/decline`)).toEqual({ reason: 'Too busy this month' })
  expect(screen.queryByRole('group', { name: 'Actions' })).not.toBeInTheDocument()
})

it('decline with no reason sends null', async () => {
  const mock = stub(ENQUIRY, { [`POST ${URL}/decline`]: { status: 200, body: DECLINED } })
  renderAt('/staff/enquiries/7')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Decline' }))
  await user.click(screen.getByRole('button', { name: 'Decline enquiry' }))
  await screen.findByRole('heading', { level: 1, name: 'Enquiry · Declined' })
  expect(sentBody(mock, `${URL}/decline`)).toEqual({ reason: null })
})

it('decline already handled says so', async () => {
  stub(ENQUIRY, { [`POST ${URL}/decline`]: { status: 409, body: { detail: 'not_new' } } })
  renderAt('/staff/enquiries/7')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Decline' }))
  await user.click(screen.getByRole('button', { name: 'Decline enquiry' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('This enquiry has already been dealt with')
})

it('a booked enquiry links to its booking', async () => {
  stub(BOOKED)
  renderAt('/staff/enquiries/7')
  expect(await screen.findByRole('heading', { level: 1, name: 'Enquiry · Booked' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'ABCD-EFGH' })).toHaveAttribute('href', '/staff/bookings/ABCD-EFGH')
  expect(screen.getByText('Booked by Sam Staff, Thu 19 Nov, 10:15')).toBeInTheDocument()
  expect(screen.queryByRole('group', { name: 'Actions' })).not.toBeInTheDocument()
})

it('an unknown enquiry says so', async () => {
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    [`GET ${URL}`]: { status: 404, body: { detail: 'No such enquiry' } },
  })
  renderAt('/staff/enquiries/7')
  expect(await screen.findByText('No such enquiry.')).toBeInTheDocument()
})
