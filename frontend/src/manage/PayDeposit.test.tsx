import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import type { BookingSummary } from '../booking/types.ts'
import { GARAGE } from '../testing/fixtures.ts'
import { ManageBookingPage } from './ManageBookingPage.tsx'
import type { MyBooking } from './types.ts'

// The booking link for a request (waiting for staff) and an approval (waiting to be paid).

const SUMMARY: BookingSummary = {
  reference: 'ABCD-EFGH',
  status: 'pending_approval',
  start: '2026-11-20T09:00:00+00:00',
  end: '2026-11-20T10:00:00+00:00',
  services: [
    {
      slug: 'clutch-replacement',
      name: 'Clutch replacement',
      duration_minutes: 60,
      price_from_pence: 45000,
      price_to_pence: 75000,
    },
  ],
  registration: 'AB12CDE',
  make: 'Ford',
  model: 'Focus',
  deposit_paid_pence: 0,
}
const REQUEST: MyBooking = {
  summary: SUMMARY,
  deposit_status: 'unpaid',
  can_cancel: true,
  refund_if_cancelled: false,
  free_cancellation_until: '2026-11-19T09:00:00+00:00',
  deadline: '2026-11-18T09:00:00+00:00',
}
const APPROVED: MyBooking = { ...REQUEST, summary: { ...SUMMARY, status: 'awaiting_deposit' } }
const CONFIRMED: MyBooking = {
  ...REQUEST,
  summary: { ...SUMMARY, status: 'confirmed', deposit_paid_pence: 2000 },
  deposit_status: 'paid',
  refund_if_cancelled: true,
  deadline: null,
}
const EXPIRED: MyBooking = {
  ...REQUEST,
  summary: { ...SUMMARY, status: 'expired' },
  can_cancel: false,
  deadline: null,
}
const CANCELLED: MyBooking = { ...EXPIRED, summary: { ...SUMMARY, status: 'cancelled' } }
const POLICY = {
  booking_window_days: 60,
  slot_hold_minutes: 5,
  payment_hold_minutes: 10,
  deposit_amount_pence: 2000,
  payment: { provider: 'demo' },
}
const CHECKOUT = { client_secret: null, demo_session: 'demo_abc', expires_in_seconds: 86400, amount_pence: 2000 }

type Stub = { views: MyBooking[]; pay?: number }

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

/** `views` are the view replies in turn; the last one repeats. */
function stubApi({ views, pay = 200 }: Stub): ReturnType<typeof vi.fn> {
  let viewed = 0
  const fetchMock = vi.fn((url: string) => {
    if (url.endsWith('/view')) {
      const booking = views[Math.min(viewed, views.length - 1)]
      viewed += 1
      return Promise.resolve(json(booking))
    }
    if (url === '/api/booking-policy') return Promise.resolve(json(POLICY))
    if (url.endsWith('/pay')) {
      return Promise.resolve(pay === 200 ? json(CHECKOUT) : json({ detail: 'Nothing to pay' }, pay))
    }
    if (url === '/api/demo/checkout/demo_abc') return Promise.resolve(json({ status: 'confirmed' }))
    if (url.endsWith('/cancel')) return Promise.resolve(json(CANCELLED))
    return Promise.resolve(json({}, 404))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderPage(): void {
  render(
    <MemoryRouter initialEntries={[{ pathname: '/booking/ABCD-EFGH', hash: '#t=tok' }]}>
      <Routes>
        <Route path="/booking/:reference" element={<ManageBookingPage garage={GARAGE} pollMs={1} />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

it('tells a customer with a request when to expect an answer', async () => {
  stubApi({ views: [REQUEST] })
  renderPage()
  expect(
    await screen.findByText("We're checking your request and will email you by Wednesday 18 November at 09:00."),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Cancel request' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Pay deposit' })).not.toBeInTheDocument()
})

it('cancelling a request says nothing about refunds', async () => {
  const fetchMock = stubApi({ views: [REQUEST] })
  renderPage()
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Cancel request' }))
  expect(screen.queryByText(/deposit back|refund/i)).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Yes, cancel it' }))
  expect(await screen.findByText('This booking is cancelled')).toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/cancel'))).toBe(true)
})

it('an approval is paid from the link and shows the confirmed booking', async () => {
  const fetchMock = stubApi({ views: [APPROVED, APPROVED, CONFIRMED] })
  renderPage()
  const user = userEvent.setup()
  expect(
    await screen.findByText('Pay the £20 deposit by Wednesday 18 November at 09:00 to confirm.'),
  ).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Pay deposit' }))
  await user.click(await screen.findByRole('button', { name: 'Pay £20 (demo)' }))
  expect(await screen.findByText('Your booking is confirmed')).toBeInTheDocument()
  expect(screen.getByText('Deposit: £20 paid')).toBeInTheDocument()
  const pay = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/pay'))
  expect(JSON.parse(String((pay?.[1] as RequestInit).body))).toEqual({ token: 'tok' })
})

it('says when the approval can no longer be paid', async () => {
  stubApi({ views: [APPROVED, EXPIRED], pay: 409 })
  renderPage()
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Pay deposit' }))
  expect(
    await screen.findByText(
      (_, element) =>
        element?.tagName === 'P' &&
        element.textContent === "This booking can't be paid for any more. Please call us on 01632 960123.",
    ),
  ).toBeInTheDocument()
  expect(await screen.findByText('The time we were keeping for you has been released')).toBeInTheDocument()
})
