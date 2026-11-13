import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { App } from './App.tsx'
import { GARAGE, HOURS, SERVICES } from './testing/fixtures.ts'

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

function renderApp(entry = '/'): void {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <App now={NOW} />
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

it('shows a loading message first', () => {
  stubApi()
  renderApp()
  expect(screen.getByText('Loading…')).toBeInTheDocument()
})

it('shows the garage name, open-today strip and services grouped by category', async () => {
  stubApi()
  renderApp()
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
  renderApp()
  await screen.findByRole('heading', { level: 1 })
  expect(within(cardFor('Clutch replacement')).getByText('Needs approval')).toBeInTheDocument()
  expect(within(cardFor('Full service')).queryByText('Needs approval')).not.toBeInTheDocument()
})

it('lists weekly hours with breaks and links the contact details', async () => {
  stubApi()
  renderApp()
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
  renderApp()
  expect(await screen.findByRole('alert')).toHaveTextContent("couldn't load")
  expect(screen.getByRole('link', { name: '01632 960123' })).toHaveAttribute('href', 'tel:01632960123')
})

it('shows an error without a phone number when every request fails', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
  renderApp()
  expect(await screen.findByRole('alert')).toHaveTextContent("couldn't load")
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})

// --- choosing services -------------------------------------------------------------

it('ticking services shows the bar with count and total time', async () => {
  stubApi()
  renderApp()
  await screen.findByRole('heading', { level: 1 })
  expect(screen.queryByRole('link', { name: /Choose a time/ })).not.toBeInTheDocument()

  const user = userEvent.setup()
  await user.click(screen.getByRole('checkbox', { name: 'MOT test' }))
  expect(screen.getByRole('link', { name: 'Choose a time · 1 service · 1h' })).toBeInTheDocument()

  await user.click(screen.getByRole('checkbox', { name: 'Full service' }))
  const bar = screen.getByRole('link', { name: 'Choose a time · 2 services · 4h' })
  expect(bar).toHaveAttribute('href', '/book?services=mot-test&services=full-service')

  await user.click(screen.getByRole('checkbox', { name: 'MOT test' }))
  await user.click(screen.getByRole('checkbox', { name: 'Full service' }))
  expect(screen.queryByRole('link', { name: /Choose a time/ })).not.toBeInTheDocument()
})

it('needs-approval services have no tick box', async () => {
  stubApi()
  renderApp()
  await screen.findByRole('heading', { level: 1 })
  const clutch = within(cardFor('Clutch replacement'))
  expect(clutch.queryByRole('checkbox')).not.toBeInTheDocument()
  expect(clutch.getByText('Needs approval — call us')).toBeInTheDocument()
})

it('pre-ticks services from the URL', async () => {
  stubApi()
  renderApp('/?services=mot-test')
  expect(await screen.findByRole('checkbox', { name: 'MOT test' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Full service' })).not.toBeChecked()
  expect(screen.getByRole('link', { name: 'Choose a time · 1 service · 1h' })).toBeInTheDocument()
})
