import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { GARAGE } from '../testing/fixtures.ts'
import { PaymentStep } from './PaymentStep.tsx'
import type { BookingSummary, Checkout, CustomerDetails, Hold, HoldStatus, PaymentConfig } from './types.ts'

// No test loads Stripe: its form is a stub with a "Pay (test)" button that reports completion.
vi.mock('./StripeCheckout.tsx', () => ({
  StripeCheckout: (props: { publishableKey: string; clientSecret: string; onComplete: () => void }) => (
    <div data-testid="stripe-form" data-key={props.publishableKey} data-secret={props.clientSecret}>
      <button type="button" onClick={props.onComplete}>
        Pay (test)
      </button>
    </div>
  ),
}))

const HOLD: Hold = {
  reference: 'ABCD-EFGH',
  hold_token: 'token',
  expires_at: '2026-11-15T10:05:00+00:00',
  expires_in_seconds: 300,
  start: '2026-11-16T08:00:00+00:00',
  end: '2026-11-16T09:00:00+00:00',
  services: [{ slug: 'mot-test', name: 'MOT test', duration_minutes: 60, price_from_pence: 5485, price_to_pence: null }],
}
const STRIPE_CHECKOUT: Checkout = { client_secret: 'cs_1_secret', demo_session: null, expires_in_seconds: 600, amount_pence: 2000 }
const DEMO_CHECKOUT: Checkout = { client_secret: null, demo_session: 'demo_abc', expires_in_seconds: 600, amount_pence: 2000 }
const STRIPE: PaymentConfig = { provider: 'stripe', publishable_key: 'pk_test_123' }
const DEMO: PaymentConfig = { provider: 'demo' }
const DETAILS: CustomerDetails = {
  name: 'Sam Driver',
  phone: '07700 900123',
  email: 'sam@example.com',
  registration: 'ab12 cde',
  make: 'Ford',
  model: 'Focus',
  notes: '',
}
const SUMMARY: BookingSummary = {
  reference: 'ABCD-EFGH',
  status: 'confirmed',
  start: HOLD.start,
  end: HOLD.end,
  services: HOLD.services,
  registration: 'AB12CDE',
  make: 'Ford',
  model: 'Focus',
  deposit_paid_pence: 2000,
}
const HELD: HoldStatus = { status: 'held', deposit_status: 'unpaid', summary: null }
const CONFIRMED: HoldStatus = { status: 'confirmed', deposit_status: 'paid', summary: SUMMARY }
const REFUNDED: HoldStatus = { status: 'expired', deposit_status: 'refund_pending', summary: null }

type Handlers = {
  onBooked: Mock<(summary: BookingSummary) => void>
  onSettled: Mock<(status: HoldStatus) => void>
  onTimeUp: Mock<() => void>
  onBusyChange: Mock<(busy: boolean) => void>
}

function renderStep(checkout: Checkout = STRIPE_CHECKOUT, payment: PaymentConfig = STRIPE): Handlers {
  const handlers: Handlers = {
    onBooked: vi.fn<(summary: BookingSummary) => void>(),
    onSettled: vi.fn<(status: HoldStatus) => void>(),
    onTimeUp: vi.fn<() => void>(),
    onBusyChange: vi.fn<(busy: boolean) => void>(),
  }
  render(
    <PaymentStep
      hold={HOLD}
      checkout={checkout}
      payment={payment}
      zone="Europe/London"
      garage={GARAGE}
      details={DETAILS}
      pollMs={1000}
      pollLimit={3}
      {...handlers}
    />,
  )
  return handlers
}

