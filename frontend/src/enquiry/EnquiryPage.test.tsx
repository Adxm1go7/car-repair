import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { UserEvent } from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { App } from '../App.tsx'
import { GARAGE, SERVICES, TIMETABLES } from '../testing/fixtures.ts'

const CATALOGUE: Record<string, unknown> = {
  '/api/services': SERVICES,
  '/api/opening-hours': { timetables: TIMETABLES },
  '/api/garage': GARAGE,
}

type Reply = { status: number; body: unknown } | 'network' | 'pending'

/** The catalogue as usual; `POST /api/enquiries` answers with `reply`. */
function stub(reply: Reply = { status: 201, body: { email: 'sam@example.com' } }): Mock {
  const mock = vi.fn((url: string) => {
    if (url === '/api/enquiries') {
      if (reply === 'network') return Promise.reject(new TypeError('offline'))
      if (reply === 'pending') return new Promise<Response>(() => {})
      return Promise.resolve(new Response(JSON.stringify(reply.body), { status: reply.status }))
    }
    return Promise.resolve(new Response(JSON.stringify(CATALOGUE[url]), { status: 200 }))
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

function renderAt(entry: string): void {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <App now={() => new Date('2026-11-10T10:00:00Z')} />
    </MemoryRouter>,
  )
}

function enquiryCalls(mock: Mock): unknown[][] {
  return mock.mock.calls.filter(([url]) => url === '/api/enquiries')
}

async function fillIn(user: UserEvent): Promise<void> {
  await user.type(await screen.findByLabelText('Name'), ' Sam Driver ')
  await user.type(screen.getByLabelText('Phone'), '07700 900123')
  await user.type(screen.getByLabelText('Email'), 'sam@example.com')
  await user.type(screen.getByLabelText('Registration'), 'AB12 CDE')
  await user.type(screen.getByLabelText('Make'), 'Ford')
  await user.type(screen.getByLabelText('Model'), 'Focus')
  await user.type(screen.getByLabelText('Describe the problem'), 'Rattle from the front left when braking  ')
}

afterEach(() => vi.unstubAllGlobals())

it('the services page links to the enquiry form', async () => {
  stub()
  renderAt('/')
  const link = await screen.findByRole('link', { name: 'Describe the problem' })
  expect(link).toHaveAttribute('href', '/enquiry')
  expect(screen.getByText(/Not sure what's wrong\?/)).toBeInTheDocument()
})

it('sends the enquiry and shows it was sent', async () => {
  const mock = stub()
  renderAt('/enquiry')
  expect(await screen.findByRole('heading', { level: 1, name: 'Ask about a problem' })).toBeInTheDocument()
  const user = userEvent.setup()
  await fillIn(user)
  await user.click(screen.getByRole('button', { name: 'Send enquiry' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Enquiry sent' })).toBeInTheDocument()
  expect(screen.getByText(/sam@example\.com/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '01632 960123' })).toHaveAttribute('href', 'tel:01632960123')
  const [call] = enquiryCalls(mock)
  const init = call[1] as RequestInit
  expect(init.method).toBe('POST')
  expect(JSON.parse(init.body as string)).toEqual({
    name: 'Sam Driver',
    phone: '07700 900123',
    email: 'sam@example.com',
    registration: 'AB12 CDE',
    make: 'Ford',
    model: 'Focus',
    description: 'Rattle from the front left when braking',
    website: '',
  })
})

it("shows each field's problem and sends nothing", async () => {
  const mock = stub()
  renderAt('/enquiry')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Send enquiry' }))
  expect(screen.getByText('Please describe the problem')).toBeInTheDocument()
  expect(screen.getByText('Please enter your name')).toBeInTheDocument()
  expect(screen.getByText('Please enter a valid email address')).toBeInTheDocument()
  expect(screen.getByLabelText('Name')).toHaveFocus()
  await user.type(screen.getByLabelText('Describe the problem'), 'noise')
  await user.click(screen.getByRole('button', { name: 'Send enquiry' }))
  expect(screen.getByText('Please describe the problem in at least 10 characters')).toBeInTheDocument()
  expect(enquiryCalls(mock)).toHaveLength(0)
})

it('the send button is disabled while sending', async () => {
  const mock = stub('pending')
  renderAt('/enquiry')
  const user = userEvent.setup()
  await fillIn(user)
  const button = screen.getByRole('button', { name: 'Send enquiry' })
  await user.click(button)
  expect(button).toBeDisabled()
  expect(button).toHaveTextContent('Sending…')
  await user.click(button)
  expect(enquiryCalls(mock)).toHaveLength(1)
})

it("a server error is shown against its field", async () => {
  stub({ status: 422, body: { detail: 'email: Please enter a valid email address' } })
  renderAt('/enquiry')
  const user = userEvent.setup()
  await fillIn(user)
  await user.click(screen.getByRole('button', { name: 'Send enquiry' }))
  expect(await screen.findByText('Please enter a valid email address')).toBeInTheDocument()
  expect(screen.queryByText(/email: /)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Send enquiry' })).toBeEnabled()
})

it('a failure to send says to try again or call', async () => {
  stub('network')
  renderAt('/enquiry')
  const user = userEvent.setup()
  await fillIn(user)
  await user.click(screen.getByRole('button', { name: 'Send enquiry' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    "Sorry, we couldn't send your enquiry. Please try again, or call us on 01632 960123.",
  )
})

it('a 429 shows the server message', async () => {
  stub({ status: 429, body: { detail: 'Too many attempts. Please wait a few minutes and try again.' } })
  renderAt('/enquiry')
  const user = userEvent.setup()
  await fillIn(user)
  await user.click(screen.getByRole('button', { name: 'Send enquiry' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts. Please wait a few minutes and try again.')
})

it('the enquiry honeypot is hidden and sent', async () => {
  const mock = stub()
  renderAt('/enquiry')
  const user = userEvent.setup()
  await fillIn(user)
  const trap = document.querySelector('input[name="website"]') as HTMLInputElement
  expect(trap).toHaveAttribute('tabindex', '-1')
  expect(trap.closest('[aria-hidden="true"]')).not.toBeNull()
  fireEvent.change(trap, { target: { value: 'spam' } })
  await user.click(screen.getByRole('button', { name: 'Send enquiry' }))
  await screen.findByRole('heading', { level: 1, name: 'Enquiry sent' })
  const [call] = enquiryCalls(mock)
  expect(JSON.parse((call[1] as RequestInit).body as string).website).toBe('spam')
})

it('links to the privacy note in a new tab, so the typed enquiry is kept', async () => {
  stub()
  renderAt('/enquiry')
  const link = await screen.findByRole('link', { name: /How we use your details/ })
  expect(link).toHaveAttribute('href', '/privacy')
  expect(link).toHaveAttribute('target', '_blank')
})
