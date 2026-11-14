import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import type { JSX } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { DetailsForm } from './DetailsForm.tsx'
import type { Checkout, CustomerDetails, Hold } from './types.ts'

const HOLD: Hold = {
  reference: 'ABCD-EFGH',
  hold_token: 'token',
  expires_at: '2026-11-15T10:10:00+00:00',
  expires_in_seconds: 600,
  start: '2026-11-16T08:00:00+00:00',
  end: '2026-11-16T09:00:00+00:00',
  services: [],
}

const DETAILS: CustomerDetails = {
  name: 'Sam Driver',
  phone: '07700 900123',
  email: 'sam@example.com',
  registration: 'AB12CDE',
  make: 'Ford',
  model: 'Focus',
  notes: '',
}

const CHECKOUT: Checkout = {
  client_secret: 'cs_1_secret',
  demo_session: null,
  expires_in_seconds: 600,
  amount_pence: 2000,
}

const EMPTY: CustomerDetails = {
  name: '',
  phone: '',
  email: '',
  registration: '',
  make: '',
  model: '',
  notes: '',
}

type Handlers = {
  onExpired: Mock<() => void>
  onCheckout: Mock<(checkout: Checkout) => void>
  onAlreadyPaid: Mock<() => void>
  onSubmittingChange: Mock<(submitting: boolean) => void>
}

/** Holds the typed values the way BookPage does. */
function Harness({ initial, handlers }: { initial: CustomerDetails; handlers: Handlers }): JSX.Element {
  const [values, setValues] = useState(initial)
  return <DetailsForm hold={HOLD} zone="Europe/London" values={values} onValuesChange={setValues} {...handlers} />
}

function renderForm(initial: CustomerDetails = EMPTY): Handlers {
  const handlers: Handlers = {
    onExpired: vi.fn<() => void>(),
    onCheckout: vi.fn<(checkout: Checkout) => void>(),
    onAlreadyPaid: vi.fn<() => void>(),
    onSubmittingChange: vi.fn<(submitting: boolean) => void>(),
  }
  render(<Harness initial={initial} handlers={handlers} />)
  return handlers
}

function answer(status: number, body: unknown = {}): ReturnType<typeof vi.fn> {
  const response = status === 204 ? new Response(null, { status }) : new Response(JSON.stringify(body), { status })
  const fetchMock = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const confirmButton = (): HTMLElement => screen.getByRole('button', { name: /^(Continue to payment|Starting payment…)$/ })

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

// --- countdown ----------------------------------------------------------------------

it('counts down from expires_in_seconds even when the phone clock is wrong', () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'Date', 'performance'] })
  vi.setSystemTime(new Date('2030-01-01T00:00:00Z')) // years after expires_at
  renderForm()
  expect(screen.getByText(/We're holding Monday 16 November, 08:00 – 09:00 for/)).toBeInTheDocument()
  expect(screen.getByRole('timer')).toHaveTextContent('10:00')
  act(() => vi.advanceTimersByTime(61_000))
  expect(screen.getByRole('timer')).toHaveTextContent('8:59')
})

it('announces only at five minutes, one minute and expiry', () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'Date', 'performance'] })
  renderForm()
  const live = screen.getByTestId('countdown-announcer')
  expect(live).toHaveAttribute('aria-live', 'polite')
  expect(live).toBeEmptyDOMElement()
  act(() => vi.advanceTimersByTime(299_000)) // 5:01 left
  expect(live).toBeEmptyDOMElement()
  act(() => vi.advanceTimersByTime(1_000)) // 5:00
  expect(live).toHaveTextContent('5 minutes left to continue')
  act(() => vi.advanceTimersByTime(240_000)) // 1:00
  expect(live).toHaveTextContent('1 minute left to continue')
})

it('reports expiry once when the countdown reaches zero', () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'Date', 'performance'] })
  const { onExpired } = renderForm()
  act(() => vi.advanceTimersByTime(599_000))
  expect(onExpired).not.toHaveBeenCalled()
  act(() => vi.advanceTimersByTime(5_000))
  expect(onExpired).toHaveBeenCalledTimes(1)
})

/** A fetch whose single answer the test sends when it chooses. */
function answerLater(): (status: number, body?: unknown) => void {
  let send: (response: Response) => void = () => {}
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise<Response>((resolve) => (send = resolve))),
  )
  return (status, body = {}) => send(new Response(JSON.stringify(body), { status }))
}

it('a checkout that lands after the countdown ends still moves on to payment', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'Date', 'performance'] })
  const reply = answerLater()
  const { onCheckout, onExpired } = renderForm(DETAILS)
  act(() => vi.advanceTimersByTime(597_000)) // 0:03 left
  await act(async () => fireEvent.click(confirmButton()))
  act(() => vi.advanceTimersByTime(5_000)) // the countdown passes zero mid-request
  expect(onExpired).not.toHaveBeenCalled()

  await act(async () => {
    reply(200, CHECKOUT)
    await Promise.resolve()
  })
  expect(onCheckout).toHaveBeenCalledWith(CHECKOUT)
  expect(onExpired).not.toHaveBeenCalled()
})