/** Answers each fetch by URL; status replies are taken in order, the last one repeating. */
function stubApi(statuses: HoldStatus[], demo: { status: number; body: unknown } = { status: 200, body: {} }): Mock {
  let next = 0
  const fetchMock = vi.fn((url: string) => {
    if (url === '/api/holds/ABCD-EFGH/status') {
      const body = statuses[Math.min(next, statuses.length - 1)]
      next += 1
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
    }
    if (url.startsWith('/api/demo/checkout/')) {
      return Promise.resolve(new Response(JSON.stringify(demo.body), { status: demo.status }))
    }
    return Promise.resolve(new Response('{}', { status: 404 }))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const FAKE: Parameters<typeof vi.useFakeTimers>[0] = {
  toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'Date', 'performance'],
}

/** Let pending replies settle inside fake time: reading a Response body takes several turns. */
async function flush(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0)
  for (let i = 0; i < 20; i++) await Promise.resolve()
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('shows the summary and the deposit', () => {
  stubApi([HELD])
  renderStep()
  expect(screen.getByText(/Monday 16 November, 08:00 – 09:00/)).toBeInTheDocument()
  expect(screen.getByText('MOT test')).toBeInTheDocument()
  expect(screen.getByText('AB12CDE · Ford Focus')).toBeInTheDocument()
  expect(screen.getByText('Deposit £20, balance paid at the garage')).toBeInTheDocument()
})

it("counts down from the checkout's seconds", () => {
  vi.useFakeTimers(FAKE)
  stubApi([HELD])
  renderStep()
  expect(screen.getByRole('timer')).toHaveTextContent('10:00')
  act(() => vi.advanceTimersByTime(61_000))
  expect(screen.getByRole('timer')).toHaveTextContent('8:59')
})

it("shows Stripe's form with the publishable key and client secret", () => {
  stubApi([HELD])
  renderStep()
  const form = screen.getByTestId('stripe-form')
  expect(form).toHaveAttribute('data-key', 'pk_test_123')
  expect(form).toHaveAttribute('data-secret', 'cs_1_secret')
  expect(screen.queryByRole('button', { name: /demo/ })).not.toBeInTheDocument()
})

it('shows the demo box in demo mode', () => {
  stubApi([HELD])
  renderStep(DEMO_CHECKOUT, DEMO)
  expect(screen.getByRole('button', { name: 'Pay £20 (demo)' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Decline card (demo)' })).toBeInTheDocument()
  expect(screen.queryByTestId('stripe-form')).not.toBeInTheDocument()
})

it('demo decline shows the message and changes nothing', async () => {
  stubApi([HELD], { status: 402, body: { detail: 'Your card was declined (demo)' } })
  const { onBooked, onSettled } = renderStep(DEMO_CHECKOUT, DEMO)
  await userEvent.setup().click(screen.getByRole('button', { name: 'Decline card (demo)' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Your card was declined (demo)')
  expect(screen.getByRole('button', { name: 'Pay £20 (demo)' })).toBeEnabled()
  expect(onBooked).not.toHaveBeenCalled()
  expect(onSettled).not.toHaveBeenCalled()
})

it('demo pay confirms through the status check', async () => {
  const fetchMock = stubApi([CONFIRMED], { status: 200, body: { status: 'confirmed' } })
  const { onBooked } = renderStep(DEMO_CHECKOUT, DEMO)
  await userEvent.setup().click(screen.getByRole('button', { name: 'Pay £20 (demo)' }))
  await vi.waitFor(() => expect(onBooked).toHaveBeenCalledWith(SUMMARY))
  const [url, init] = fetchMock.mock.calls[0]
  expect(url).toBe('/api/demo/checkout/demo_abc')
  expect(JSON.parse(String((init as RequestInit).body))).toEqual({ outcome: 'pay' })
})

it('completing polls until confirmed then calls onBooked', async () => {
  vi.useFakeTimers(FAKE)
  stubApi([HELD, HELD, CONFIRMED])
  const { onBooked, onBusyChange } = renderStep()
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Pay (test)' }))
    await flush()
  })
  expect(screen.getByRole('status')).toHaveTextContent('Confirming your payment…')
  expect(onBusyChange).toHaveBeenLastCalledWith(true)
  expect(onBooked).not.toHaveBeenCalled()
  await act(async () => {
    vi.advanceTimersByTime(1000)
    await flush()
    vi.advanceTimersByTime(1000)
    await flush()
  })
  expect(onBooked).toHaveBeenCalledWith(SUMMARY)
})

it('a released status calls onSettled', async () => {
  stubApi([REFUNDED])
  const { onSettled, onBooked } = renderStep()
  await userEvent.setup().click(screen.getByRole('button', { name: 'Pay (test)' }))
  await vi.waitFor(() => expect(onSettled).toHaveBeenCalledWith(REFUNDED))
  expect(onBooked).not.toHaveBeenCalled()
})

it('gives up after the limit with the reference and phone', async () => {
  vi.useFakeTimers(FAKE)
  stubApi([HELD])
  const { onBooked, onSettled, onBusyChange } = renderStep()
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Pay (test)' }))
    await flush()
    for (let i = 0; i < 3; i++) {
      vi.advanceTimersByTime(1000)
      await flush()
    }
  })
  const message = screen.getByRole('status')
  expect(message).toHaveTextContent("We're still confirming your payment.")
  expect(message).toHaveTextContent('ABCD-EFGH')
  expect(message).toHaveTextContent('01632 960123')
  expect(onBooked).not.toHaveBeenCalled()
  expect(onSettled).not.toHaveBeenCalled()
  expect(onBusyChange).toHaveBeenLastCalledWith(false)
})

it('the countdown ending while polling waits for the poll', async () => {
  vi.useFakeTimers(FAKE)
  stubApi([HELD, CONFIRMED])
  const { onBooked, onTimeUp } = renderStep({ ...STRIPE_CHECKOUT, expires_in_seconds: 1 })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Pay (test)' }))
    await flush()
  })
  await act(async () => {
    vi.advanceTimersByTime(2000) // the countdown passes zero mid-poll
    await flush()
  })
  expect(onTimeUp).not.toHaveBeenCalled()
  expect(onBooked).toHaveBeenCalledWith(SUMMARY)
})

it('the countdown ending otherwise calls onTimeUp once', () => {
  vi.useFakeTimers(FAKE)
  stubApi([HELD])
  const { onTimeUp } = renderStep()
  act(() => vi.advanceTimersByTime(599_000))
  expect(onTimeUp).not.toHaveBeenCalled()
  act(() => vi.advanceTimersByTime(5_000))
  expect(onTimeUp).toHaveBeenCalledTimes(1)
})
