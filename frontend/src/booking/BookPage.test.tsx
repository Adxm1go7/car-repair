import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
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

type Stub = { availability?: Partial<Availability>; holdStatus?: number }

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

/** A fake backend. Returns the fetch mock so tests can count calls. */
function stubApi({ availability = {}, holdStatus = 201 }: Stub = {}): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((url: string) => {
    if (url === '/api/services') return Promise.resolve(json(SERVICES))
    if (url === '/api/opening-hours') return Promise.resolve(json(SUNDAY_CLOSED))
    if (url === '/api/garage') return Promise.resolve(json(GARAGE))
    if (url === '/api/booking-policy') {
      return Promise.resolve(json({ booking_window_days: 60, slot_hold_minutes: 10 }))
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