it('a 410 that lands after the countdown ends reports expiry once', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'Date', 'performance'] })
  const reply = answerLater()
  const { onCheckout, onExpired } = renderForm(DETAILS)
  await act(async () => fireEvent.click(confirmButton()))
  act(() => vi.advanceTimersByTime(605_000))
  expect(onExpired).not.toHaveBeenCalled()

  await act(async () => {
    reply(410, { detail: 'Your hold has expired' })
    await Promise.resolve()
  })
  expect(onExpired).toHaveBeenCalledTimes(1)
  expect(onCheckout).not.toHaveBeenCalled()
})

// --- the form -----------------------------------------------------------------------

it('moves focus to the first field with a problem', async () => {
  answer(200, CHECKOUT)
  renderForm({ ...DETAILS, email: 'sam', registration: 'A' })
  await userEvent.setup().click(confirmButton())
  expect(screen.getByLabelText('Email')).toHaveFocus()
})

it('labels every field', () => {
  renderForm()
  for (const label of ['Name', 'Phone', 'Email', 'Registration', 'Make', 'Model', 'Notes (optional)']) {
    expect(screen.getByLabelText(label)).toBeInTheDocument()
  }
})

it('shows field errors and does not call the API when invalid', async () => {
  const fetchMock = answer(200, CHECKOUT)
  renderForm()
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Phone'), '123')
  await user.click(confirmButton())
  const phone = screen.getByLabelText('Phone')
  expect(phone).toHaveAttribute('aria-invalid', 'true')
  expect(phone).toHaveAccessibleDescription('Please enter a phone number we can call')
  expect(screen.getByLabelText('Name')).toHaveAccessibleDescription('Please enter your name')
  expect(fetchMock).not.toHaveBeenCalled()
})

it('starts checkout with the typed details and hands the checkout to the page', async () => {
  const fetchMock = answer(200, CHECKOUT)
  const { onCheckout } = renderForm(DETAILS)
  await userEvent.setup().click(confirmButton())
  await vi.waitFor(() => expect(onCheckout).toHaveBeenCalledWith(CHECKOUT))
  const [url, init] = fetchMock.mock.calls[0]
  expect(url).toBe('/api/holds/ABCD-EFGH/checkout')
  expect(JSON.parse(String((init as RequestInit).body))).toEqual({ hold_token: 'token', ...DETAILS })
})

it('shows Starting payment… and aria-busy while waiting', async () => {
  vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {}))) // never answers
  const { onSubmittingChange } = renderForm(DETAILS)
  expect(confirmButton()).toHaveTextContent('Continue to payment')
  await userEvent.setup().click(confirmButton())
  expect(confirmButton()).toBeDisabled()
  expect(confirmButton()).toHaveTextContent('Starting payment…')
  expect(screen.getByRole('form', { name: 'Your details' })).toHaveAttribute('aria-busy', 'true')
  expect(onSubmittingChange).toHaveBeenLastCalledWith(true)
})

it('a 409 calls onAlreadyPaid', async () => {
  answer(409, { detail: 'This booking is already paid' })
  const { onAlreadyPaid, onCheckout } = renderForm(DETAILS)
  await userEvent.setup().click(confirmButton())
  await vi.waitFor(() => expect(onAlreadyPaid).toHaveBeenCalledTimes(1))
  expect(onCheckout).not.toHaveBeenCalled()
})

it('shows the server message when payment is unavailable', async () => {
  answer(503, { detail: 'Payment is unavailable right now — please try again or call us' })
  renderForm(DETAILS)
  await userEvent.setup().click(confirmButton())
  expect(await screen.findByRole('alert')).toHaveTextContent('Payment is unavailable right now')
  expect(confirmButton()).toBeEnabled()
})

it('a 410 from checkout calls onExpired', async () => {
  answer(410, { detail: 'Your hold has expired' })
  const { onExpired, onCheckout, onSubmittingChange } = renderForm(DETAILS)
  await userEvent.setup().click(confirmButton())
  await vi.waitFor(() => expect(onExpired).toHaveBeenCalledTimes(1))
  expect(onCheckout).not.toHaveBeenCalled()
  expect(onSubmittingChange).toHaveBeenLastCalledWith(false)
})

it('shows a field error the server sends back against that field', async () => {
  answer(422, { detail: 'email: Please enter a valid email address' })
  renderForm(DETAILS)
  await userEvent.setup().click(confirmButton())
  expect(await screen.findByLabelText('Email')).toHaveAccessibleDescription('Please enter a valid email address')
  expect(confirmButton()).toBeEnabled()
})
