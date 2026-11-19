import { useEffect, useRef, useState } from 'react'
import type { JSX } from 'react'
import { fetchBookingPolicy, payDemo } from '../booking/api.ts'
import { StripeCheckout } from '../booking/StripeCheckout.tsx'
import type { BookingPolicy, Checkout } from '../booking/types.ts'
import { formatPrice } from '../catalogue/format.ts'
import { startPayment, viewBooking } from './api.ts'
import type { MyBooking } from './types.ts'

type Props = {
  reference: string
  token: string
  /** "Wednesday 18 November at 09:00": when the deposit is due by. */
  deadline: string
  phone: JSX.Element
  /** The payment went through: the booking is confirmed. */
  onPaid: (booking: MyBooking) => void
  /** The booking can't be paid for any more (paid, cancelled, or run out). */
  onGone: () => void
  /** After paying, the booking ended without being confirmed (the time had gone, so the
   * payment is refunded): the page shows it as it is now. */
  onSettled: (booking: MyBooking) => void
  pollMs?: number
  pollLimit?: number
}

type Phase = 'ready' | 'opening' | 'paying' | 'confirming' | 'stuck'

/** Pay the deposit for a booking the garage approved, with the same payment form as the
 * booking page. Once paid, the booking is asked about until it says confirmed. */
export function PayDeposit(props: Props): JSX.Element {
  const { reference, token, deadline, phone, pollMs = 1000, pollLimit = 15 } = props
  const [policy, setPolicy] = useState<BookingPolicy | null>(null)
  const [checkout, setCheckout] = useState<Checkout | null>(null)
  const [phase, setPhase] = useState<Phase>('ready')
  const [problem, setProblem] = useState<string | null>(null)
  const latest = useRef(props)
  useEffect(() => {
    latest.current = props
  })
  const gone = useRef(false)
  useEffect(() => {
    gone.current = false
    let stale = false
    void fetchBookingPolicy().then((result) => {
      if (!stale && result.ok) setPolicy(result.data)
    })
    return () => {
      stale = true
      gone.current = true
    }
  }, [])

  async function open(): Promise<void> {
    setPhase('opening')
    setProblem(null)
    const result = await startPayment(reference, token)
    if (gone.current) return
    if (result.ok) {
      setCheckout(result.data)
      setPhase('paying')
      return
    }
    setPhase('ready')
    if (result.kind === 'gone' || result.kind === 'invalid') latest.current.onGone()
    else setProblem("Sorry, we couldn't open the payment just now. Please try again.")
  }

  async function poll(): Promise<void> {
    setPhase('confirming')
    for (let attempt = 0; attempt < pollLimit; attempt++) {
      if (attempt > 0) await new Promise((resolve) => setTimeout(resolve, pollMs))
      if (gone.current) return
      const result = await viewBooking(reference, token)
      if (gone.current) return
      if (result.ok && result.data.summary.status === 'confirmed') {
        latest.current.onPaid(result.data)
        return
      }
      if (result.ok && (result.data.summary.status === 'expired' || result.data.summary.status === 'cancelled')) {
        latest.current.onSettled(result.data)
        return
      }
    }
    setPhase('stuck')
  }

  async function demo(outcome: 'pay' | 'decline'): Promise<void> {
    if (!checkout?.demo_session) return
    setProblem(null)
    const result = await payDemo(checkout.demo_session, outcome)
    if (gone.current) return
    if (result.ok) void poll()
    else if (result.kind === 'declined') setProblem('Your card was declined (demo)')
    else setProblem(result.detail ?? "Sorry, we couldn't take the payment. Please try again.")
  }

  const amount = checkout?.amount_pence ?? policy?.deposit_amount_pence
  const deposit = amount === undefined ? 'deposit' : `${formatPrice(amount, null)} deposit`
  return (
    <div className="pay-deposit">
      <p className="pay-due">{`Pay the ${deposit} by ${deadline} to confirm.`}</p>
      {problem && (
        <p role="alert" className="notice">
          {problem}
        </p>
      )}
      {(phase === 'ready' || phase === 'opening') && (
        <button type="button" className="button" disabled={phase === 'opening'} onClick={() => void open()}>
          {phase === 'opening' ? 'Opening payment…' : 'Pay deposit'}
        </button>
      )}
      {phase === 'paying' && checkout && policy?.payment.provider === 'stripe' && checkout.client_secret ? (
        <StripeCheckout
          publishableKey={policy.payment.publishable_key}
          clientSecret={checkout.client_secret}
          onComplete={() => void poll()}
        />
      ) : (
        phase === 'paying' &&
        checkout && (
          <div className="demo-payment">
            <p>Demo payment: no card is needed.</p>
            <button type="button" className="button" onClick={() => void demo('pay')}>
              {`Pay ${formatPrice(checkout.amount_pence, null)} (demo)`}
            </button>
            <button type="button" className="link-button" onClick={() => void demo('decline')}>
              Decline card (demo)
            </button>
          </div>
        )
      )}
      {phase === 'confirming' && <p role="status">Confirming your payment…</p>}
      {phase === 'stuck' && (
        <p role="alert" className="notice">
          {`We're still confirming your payment. Your booking reference is ${reference}. Please call us on `}
          {phone} if you don&apos;t get a confirmation email soon.
        </p>
      )}
    </div>
  )
}
