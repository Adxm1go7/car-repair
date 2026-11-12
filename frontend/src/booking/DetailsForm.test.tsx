import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import type { JSX } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { DetailsForm } from './DetailsForm.tsx'
import type { BookingSummary, CustomerDetails, Hold } from './types.ts'

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

const SUMMARY: BookingSummary = {
  reference: 'ABCD-EFGH',
  status: 'confirmed',
  start: HOLD.start,
  end: HOLD.end,
  services: [],
  registration: 'AB12CDE',
  make: 'Ford',
  model: 'Focus',
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
  onBooked: Mock<(summary: BookingSummary) => void>
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
    onBooked: vi.fn<(summary: BookingSummary) => void>(),
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

const confirmButton = (): HTMLElement => screen.getByRole('button', { name: 'Confirm booking' })

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
  expect(live).toHaveTextContent('5 minutes left to confirm')
  act(() => vi.advanceTimersByTime(240_000)) // 1:00
  expect(live).toHaveTextContent('1 minute left to confirm')
})

it('reports expiry once when the countdown reaches zero', () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'Date', 'performance'] })
  const { onExpired } = renderForm()
  act(() => vi.advanceTimersByTime(599_000))
  expect(onExpired).not.toHaveBeenCalled()
  act(() => vi.advanceTimersByTime(5_000))
  expect(onExpired).toHaveBeenCalledTimes(1)
})

// --- the form -----------------------------------------------------------------------

it('labels every field', () => {
  renderForm()
  for (const label of ['Name', 'Phone', 'Email', 'Registration', 'Make', 'Model', 'Notes (optional)']) {
    expect(screen.getByLabelText(label)).toBeInTheDocument()
  }
})

it('shows field errors and does not call the API when invalid', async () => {
  const fetchMock = answer(200, SUMMARY)
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

it('confirms with the typed details and hands back the summary', async () => {
  const fetchMock = answer(200, SUMMARY)
  const { onBooked } = renderForm(DETAILS)
  await userEvent.setup().click(confirmButton())
  await vi.waitFor(() => expect(onBooked).toHaveBeenCalledWith(SUMMARY))
  const [url, init] = fetchMock.mock.calls[0]
  expect(url).toBe('/api/holds/ABCD-EFGH/confirm')
  expect(JSON.parse(String((init as RequestInit).body))).toEqual({ hold_token: 'token', ...DETAILS })
})

it('disables the confirm button while submitting, and says so', async () => {
  vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {}))) // never answers
  const { onSubmittingChange } = renderForm(DETAILS)
  await userEvent.setup().click(confirmButton())
  expect(confirmButton()).toBeDisabled()
  expect(onSubmittingChange).toHaveBeenLastCalledWith(true)
})

it('a 410 from confirm calls onExpired', async () => {
  answer(410, { detail: 'Your hold has expired' })
  const { onExpired, onBooked, onSubmittingChange } = renderForm(DETAILS)
  await userEvent.setup().click(confirmButton())
  await vi.waitFor(() => expect(onExpired).toHaveBeenCalledTimes(1))
  expect(onBooked).not.toHaveBeenCalled()
  expect(onSubmittingChange).toHaveBeenLastCalledWith(false)
})

it('shows a field error the server sends back against that field', async () => {
  answer(422, { detail: 'email: Please enter a valid email address' })
  renderForm(DETAILS)
  await userEvent.setup().click(confirmButton())
  expect(await screen.findByLabelText('Email')).toHaveAccessibleDescription('Please enter a valid email address')
  expect(confirmButton()).toBeEnabled()
})
