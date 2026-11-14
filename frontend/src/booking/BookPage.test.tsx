import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { JSX } from 'react'
import { MemoryRouter, useNavigate } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { App } from '../App.tsx'
import type { OpeningDay } from '../catalogue/types.ts'
import { GARAGE, HOURS, SERVICES } from '../testing/fixtures.ts'
import type { Availability, Hold } from './types.ts'

// Sunday 15 November, 10:00 in London. The garage is closed on Sundays here.
const NOW = (): Date => new Date('2026-11-15T10:00:00Z')
const SUNDAY_CLOSED: OpeningDay[] = HOURS.map((day) =>
  day.weekday === 6 ? { weekday: 6, open: null, close: null, breaks: [] } : day,
)

const MONDAY = '2026-11-16'
const SLOTS = [
  { start: `${MONDAY}T08:00:00+00:00`, end: `${MONDAY}T09:00:00+00:00` },
  { start: `${MONDAY}T13:00:00+00:00`, end: `${MONDAY}T14:00:00+00:00` },
]
const HOLD: Hold = {
  reference: 'ABCD-EFGH',
  hold_token: 'token',
  expires_at: '2026-11-15T10:10:00+00:00',
  expires_in_seconds: 600,
  start: SLOTS[0].start,
  end: SLOTS[0].end,
  services: [],
}

const POLICY = {
  booking_window_days: 60,
  slot_hold_minutes: 10,
  payment_hold_minutes: 10,
  deposit_amount_pence: 2000,
  payment: { provider: 'demo' },
}
const CHECKOUT = { client_secret: null, demo_session: 'demo_abc', expires_in_seconds: 600, amount_pence: 2000 }

/** checkoutStatus 0 means checkout never answers. */
type Stub = { availability?: Partial<Availability>; holdStatus?: number; checkoutStatus?: number }

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

/** A fake backend. Returns the fetch mock so tests can count calls. */
function stubApi({ availability = {}, holdStatus = 201, checkoutStatus = 200 }: Stub = {}): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((url: string) => {
    if (url === '/api/services') return Promise.resolve(json(SERVICES))
    if (url === '/api/opening-hours') return Promise.resolve(json(SUNDAY_CLOSED))
    if (url === '/api/garage') return Promise.resolve(json(GARAGE))
    if (url === '/api/booking-policy') {
      return Promise.resolve(json(POLICY))
    }
    if (url.startsWith('/api/availability')) {
      const date = new URLSearchParams(url.split('?')[1]).get('date') ?? ''
      return Promise.resolve(
        json({
          date,
          timezone: 'Europe/London',
          duration_minutes: 60,
          unavailable_reason: null,
          slots: date === MONDAY ? SLOTS : [],
          ...availability,
        }),
      )
    }
    if (url === '/api/holds') {
      return Promise.resolve(
        holdStatus === 201 ? json(HOLD, 201) : json({ detail: 'That time has just been taken' }, 409),
      )
    }
    if (url === '/api/holds/ABCD-EFGH') return Promise.resolve(new Response(null, { status: 204 }))
    if (url === '/api/holds/ABCD-EFGH/checkout') {
      if (checkoutStatus === 0) return new Promise<Response>(() => {}) // never answers
      return Promise.resolve(
        checkoutStatus === 200 ? json(CHECKOUT) : json({ detail: 'Your hold has expired' }, checkoutStatus),
      )
    }
    return Promise.resolve(json({}, 404))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderAt(entry: string): void {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <App now={NOW} />
    </MemoryRouter>,
  )
}

/** Stands in for the browser's Back button. */
function BackButton(): JSX.Element {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => void navigate(-1)}>
      Browser back
    </button>
  )
}

/** The booking page, arrived at from the services page, so there is somewhere to go back to. */
function renderWithHistory(): void {
  render(
    <MemoryRouter initialEntries={['/', '/book?services=mot-test']} initialIndex={1}>
      <BackButton />
      <App now={NOW} />
    </MemoryRouter>,
  )
}

function availabilityCalls(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map(([url]) => String(url)).filter((url) => url.startsWith('/api/availability'))
}

afterEach(() => vi.unstubAllGlobals())

