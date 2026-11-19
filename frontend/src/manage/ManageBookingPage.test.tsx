import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import type { BookingSummary } from '../booking/types.ts'
import { GARAGE } from '../testing/fixtures.ts'
import { ManageBookingPage } from './ManageBookingPage.tsx'
import type { MyBooking } from './types.ts'

const SUMMARY: BookingSummary = {
  reference: 'ABCD-EFGH',
  status: 'confirmed',
  start: '2026-11-20T09:00:00+00:00',
  end: '2026-11-20T10:00:00+00:00',
  services: [
    { slug: 'mot-test', name: 'MOT test', duration_minutes: 60, price_from_pence: 5485, price_to_pence: null },
  ],
  registration: 'AB12CDE',
  make: 'Ford',
  model: 'Focus',
  deposit_paid_pence: 2000,
}
const CAN_CANCEL: MyBooking = {
  summary: SUMMARY,
  deposit_status: 'paid',
  can_cancel: true,
  refund_if_cancelled: true,
  free_cancellation_until: '2026-11-19T09:00:00+00:00',
}
const INSIDE_WINDOW: MyBooking = { ...CAN_CANCEL, can_cancel: false, refund_if_cancelled: false }
const CANCELLED: MyBooking = {
  ...INSIDE_WINDOW,
  summary: { ...SUMMARY, status: 'cancelled' },
  deposit_status: 'refund_pending',
}

const CALL_LINE = "Need a different time? Call us on 01632 960123 and we'll sort it out."
const INVALID = "This link isn't valid any more. Please call us on 01632 960123."

type Reply = { status: number; body: unknown }

function json({ status, body }: Reply): Response {
  return new Response(JSON.stringify(body), { status })
}

/** Answers view and cancel by URL. Returns the fetch mock so tests can check calls. */
function stubApi(view: Reply, cancel: Reply = { status: 200, body: CANCELLED }) {
  const fetchMock = vi.fn((url: string) =>
    Promise.resolve(json(url.endsWith('/cancel') ? cancel : view)),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function cancelCalls(fetchMock: ReturnType<typeof stubApi>): number {
  return fetchMock.mock.calls.filter(([url]) => url.endsWith('/cancel')).length
}

function renderPage(hash = '#t=tok'): void {
  render(
    <MemoryRouter initialEntries={[{ pathname: '/booking/ABCD-EFGH', hash }]}>
      <Routes>
        <Route path="/booking/:reference" element={<ManageBookingPage garage={GARAGE} />} />
      </Routes>
    </MemoryRouter>,
  )
}

/** A paragraph whose whole text is `text`, even with the phone link inside it. */
function sentence(text: string) {
  return (_: string, element: Element | null): boolean => element?.tagName === 'P' && element.textContent === text
}

function expectNoRebookWording(): void {
  expect(screen.queryByText(/reschedule|book again/i)).toBeNull()
}

afterEach(() => {
  vi.unstubAllGlobals()
})

it('shows the invalid-link message when the fragment is missing', async () => {
  const fetchMock = stubApi({ status: 200, body: CAN_CANCEL })
  renderPage('')
  expect(await screen.findByText(sentence(INVALID))).toBeInTheDocument()
  expect(fetchMock).not.toHaveBeenCalled()
  expect(screen.queryByText('MOT test')).toBeNull()
})

it('shows the invalid-link message on 404', async () => {
  stubApi({ status: 404, body: { detail: "This link isn't valid" } })
  renderPage()
  expect(await screen.findByText(sentence(INVALID))).toBeInTheDocument()
  expect(screen.queryByText('MOT test')).toBeNull()
})

it('posts the token from the fragment, not the URL', async () => {
  const fetchMock = stubApi({ status: 200, body: CAN_CANCEL })
  renderPage('#t=secret-token')
  await screen.findByText('MOT test')
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
  expect(url).toBe('/api/bookings/ABCD-EFGH/view')
  expect(init.method).toBe('POST')
  expect(JSON.parse(init.body as string)).toEqual({ token: 'secret-token' })
})

it('shows the booking with a cancel button when can_cancel', async () => {
  stubApi({ status: 200, body: CAN_CANCEL })
  renderPage()
  expect(await screen.findByText('MOT test')).toBeInTheDocument()
  expect(screen.getByText('ABCD-EFGH')).toBeInTheDocument()
  expect(screen.getByText('Friday 20 November, 09:00 – 10:00')).toBeInTheDocument()
  expect(screen.getByText('AB12CDE · Ford Focus')).toBeInTheDocument()
  expect(screen.getByText('Deposit: £20 paid')).toBeInTheDocument()
  expect(screen.getByText(sentence(CALL_LINE))).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '01632 960123' })).toHaveAttribute('href', 'tel:01632960123')
  expect(screen.getByRole('button', { name: 'Cancel booking' })).toBeInTheDocument()
  expectNoRebookWording()
})

it('shows only the call line inside the window', async () => {
  stubApi({ status: 200, body: INSIDE_WINDOW })
  renderPage()
  expect(await screen.findByText(sentence('To change or cancel, please call us on 01632 960123.'))).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Cancel booking' })).toBeNull()
  expect(screen.queryByText(sentence(CALL_LINE))).toBeNull()
  expectNoRebookWording()
})

