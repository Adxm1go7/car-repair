import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { STAFF_BOOKING } from '../../testing/schedule.ts'
import type { Reply } from '../../testing/staffApi.tsx'
import { STAFF_ME, renderAt, sentBody, stubFetch } from '../../testing/staffApi.tsx'
import type { StaffBooking } from '../types.ts'

const URL = '/api/staff/bookings/ABCD-EFGH'

const CANCELLED: StaffBooking = { ...STAFF_BOOKING, status: 'cancelled', deposit_status: 'refund_pending', actions: [] }

function stubCancel(cancel: Reply, booking: StaffBooking = STAFF_BOOKING) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    [`GET ${URL}`]: { status: 200, body: booking },
    [`POST ${URL}/cancel`]: cancel,
  })
}

async function cancelWith(reason: string | null): Promise<void> {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Cancel booking' }))
  if (reason) await user.type(screen.getByLabelText('Reason (optional)'), reason)
  await user.click(screen.getByRole('button', { name: 'Cancel this booking' }))
  await user.click(screen.getByRole('button', { name: 'Yes, cancel it' }))
}

afterEach(() => vi.unstubAllGlobals())

it('cancels with a reason after confirming', async () => {
  const mock = stubCancel({ status: 200, body: CANCELLED })
  renderAt('/staff/bookings/ABCD-EFGH')
  await cancelWith('Part not in stock')
  expect(await screen.findByRole('heading', { level: 1, name: 'ABCD-EFGH · Cancelled' })).toBeInTheDocument()
  expect(screen.getByText('Deposit refund on its way')).toBeInTheDocument()
  expect(sentBody(mock, `${URL}/cancel`)).toEqual({ reason: 'Part not in stock' })
})

it('the confirm step says the customer is emailed and refunded', async () => {
  stubCancel({ status: 200, body: CANCELLED })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Cancel booking' }))
  await user.click(screen.getByRole('button', { name: 'Cancel this booking' }))
  expect(screen.getByText("Have you called the customer? They'll be emailed, and their deposit refunded.")).toBeInTheDocument()
})

it('the confirm step warns when there is no email', async () => {
  stubCancel({ status: 200, body: CANCELLED }, { ...STAFF_BOOKING, customer_email: null, deposit_status: 'not_required' })
  renderAt('/staff/bookings/ABCD-EFGH')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Cancel booking' }))
  await user.click(screen.getByRole('button', { name: 'Cancel this booking' }))
  expect(screen.getByText('Have you called the customer? They have no email, so remember to tell them.')).toBeInTheDocument()
})

it('cancel shows the 503 message', async () => {
  stubCancel({ status: 503, body: { detail: "We couldn't cancel just now" } })
  renderAt('/staff/bookings/ABCD-EFGH')
  await cancelWith(null)
  expect(await screen.findByRole('alert')).toHaveTextContent("We couldn't cancel just now. Please try again.")
  expect(screen.getByRole('heading', { level: 1, name: 'ABCD-EFGH · Confirmed' })).toBeInTheDocument()
})

it('a cancel no longer allowed reloads the booking', async () => {
  const mock = stubCancel({ status: 409, body: { detail: 'not_allowed' } })
  renderAt('/staff/bookings/ABCD-EFGH')
  await cancelWith(null)
  expect(await screen.findByRole('alert')).toHaveTextContent('That has changed since you opened this page')
  expect(mock.mock.calls.filter(([url, init]) => url === URL && (init?.method ?? 'GET') === 'GET')).toHaveLength(2)
})
