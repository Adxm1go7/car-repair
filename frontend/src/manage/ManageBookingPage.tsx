import { useEffect, useRef, useState } from 'react'
import type { JSX, KeyboardEvent } from 'react'
import { useLocation, useParams } from 'react-router'
import { formatLongDate, formatTime, formatTimeRange } from '../booking/format.ts'
import { formatPrice } from '../catalogue/format.ts'
import type { Garage } from '../catalogue/types.ts'
import { cancelBooking, viewBooking } from './api.ts'
import { PayDeposit } from './PayDeposit.tsx'
import type { MyBooking } from './types.ts'

// Customers can't reschedule: the garage wants a call for a different time. So nothing on
// this page offers to move or rebook; it points to the phone instead.

type PageState =
  | { kind: 'loading' }
  | { kind: 'invalid' }
  | { kind: 'error' }
  | { kind: 'ready'; booking: MyBooking }

const CANCELLED_DEPOSIT: Record<string, string> = {
  refund_pending: 'Your deposit refund is on its way',
  refunded: 'Your deposit has been refunded',
  refund_failed: "We'll be in touch about your refund",
  paid: 'Your deposit was kept',
}

const OTHER_STATUS: Record<string, string> = {
  in_progress: 'Your car is being worked on',
  completed: 'This booking is complete',
  no_show: 'This booking was missed',
  expired: 'The time we were keeping for you has been released',
}

/** Bookings the customer can still cancel from the link (a request or an approval at any
 * time, nothing being paid; a confirmed one while the API says so). */
const CANCELLABLE = new Set(['confirmed', 'pending_approval', 'awaiting_deposit'])
const WAITING = new Set(['pending_approval', 'awaiting_deposit'])
/** An approval paid after its time was released: the payment goes back. */
const LATE_REFUND = new Set(['refund_pending', 'refunded'])

/** "Wednesday 18 November at 09:00". */
function formatDeadline(iso: string, zone: string): string {
  return `${formatLongDate(iso, zone)} at ${formatTime(iso, zone)}`
}

function telHref(phone: string): string {
  return `tel:${phone.replace(/\s+/g, '')}`
}

/** The token from "#t=…". Never in the path or query, so it isn't logged or sent on. */
function tokenFrom(hash: string): string | null {
  const token = new URLSearchParams(hash.slice(1)).get('t')
  return token ? token : null
}

function Summary({ booking, zone }: { booking: MyBooking; zone: string }): JSX.Element {
  const { summary } = booking
  const showDeposit = summary.status !== 'cancelled' && booking.deposit_status === 'paid'
  return (
    <>
      <dl className="booked-reference">
        <dt>Reference</dt>
        <dd>{summary.reference}</dd>
      </dl>
      <p className="booked-when">
        {`${formatLongDate(summary.start, zone)}, ${formatTimeRange(summary.start, summary.end, zone)}`}
      </p>
      <ul className="booked-services">
        {summary.services.map((service) => (
          <li key={service.slug}>{service.name}</li>
        ))}
      </ul>
      <p>{`${summary.registration} · ${summary.make} ${summary.model}`}</p>
      {showDeposit && summary.deposit_paid_pence > 0 && (
        <p className="booked-deposit">{`Deposit: ${formatPrice(summary.deposit_paid_pence, null)} paid`}</p>
      )}
    </>
  )
}

type DialogProps = {
  booking: MyBooking
  zone: string
  phone: JSX.Element
  busy: boolean
  onConfirm: () => void
  onKeep: () => void
}

