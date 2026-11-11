import { render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { App } from './App.tsx'
import type { Garage, OpeningDay, Service } from './catalogue/types.ts'

const SERVICES: Service[] = [
  {
    slug: 'mot-test',
    name: 'MOT test',
    category: 'MOT',
    description: 'The annual roadworthiness test.',
    duration_minutes: 60,
    price_from_pence: 5485,
    price_to_pence: null,
    approval_mode: 'instant',
  },
  {
    slug: 'full-service',
    name: 'Full service',
    category: 'Servicing',
    description: 'Oil, filters, fluids and a 50-point check.',
    duration_minutes: 180,
    price_from_pence: 21900,
    price_to_pence: null,
    approval_mode: 'instant',
  },
  {
    slug: 'clutch-replacement',
    name: 'Clutch replacement',
    category: 'Repairs',
    description: 'Supply and fit a new clutch kit.',
    duration_minutes: 360,
    price_from_pence: 45000,
    price_to_pence: 75000,
    approval_mode: 'needs_approval',
  },
]

const LUNCH = [{ start: '12:30', end: '13:00' }]
const HOURS: OpeningDay[] = [
  ...[0, 1, 2, 3, 4].map((weekday) => ({ weekday, open: '08:00', close: '17:30', breaks: LUNCH })),
  { weekday: 5, open: '09:00', close: '14:00', breaks: [] },
  { weekday: 6, open: '10:00', close: '13:00', breaks: [] },
]

const GARAGE: Garage = {
  name: 'Hillside Motors',
  address: '12 Station Road, Anytown, AT1 2CD',
  phone: '01632 960123',
  email: 'bookings@example.com',
  timezone: 'Europe/London',
}

const RESPONSES: Record<string, unknown> = {
  '/api/services': SERVICES,
  '/api/opening-hours': HOURS,
  '/api/garage': GARAGE,
}

/** Answers each API URL with its fixture, or a 500 for the URLs listed in `failing`. */
function stubApi(failing: string[] = []): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      Promise.resolve(
        failing.includes(url)
          ? new Response('{}', { status: 500 })
          : new Response(JSON.stringify(RESPONSES[url]), { status: 200 }),
      ),
    ),
  )
}

// Tuesday 10:00 in the UK.
const NOW = (): Date => new Date('2026-11-10T10:00:00Z')

function cardFor(serviceName: string): HTMLElement {
  const card = screen.getByRole('heading', { level: 3, name: serviceName }).closest('li')
  if (!card) throw new Error(`no card for ${serviceName}`)
  return card
}

afterEach(() => vi.unstubAllGlobals())

it('shows a loading message first', () => {
  stubApi()
  render(<App now={NOW} />)
  expect(screen.getByText('Loading…')).toBeInTheDocument()
})

it('shows the garage name, open-today strip and services grouped by category', async () => {
  stubApi()
  render(<App now={NOW} />)
  expect(await screen.findByRole('heading', { level: 1, name: 'Hillside Motors' })).toBeInTheDocument()
  expect(screen.getByText('Open today 08:00–17:30')).toBeInTheDocument()
  expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
    'MOT',
    'Servicing',
    'Repairs',
    'Opening hours',
    'Contact',
  ])
  const fullService = within(cardFor('Full service'))
  expect(fullService.getByText('3h')).toBeInTheDocument()
  expect(fullService.getByText('£219')).toBeInTheDocument()
  expect(within(cardFor('Clutch replacement')).getByText('£450–£750')).toBeInTheDocument()
})

it('badges only needs-approval services', async () => {
  stubApi()
  render(<App now={NOW} />)
  await screen.findByRole('heading', { level: 1 })
  expect(within(cardFor('Clutch replacement')).getByText('Needs approval')).toBeInTheDocument()
  expect(within(cardFor('Full service')).queryByText('Needs approval')).not.toBeInTheDocument()
})

it('lists weekly hours with breaks and links the contact details', async () => {
  stubApi()
  render(<App now={NOW} />)
  await screen.findByRole('heading', { level: 1 })
  expect(screen.getAllByText('Closed 12:30–13:00')).toHaveLength(5)
  expect(screen.getByRole('link', { name: '01632 960123' })).toHaveAttribute('href', 'tel:01632960123')
  expect(screen.getByRole('link', { name: 'bookings@example.com' })).toHaveAttribute(
    'href',
    'mailto:bookings@example.com',
  )
})

it('shows an error with the phone number when services fail but garage loads', async () => {
  stubApi(['/api/services'])
  render(<App now={NOW} />)
  expect(await screen.findByRole('alert')).toHaveTextContent("couldn't load")
  expect(screen.getByRole('link', { name: '01632 960123' })).toHaveAttribute('href', 'tel:01632960123')
})

it('shows an error without a phone number when every request fails', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
  render(<App now={NOW} />)
  expect(await screen.findByRole('alert')).toHaveTextContent("couldn't load")
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})
