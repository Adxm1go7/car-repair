import { useEffect, useRef, useState } from 'react'
import type { JSX } from 'react'
import { formatPrice } from '../catalogue/format.ts'
import type { Garage } from '../catalogue/types.ts'
import { fetchHoldStatus, payDemo } from './api.ts'
import { formatLongDate, formatTimeRange } from './format.ts'
import { StripeCheckout } from './StripeCheckout.tsx'
import type { BookingSummary, Checkout, CustomerDetails, Hold, HoldStatus, PaymentConfig } from './types.ts'
import { formatCountdown, useCountdown } from './useCountdown.ts'

type Props = {
  hold: Hold
  checkout: Checkout
  payment: PaymentConfig
  zone: string
  garage: Garage
  details: CustomerDetails
  /** The server confirmed the booking. */
  onBooked: (summary: BookingSummary) => void
  /** The server says the hold is gone (released, or refunded after a late payment). */
  onSettled: (status: HoldStatus) => void
  /** The countdown reached zero with no payment being checked: the page releases the hold. */
  onTimeUp: () => void
  /** True while a payment is being checked, so the page can switch off its other buttons. */
  onBusyChange: (busy: boolean) => void
  pollMs?: number
  pollLimit?: number
}

type Phase = 'paying' | 'confirming' | 'stuck'

/** What a screen reader hears. It changes only at these moments, so it isn't read every second. */
function announcement(remaining: number): string {
  if (remaining === 0) return 'Your time to pay has run out'
  if (remaining <= 60) return '1 minute left to pay'
  if (remaining <= 300) return '5 minutes left to pay'
  return ''
}

function telHref(phone: string): string {
  return `tel:${phone.replace(/\s+/g, '')}`
}

export function PaymentStep(props: Props): JSX.Element {
  const { hold, checkout, payment, zone, garage, details, pollMs = 1000, pollLimit = 30 } = props
  const [phase, setPhase] = useState<Phase>('paying')
  const [problem, setProblem] = useState<string | null>(null)
  const [demoBusy, setDemoBusy] = useState(false)

  // The parent's callbacks, read when the poll answers rather than when it started.
  const latest = useRef(props)
  useEffect(() => {
    latest.current = props
  })

  // Polling and the countdown can race; once the poll has started, it decides.
  const polling = useRef(false)
  const gone = useRef(false)
  useEffect(() => {
    gone.current = false
    return () => {
      gone.current = true // a late poll answer must not act
    }
  }, [])

  const remaining = useCountdown(checkout.expires_in_seconds, () => {
    if (!polling.current && !gone.current) latest.current.onTimeUp()
  })

  async function poll(): Promise<void> {
    if (polling.current) return
    polling.current = true
    setPhase('confirming')
    latest.current.onBusyChange(true)
    for (let attempt = 0; attempt < pollLimit; attempt++) {
      if (attempt > 0) await new Promise((resolve) => setTimeout(resolve, pollMs))
      if (gone.current) return
      const result = await fetchHoldStatus(hold.reference, hold.hold_token)
      if (gone.current) return
      if (!result.ok) continue // a blip: ask again
      if (result.data.status === 'confirmed') {
        latest.current.onBooked(result.data.summary)
        return
      }
      if (result.data.status === 'expired') {
        latest.current.onSettled(result.data)
        return
      }
    }
    setPhase('stuck')
    latest.current.onBusyChange(false)
  }

  async function demo(outcome: 'pay' | 'decline'): Promise<void> {
    if (!checkout.demo_session || demoBusy) return
    setDemoBusy(true)
    setProblem(null)
    const result = await payDemo(checkout.demo_session, outcome)
    if (gone.current) return
    setDemoBusy(false)
    if (result.ok) {
      void poll()
    } else if (result.kind === 'declined') {
      setProblem('Your card was declined (demo)')
    } else {
      setProblem(result.detail ?? "Sorry, we couldn't take the payment. Please try again.")
    }
  }

  const deposit = formatPrice(checkout.amount_pence, null)
  const registration = details.registration.replace(/\s+/g, '').toUpperCase()
  const phone = <a href={telHref(garage.phone)}>{garage.phone}</a>

  return (
    <section className="payment" aria-label="Pay your deposit">
      <p className="hold-banner">
        {`We're holding ${formatLongDate(hold.start, zone)}, ${formatTimeRange(hold.start, hold.end, zone)} for `}
        <span role="timer" className="countdown">
          {formatCountdown(remaining)}
        </span>
      </p>
      <div data-testid="countdown-announcer" className="visually-hidden" aria-live="polite">
        {phase === 'paying' ? announcement(remaining) : ''}
      </div>

      <div className="payment-summary">
        <ul className="booked-services">
          {hold.services.map((service) => (
            <li key={service.slug}>{service.name}</li>
          ))}
        </ul>
        <p>{`${registration} · ${details.make} ${details.model}`}</p>
        <p className="payment-deposit">{`Deposit ${deposit}, balance paid at the garage`}</p>
      </div>

      {phase === 'confirming' && (
        <p role="status" className="notice">
          Confirming your payment…
        </p>
      )}
      {phase === 'stuck' && (
        <p role="status" className="notice">
          {`We're still confirming your payment. Your booking reference is ${hold.reference}. Please call us on `}
          {phone}
          {" if you don't see it confirmed."}
        </p>
      )}

      {payment.provider === 'stripe' && checkout.client_secret ? (
        <StripeCheckout
          publishableKey={payment.publishable_key}
          clientSecret={checkout.client_secret}
          onComplete={() => void poll()}
        />
      ) : (
        phase === 'paying' && (
          <div className="demo-payment">
            <p>Demo mode: no card is charged. Set Stripe test keys to use the real payment form.</p>
            {problem && (
              <p role="alert" className="notice">
                {problem}
              </p>
            )}
            <button type="button" className="button" disabled={demoBusy} onClick={() => void demo('pay')}>
              {`Pay ${deposit} (demo)`}
            </button>
            <button type="button" className="link-button" disabled={demoBusy} onClick={() => void demo('decline')}>
              Decline card (demo)
            </button>
          </div>
        )
      )}
    </section>
  )
}