function ConfirmCancel({ booking, zone, phone, busy, onConfirm, onKeep }: DialogProps): JSX.Element {
  const keepRef = useRef<HTMLButtonElement>(null)
  const { summary } = booking
  const what = summary.status === 'pending_approval' ? 'request' : 'booking'

  useEffect(() => {
    keepRef.current?.focus()
  }, [])

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === 'Escape' && !busy) onKeep()
  }

  return (
    <div
      role="alertdialog"
      aria-labelledby="cancel-title"
      aria-describedby="cancel-description"
      className="confirm-cancel"
      onKeyDown={onKeyDown}
    >
      <h2 id="cancel-title">
        {`Cancel your ${what} on ${formatLongDate(summary.start, zone)} at ${formatTime(summary.start, zone)}?`}
      </h2>
      <div id="cancel-description">
        {booking.refund_if_cancelled && summary.deposit_paid_pence > 0 && (
          <p>{`You'll get your ${formatPrice(summary.deposit_paid_pence, null)} deposit back.`}</p>
        )}
        <p>If you just need a different time, please call us on {phone} instead and we can move it for you.</p>
      </div>
      <div className="confirm-actions">
        <button type="button" className="button button-danger" onClick={onConfirm} disabled={busy}>
          {busy ? 'Cancelling…' : 'Yes, cancel it'}
        </button>
        <button type="button" className="button button-secondary" ref={keepRef} onClick={onKeep} disabled={busy}>
          {`Keep my ${what}`}
        </button>
      </div>
    </div>
  )
}

type PageProps = { garage: Garage; pollMs?: number }