it('starts on the first open day and lists its times in garage time', async () => {
  const fetchMock = stubApi()
  renderAt('/book?services=mot-test')
  const morning = await screen.findByRole('region', { name: 'Morning' })
  expect(within(morning).getByRole('button', { name: '08:00 – 09:00' })).toBeInTheDocument()
  const afternoon = screen.getByRole('region', { name: 'Afternoon' })
  expect(within(afternoon).getByRole('button', { name: '13:00 – 14:00' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Mon 16 Nov' })).toHaveAttribute('aria-pressed', 'true')
  expect(availabilityCalls(fetchMock)).toEqual([
    `/api/availability?services=mot-test&date=${MONDAY}`,
  ])
})

it('disables closed days', async () => {
  stubApi()
  renderAt('/book?services=mot-test')
  await screen.findByRole('region', { name: 'Morning' })
  expect(screen.getByRole('button', { name: 'Sun 15 Nov' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Sun 22 Nov' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Tue 17 Nov' })).toBeEnabled()
})

it('loads another day when it is picked', async () => {
  stubApi()
  renderAt('/book?services=mot-test')
  await screen.findByRole('region', { name: 'Morning' })
  await userEvent.setup().click(screen.getByRole('button', { name: 'Tue 17 Nov' }))
  expect(await screen.findByText('No times left on this day')).toBeInTheDocument()
})

it('tells the customer to book mixed bay types separately', async () => {
  stubApi({ availability: { unavailable_reason: 'mixed_bay_types', slots: [] } })
  renderAt('/book?services=mot-test&services=full-service')
  expect(
    await screen.findByText("These services can't be booked together — please book them separately"),
  ).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Change services' })).toHaveAttribute(
    'href',
    '/?services=mot-test&services=full-service',
  )
})

it('shows "just taken" and reloads after a 409', async () => {
  const fetchMock = stubApi({ holdStatus: 409 })
  renderAt('/book?services=mot-test')
  await userEvent.setup().click(await screen.findByRole('button', { name: '08:00 – 09:00' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Sorry, someone just took that time.')
  expect(availabilityCalls(fetchMock)).toHaveLength(2)
})

it('moves to the details step after a successful hold', async () => {
  const fetchMock = stubApi()
  renderAt('/book?services=mot-test')
  await userEvent.setup().click(await screen.findByRole('button', { name: '08:00 – 09:00' }))
  expect(await screen.findByRole('heading', { name: 'Your details' })).toBeInTheDocument()
  const holdCall = fetchMock.mock.calls.find(([url]) => url === '/api/holds')
  expect(JSON.parse(String((holdCall?.[1] as RequestInit).body))).toEqual({
    services: ['mot-test'],
    start: SLOTS[0].start,
  })
})

it('redirects to the services page with no services', async () => {
  stubApi()
  renderAt('/book')
  expect(await screen.findByRole('heading', { level: 1, name: 'Hillside Motors' })).toBeInTheDocument()
})

it('redirects to the services page when only needs-approval services are chosen', async () => {
  stubApi()
  renderAt('/book?services=clutch-replacement')
  expect(await screen.findByRole('heading', { level: 1, name: 'Hillside Motors' })).toBeInTheDocument()
})

async function fillDetails(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.type(screen.getByLabelText('Name'), 'Sam Driver')
  await user.type(screen.getByLabelText('Phone'), '07700 900123')
  await user.type(screen.getByLabelText('Email'), 'sam@example.com')
  await user.type(screen.getByLabelText('Registration'), 'AB12CDE')
  await user.type(screen.getByLabelText('Make'), 'Ford')
  await user.type(screen.getByLabelText('Model'), 'Focus')
}

it('goes back to the times after the hold runs out, keeping what was typed', async () => {
  stubApi({ checkoutStatus: 410 })
  renderAt('/book?services=mot-test')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '08:00 – 09:00' }))
  await screen.findByRole('heading', { name: 'Your details' })
  await fillDetails(user)
  await user.click(screen.getByRole('button', { name: 'Continue to payment' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Your hold ran out, so we released that time.')
  expect(screen.getByRole('heading', { name: 'Choose a time' })).toBeInTheDocument()
  await user.click(await screen.findByRole('button', { name: '08:00 – 09:00' }))
  expect(await screen.findByLabelText('Name')).toHaveValue('Sam Driver')
  expect(screen.getByLabelText('Model')).toHaveValue('Focus')
})

// Task 9 rewrites this for the payment step.
it.skip('shows the booked page after confirming', async () => {
  stubApi()
  renderAt('/book?services=mot-test')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '08:00 – 09:00' }))
  await screen.findByRole('heading', { name: 'Your details' })
  await fillDetails(user)
  await user.click(screen.getByRole('button', { name: 'Continue to payment' }))
  expect(await screen.findByRole('heading', { level: 1, name: "You're booked" })).toBeInTheDocument()
  expect(screen.getByText('ABCD-EFGH')).toBeInTheDocument()
})

function released(fetchMock: ReturnType<typeof vi.fn>): RequestInit | undefined {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => url === '/api/holds/ABCD-EFGH' && (init as RequestInit | undefined)?.method === 'DELETE',
  )
  return call?.[1] as RequestInit | undefined
}

it('change time releases the hold and keeps what was typed', async () => {
  const fetchMock = stubApi()
  renderAt('/book?services=mot-test')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '08:00 – 09:00' }))
  await screen.findByRole('heading', { name: 'Your details' })
  await fillDetails(user)
  await user.click(screen.getByRole('button', { name: 'Change time' }))

  expect(await screen.findByRole('heading', { name: 'Choose a time' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Change time' })).not.toBeInTheDocument()
  expect(JSON.parse(String(released(fetchMock)?.body))).toEqual({ hold_token: 'token' })

  await user.click(await screen.findByRole('button', { name: '08:00 – 09:00' }))
  expect(await screen.findByLabelText('Name')).toHaveValue('Sam Driver')
  expect(screen.getByLabelText('Model')).toHaveValue('Focus')
})

it('change time sits next to change services and is off while starting payment', async () => {
  stubApi({ checkoutStatus: 0 })
  renderAt('/book?services=mot-test')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '08:00 – 09:00' }))
  const nav = await screen.findByRole('navigation', { name: 'Booking steps' })
  expect(within(nav).getByRole('link', { name: '← Change services' })).toBeInTheDocument()
  expect(within(nav).getByRole('button', { name: 'Change time' })).toBeEnabled()
  await fillDetails(user)
  await user.click(screen.getByRole('button', { name: 'Continue to payment' }))
  expect(within(nav).getByRole('button', { name: 'Change time' })).toBeDisabled()
})