it('cancel asks first, then shows the refund on its way', async () => {
  const user = userEvent.setup()
  const fetchMock = stubApi({ status: 200, body: CAN_CANCEL })
  renderPage()
  await user.click(await screen.findByRole('button', { name: 'Cancel booking' }))

  const dialog = screen.getByRole('alertdialog', { name: 'Cancel your booking on Friday 20 November at 09:00?' })
  expect(dialog).toHaveTextContent("You'll get your £20 deposit back.")
  expect(dialog).toHaveTextContent(
    'If you just need a different time, please call us on 01632 960123 instead and we can move it for you.',
  )
  expect(dialog).toContainElement(document.activeElement as HTMLElement)
  expect(cancelCalls(fetchMock)).toBe(0)
  expectNoRebookWording()

  await user.click(screen.getByRole('button', { name: 'Yes, cancel it' }))
  expect(await screen.findByText('This booking is cancelled')).toBeInTheDocument()
  expect(screen.getByText('Your deposit refund is on its way')).toBeInTheDocument()
  expect(screen.queryByRole('alertdialog')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Cancel booking' })).toBeNull()
  expect(screen.getByRole('link', { name: '01632 960123' })).toBeInTheDocument()
  expect(cancelCalls(fetchMock)).toBe(1)
  expectNoRebookWording()
})

it('leaves out the deposit line in the dialog when no refund is due', async () => {
  const user = userEvent.setup()
  stubApi({ status: 200, body: { ...CAN_CANCEL, deposit_status: 'waived', refund_if_cancelled: false } })
  renderPage()
  await user.click(await screen.findByRole('button', { name: 'Cancel booking' }))
  expect(screen.getByRole('alertdialog')).not.toHaveTextContent(/deposit back/)
})

it('keep my booking closes the dialog without a request', async () => {
  const user = userEvent.setup()
  const fetchMock = stubApi({ status: 200, body: CAN_CANCEL })
  renderPage()
  await user.click(await screen.findByRole('button', { name: 'Cancel booking' }))
  await user.click(screen.getByRole('button', { name: 'Keep my booking' }))
  expect(screen.queryByRole('alertdialog')).toBeNull()
  expect(screen.getByRole('button', { name: 'Cancel booking' })).toHaveFocus()
  expect(cancelCalls(fetchMock)).toBe(0)
})

it('shows the try-again message on 503 and keeps the booking', async () => {
  const user = userEvent.setup()
  stubApi({ status: 200, body: CAN_CANCEL }, { status: 503, body: { detail: "We couldn't cancel just now" } })
  renderPage()
  await user.click(await screen.findByRole('button', { name: 'Cancel booking' }))
  await user.click(screen.getByRole('button', { name: 'Yes, cancel it' }))
  expect(
    await screen.findByText(sentence("We couldn't cancel just now. Please try again, or call us on 01632 960123.")),
  ).toBeInTheDocument()
  expect(screen.queryByText('This booking is cancelled')).toBeNull()
  expect(screen.getByText('MOT test')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Cancel booking' })).toBeInTheDocument()
})

it('a 409 too_late shows the call line', async () => {
  const user = userEvent.setup()
  stubApi({ status: 200, body: CAN_CANCEL }, { status: 409, body: { detail: 'too_late' } })
  renderPage()
  await user.click(await screen.findByRole('button', { name: 'Cancel booking' }))
  await user.click(screen.getByRole('button', { name: 'Yes, cancel it' }))
  expect(await screen.findByText(sentence('To change or cancel, please call us on 01632 960123.'))).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Cancel booking' })).toBeNull()
  expect(screen.getByText('MOT test')).toBeInTheDocument()
})

it.each([
  ['refund_pending', 'Your deposit refund is on its way'],
  ['refunded', 'Your deposit has been refunded'],
  ['refund_failed', "We'll be in touch about your refund"],
  ['paid', 'Your deposit was kept'],
])('a cancelled booking with deposit %s says "%s"', async (deposit_status, text) => {
  stubApi({ status: 200, body: { ...CANCELLED, deposit_status } })
  renderPage()
  expect(await screen.findByText('This booking is cancelled')).toBeInTheDocument()
  expect(screen.getByText(text)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Cancel booking' })).toBeNull()
  expectNoRebookWording()
})

it('no reschedule or book-again wording appears', async () => {
  for (const body of [CAN_CANCEL, INSIDE_WINDOW, CANCELLED]) {
    stubApi({ status: 200, body })
    renderPage()
    await screen.findByText('MOT test')
    expectNoRebookWording()
    cleanup()
  }
  stubApi({ status: 404, body: {} })
  renderPage()
  await screen.findByText(sentence(INVALID))
  expectNoRebookWording()
})

it('shows no deposit line for a phone booking', async () => {
  const phone: MyBooking = {
    ...CAN_CANCEL,
    summary: { ...SUMMARY, deposit_paid_pence: 0 },
    deposit_status: 'not_required',
    refund_if_cancelled: false,
  }
  stubApi({ status: 200, body: phone }, { status: 200, body: { ...phone, summary: { ...phone.summary, status: 'cancelled' } } })
  renderPage()
  await screen.findByText('MOT test')
  expect(screen.queryByText(/deposit/i)).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel booking' }))
  expect(screen.queryByText(/deposit/i)).toBeNull()
})

it('a 429 when cancelling shows the server message and keeps the booking', async () => {
  const user = userEvent.setup()
  stubApi({ status: 200, body: CAN_CANCEL }, { status: 429, body: { detail: 'Too many attempts. Please wait a few minutes and try again.' } })
  renderPage()
  await user.click(await screen.findByRole('button', { name: 'Cancel booking' }))
  await user.click(screen.getByRole('button', { name: 'Yes, cancel it' }))
  expect(await screen.findByText('Too many attempts. Please wait a few minutes and try again.')).toBeInTheDocument()
  expect(screen.queryByText('This booking is cancelled')).toBeNull()
  expect(screen.getByRole('button', { name: 'Cancel booking' })).toBeInTheDocument()
})