export function ManageBookingPage({ garage, pollMs }: PageProps): JSX.Element {
  const { reference = '' } = useParams()
  const token = tokenFrom(useLocation().hash)
  const [state, setState] = useState<PageState>(token === null ? { kind: 'invalid' } : { kind: 'loading' })
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [cancelFailed, setCancelFailed] = useState(false)
  const [cancelProblem, setCancelProblem] = useState<string | null>(null) // the server's reason
  const [justPaid, setJustPaid] = useState(false)
  const [payGone, setPayGone] = useState(false)
  const cancelButtonRef = useRef<HTMLButtonElement>(null)
  const returnFocus = useRef(false)
  const zone = garage.timezone
  const phone = <a href={telHref(garage.phone)}>{garage.phone}</a>

  useEffect(() => {
    if (token === null) return
    let stale = false
    void viewBooking(reference, token).then((result) => {
      if (stale) return
      if (result.ok) setState({ kind: 'ready', booking: result.data })
      else setState({ kind: result.kind === 'invalid' ? 'invalid' : 'error' })
    })
    return () => {
      stale = true
    }
  }, [reference, token])

  // Back to "Cancel booking" when the dialog closes and the button is still there.
  useEffect(() => {
    if (!confirming && returnFocus.current) {
      returnFocus.current = false
      cancelButtonRef.current?.focus()
    }
  }, [confirming])

  function closeDialog(): void {
    returnFocus.current = true
    setConfirming(false)
  }

  async function confirmCancel(booking: MyBooking): Promise<void> {
    if (token === null) return
    setBusy(true)
    const result = await cancelBooking(reference, token)
    setBusy(false)
    if (result.ok) {
      setState({ kind: 'ready', booking: result.data })
      setConfirming(false)
      return
    }
    if (result.kind === 'invalid') {
      setState({ kind: 'invalid' })
    } else if (result.kind === 'refused' && result.reason === 'too_late') {
      setState({ kind: 'ready', booking: { ...booking, can_cancel: false, refund_if_cancelled: false } })
      setConfirming(false)
      return
    } else if (result.kind === 'refused') {
      // Already cancelled, perhaps in another tab: show how it stands now.
      const fresh = await viewBooking(reference, token)
      setState(fresh.ok ? { kind: 'ready', booking: fresh.data } : { kind: 'invalid' })
    } else if (result.kind === 'error' && result.detail) {
      setCancelProblem(result.detail) // e.g. too many attempts
    } else {
      setCancelFailed(true)
    }
    closeDialog()
  }

  if (state.kind === 'loading') {
    return (
      <main className="page booked">
        <p>Loading…</p>
      </main>
    )
  }

  if (state.kind === 'invalid' || state.kind === 'error') {
    return (
      <main className="page booked">
        <h1 className="step-title">Your booking</h1>
        <div role="alert" className="error">
          {state.kind === 'invalid' ? (
            <p>This link isn&apos;t valid any more. Please call us on {phone}.</p>
          ) : (
            <p>We couldn&apos;t load your booking just now. Please try again, or call us on {phone}.</p>
          )}
        </div>
      </main>
    )
  }

  async function reload(): Promise<void> {
    if (token === null) return
    const fresh = await viewBooking(reference, token)
    setState(fresh.ok ? { kind: 'ready', booking: fresh.data } : { kind: fresh.kind === 'invalid' ? 'invalid' : 'error' })
  }

  const { booking } = state
  const status = booking.summary.status
  const canCancel = CANCELLABLE.has(status) && booking.can_cancel
  const what = status === 'pending_approval' ? 'request' : 'booking'
  return (
    <main className="page booked">
      <h1 className="step-title">Your booking</h1>
      {justPaid && status === 'confirmed' && <p className="booking-state">Your booking is confirmed</p>}
      {payGone && (
        <p role="alert" className="error">
          This booking can&apos;t be paid for any more. Please call us on {phone}.
        </p>
      )}
      {status === 'cancelled' && (
        <div className="booking-state">
          <p className="booking-cancelled">This booking is cancelled</p>
          {CANCELLED_DEPOSIT[booking.deposit_status] && <p>{CANCELLED_DEPOSIT[booking.deposit_status]}</p>}
        </div>
      )}
      {OTHER_STATUS[status] && <p className="booking-state">{OTHER_STATUS[status]}</p>}
      {status === 'expired' && LATE_REFUND.has(booking.deposit_status) && (
        <p>
          Your payment came in after the time was released, so we&apos;re refunding it. It can take 5–10 days to
          reach your card.
        </p>
      )}
      <Summary booking={booking} zone={zone} />

      {status === 'pending_approval' && booking.deadline && (
        <p>{`We're checking your request and will email you by ${formatDeadline(booking.deadline, zone)}.`}</p>
      )}
      {status === 'awaiting_deposit' && booking.deadline && token !== null && (
        <PayDeposit
          reference={reference}
          token={token}
          deadline={formatDeadline(booking.deadline, zone)}
          phone={phone}
          pollMs={pollMs}
          onPaid={(paid) => {
            setJustPaid(true)
            setState({ kind: 'ready', booking: paid })
          }}
          onGone={() => {
            setPayGone(true)
            void reload()
          }}
          onSettled={(settled) => setState({ kind: 'ready', booking: settled })}
        />
      )}

      {canCancel && (
        <>
          {status === 'confirmed' && <p>Need a different time? Call us on {phone} and we&apos;ll sort it out.</p>}
          {cancelProblem && (
            <p role="alert" className="error">
              {cancelProblem}
            </p>
          )}
          {cancelFailed && (
            <p role="alert" className="error">
              We couldn&apos;t cancel just now. Please try again, or call us on {phone}.
            </p>
          )}
          {confirming ? (
            <ConfirmCancel
              booking={booking}
              zone={zone}
              phone={phone}
              busy={busy}
              onConfirm={() => void confirmCancel(booking)}
              onKeep={closeDialog}
            />
          ) : (
            <button
              type="button"
              className="button button-secondary"
              ref={cancelButtonRef}
              onClick={() => {
                setCancelFailed(false)
                setCancelProblem(null)
                setConfirming(true)
              }}
            >
              {`Cancel ${what}`}
            </button>
          )}
        </>
      )}
      {status === 'confirmed' && !booking.can_cancel && <p>To change or cancel, please call us on {phone}.</p>}
      {status !== 'confirmed' && !WAITING.has(status) && <p>Questions about your booking? Call us on {phone}.</p>}
      {WAITING.has(status) && <p>Questions? Call us on {phone}.</p>}
      <p>{garage.address}</p>
    </main>
  )
}