it('change services releases the hold and drops what was typed', async () => {
  const fetchMock = stubApi()
  renderAt('/book?services=mot-test')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '08:00 – 09:00' }))
  await screen.findByRole('heading', { name: 'Your details' })
  await fillDetails(user)
  await user.click(screen.getByRole('link', { name: '← Change services' }))

  expect(await screen.findByRole('checkbox', { name: 'MOT test' })).toBeChecked()
  expect(released(fetchMock)).toBeDefined()

  await user.click(screen.getByRole('link', { name: /Choose a time/ }))
  await user.click(await screen.findByRole('button', { name: '08:00 – 09:00' }))
  expect(await screen.findByLabelText('Name')).toHaveValue('')
})

it('change services does nothing while starting payment', async () => {
  const fetchMock = stubApi({ checkoutStatus: 0 })
  renderAt('/book?services=mot-test')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '08:00 – 09:00' }))
  await screen.findByRole('heading', { name: 'Your details' })
  await fillDetails(user)
  await user.click(screen.getByRole('button', { name: 'Continue to payment' }))

  const changeServices = screen.getByRole('link', { name: '← Change services' })
  expect(changeServices).toHaveAttribute('aria-disabled', 'true')
  await user.click(changeServices)
  expect(screen.getByRole('heading', { name: 'Your details' })).toBeInTheDocument()
  expect(released(fetchMock)).toBeUndefined()
})

// --- leaving without a button ------------------------------------------------------

async function holdFirstTime(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(await screen.findByRole('button', { name: '08:00 – 09:00' }))
  await screen.findByRole('heading', { name: 'Your details' })
}

it('the browser back button releases the hold', async () => {
  const fetchMock = stubApi()
  renderWithHistory()
  const user = userEvent.setup()
  await holdFirstTime(user)
  await user.click(screen.getByRole('button', { name: 'Browser back' }))
  expect(await screen.findByRole('checkbox', { name: 'MOT test' })).toBeInTheDocument()
  expect(JSON.parse(String(released(fetchMock)?.body))).toEqual({ hold_token: 'token' })
})

it('a refresh or closing the tab releases the hold in a way that outlives the page', async () => {
  const fetchMock = stubApi()
  renderAt('/book?services=mot-test')
  await holdFirstTime(userEvent.setup())
  window.dispatchEvent(new Event('pagehide'))
  expect(released(fetchMock)?.keepalive).toBe(true)
})

it('leaving before holding a time releases nothing', async () => {
  const fetchMock = stubApi()
  renderWithHistory()
  const user = userEvent.setup()
  await screen.findByRole('button', { name: '08:00 – 09:00' })
  window.dispatchEvent(new Event('pagehide'))
  await user.click(screen.getByRole('button', { name: 'Browser back' }))
  await screen.findByRole('checkbox', { name: 'MOT test' })
  expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === 'DELETE')).toBe(false)
})

// Task 9 rewrites this for the payment step.
it.skip('a confirmed booking is never released', async () => {
  const fetchMock = stubApi()
  renderWithHistory()
  const user = userEvent.setup()
  await holdFirstTime(user)
  await fillDetails(user)
  await user.click(screen.getByRole('button', { name: 'Continue to payment' }))
  await screen.findByRole('heading', { level: 1, name: "You're booked" })
  window.dispatchEvent(new Event('pagehide'))
  expect(released(fetchMock)).toBeUndefined()
})
