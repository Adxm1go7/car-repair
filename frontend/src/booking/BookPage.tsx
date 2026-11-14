import { useEffect, useRef, useState } from 'react'
import type { JSX, MouseEvent, RefObject } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'
import { formatDuration } from '../catalogue/format.ts'
import type { Catalogue } from '../catalogue/types.ts'
import { cancelHold, fetchBookingPolicy, fetchHoldStatus } from './api.ts'
import type { Result } from './api.ts'
import { bookableDays, todayInZone } from './days.ts'
import { DetailsForm } from './DetailsForm.tsx'
import { PaymentStep } from './PaymentStep.tsx'
import { parseSelection, selectionQuery, totalMinutes } from './selection.ts'
import { TimePicker } from './TimePicker.tsx'
import type { BookingPolicy, BookingSummary, Checkout, CustomerDetails, Hold, HoldStatus } from './types.ts'

type Step =
  | { kind: 'picking'; notice?: string }
  | { kind: 'details'; hold: Hold }
  | { kind: 'paying'; hold: Hold; checkout: Checkout }

const RAN_OUT = 'Your hold ran out, so we released that time.'
const NOT_CHARGED = "Your time ran out, so we released it. You haven't been charged."
const REFUNDED =
  "Your payment came in after your time ran out, and that time has been taken. We've refunded your deposit; " +
  'it can take 5–10 days to reach your card.'

const TITLES: Record<Step['kind'], string> = {
  picking: 'Choose a time',
  details: 'Your details',
  paying: 'Pay your deposit',
}

const EMPTY_DETAILS: CustomerDetails = {
  name: '',
  phone: '',
  email: '',
  registration: '',
  make: '',
  model: '',
  notes: '',
}

type Props = { catalogue: Catalogue; now: () => Date }

/** Give the held slot back, once. Best effort: if it fails, the hold runs out by itself. */
function releaseHold(unreleased: RefObject<Hold | null>): void {
  const hold = unreleased.current
  unreleased.current = null
  if (hold) void cancelHold(hold.reference, hold.hold_token)
}

/** Choose a time, enter details, then pay the deposit. The chosen services come from the URL. */
export function BookPage({ catalogue, now }: Props): JSX.Element {
  const { services, hours, garage } = catalogue
  const location = useLocation()
  const [policy, setPolicy] = useState<Result<BookingPolicy> | null>(null)
  const [step, setStep] = useState<Step>({ kind: 'picking' })
  // What the customer typed. It lives here, not in the form, so it survives changing time
  // and a hold running out. Changing services leaves this page, which drops it.
  const [details, setDetails] = useState<CustomerDetails>(EMPTY_DETAILS)
  // A request is deciding the booking (starting payment, checking it, or releasing): the
  // step buttons wait for its answer.
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  // The hold this page should give back if the customer leaves. It is cleared once the
  // booking is confirmed, the hold has run out, or it has already been released.
  const unreleased = useRef<Hold | null>(null)

  // Leaving without a button: Back (or any link) unmounts this page; a refresh or closing
  // the tab fires pagehide, where cancelHold's keepalive lets the request outlive the page.
  useEffect(() => {
    const onPageHide = (): void => releaseHold(unreleased)
    window.addEventListener('pagehide', onPageHide)
    return () => {
      window.removeEventListener('pagehide', onPageHide)
      releaseHold(unreleased)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    void fetchBookingPolicy().then((result) => {
      if (!cancelled) setPolicy(result)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const bookable = new Set(services.filter((s) => s.approval_mode === 'instant').map((s) => s.slug))
  const chosen = parseSelection(location.search).filter((slug) => bookable.has(slug))
  if (chosen.length === 0) return <Navigate to="/" replace />

  const names = services.filter((s) => chosen.includes(s.slug)).map((s) => s.name)
  const zone = garage.timezone
  const held = step.kind === 'picking' ? null : step.hold
  const servicesUrl = `/${selectionQuery(chosen)}`

  function booked(summary: BookingSummary): void {
    unreleased.current = null // paid: never give it back
    void navigate(`/booked/${summary.reference}`, { state: summary })
  }

  /** Where to go once the server says the hold is gone. `fallback` is for nothing paid. */
  function afterRelease(status: HoldStatus | null, fallback: string | undefined, reference: string): void {
    unreleased.current = null // the server has already let it go
    const deposit = status?.deposit_status
    if (status?.payment_pending) {
      // The server couldn't close the payment form yet, so a payment may still arrive (it
      // will end as a booking or a refund). Never tell the customer they weren't charged.
      setStep({
        kind: 'picking',
        notice:
          `We couldn't confirm whether your payment went through. Your booking reference is ${reference}. ` +
          `Please call us on ${garage.phone} before booking again.`,
      })
    } else if (deposit === 'refund_pending' || deposit === 'refunded') {
      setStep({ kind: 'picking', notice: REFUNDED })
    } else if (deposit === 'refund_failed') {
      setStep({
        kind: 'picking',
        notice: `Your payment came in after your time ran out. Please call us on ${garage.phone} so we can refund it.`,
      })
    } else {
      setStep({ kind: 'picking', notice: fallback })
    }
  }

  /**
   * Leaving the payment step on purpose (time up, Change time, Change services): release the
   * hold and close the payment form, then ask the server what happened before saying
   * anything, because a payment already in flight can still get through.
   * Returns true when the page should carry on leaving (nothing was booked).
   */
  async function settle(fallback: string | undefined): Promise<boolean> {
    const hold = unreleased.current
    if (!hold) return true
    unreleased.current = null // so unmounting doesn't release it a second time
    setBusy(true)
    const outcome = await cancelHold(hold.reference, hold.hold_token)
    const status = await fetchHoldStatus(hold.reference, hold.hold_token)
    setBusy(false)
    if (status.ok && status.data.status === 'confirmed') {
      booked(status.data.summary)
      return false
    }
    if (outcome === 'paid') {
      // Booked, but the summary couldn't be fetched: the booked page shows the reference.
      void navigate(`/booked/${hold.reference}`)
      return false
    }
    afterRelease(status.ok ? status.data : null, fallback, hold.reference)
    return true
  }

  function changeTime(): void {
    if (step.kind === 'paying') {
      void settle(undefined)
      return
    }
    releaseHold(unreleased)
    setStep({ kind: 'picking' })
  }

  function changeServices(event: MouseEvent<HTMLAnchorElement>): void {
    if (busy) {
      // Mid-request the booking may already be made: stay until the reply decides.
      event.preventDefault()
      return
    }
    if (step.kind !== 'paying') {
      releaseHold(unreleased)
      return
    }
    event.preventDefault()
    void settle(undefined).then((leave) => {
      if (leave) void navigate(servicesUrl)
    })
  }

  /** The details step's 409: a payment already confirmed this booking. */
  async function alreadyPaid(hold: Hold): Promise<void> {
    const status = await fetchHoldStatus(hold.reference, hold.hold_token)
    if (status.ok && status.data.status === 'confirmed') booked(status.data.summary)
    else {
      unreleased.current = null
      void navigate(`/booked/${hold.reference}`)
    }
  }

  return (
    <main className="page">
      <nav className="back" aria-label="Booking steps">
        <Link
          to={servicesUrl}
          aria-disabled={busy || undefined}
          className={busy ? 'link-disabled' : undefined}
          onClick={changeServices}
        >
          ← Change services
        </Link>
        {held && (
          <button type="button" className="link-button" disabled={busy} onClick={changeTime}>
            Change time
          </button>
        )}
      </nav>
      <h1 className="step-title">{TITLES[step.kind]}</h1>
      <p className="chosen">
        {names.join(', ')} · {formatDuration(totalMinutes(services, chosen))}
      </p>

      {policy === null ? (
        <p>Loading…</p>
      ) : !policy.ok ? (
        <div role="alert" className="error">
          <p>{"Sorry, online booking isn't available right now."}</p>
          <p>
            Please call us on <a href={`tel:${garage.phone.replace(/\s+/g, '')}`}>{garage.phone}</a>
          </p>
        </div>
      ) : step.kind === 'picking' ? (
        <TimePicker
          initialNotice={step.notice}
          services={chosen}
          days={bookableDays(todayInZone(now(), zone), policy.data.booking_window_days, hours)}
          zone={zone}
          onHeld={(hold) => {
            unreleased.current = hold
            setStep({ kind: 'details', hold })
          }}
        />
      ) : step.kind === 'details' ? (
        <DetailsForm
          key={step.hold.reference}
          hold={step.hold}
          zone={zone}
          values={details}
          onValuesChange={setDetails}
          onSubmittingChange={setBusy}
          onExpired={() => {
            unreleased.current = null // the server has already let it go
            setStep({ kind: 'picking', notice: RAN_OUT })
          }}
          onCheckout={(checkout) => {
            setBusy(false)
            setStep({ kind: 'paying', hold: step.hold, checkout })
          }}
          onAlreadyPaid={() => void alreadyPaid(step.hold)}
        />
      ) : (
        <PaymentStep
          key={step.hold.reference}
          hold={step.hold}
          checkout={step.checkout}
          payment={policy.data.payment}
          zone={zone}
          garage={garage}
          details={details}
          onBooked={booked}
          onSettled={(status) => afterRelease(status, NOT_CHARGED, step.hold.reference)}
          onTimeUp={() => void settle(NOT_CHARGED)}
          onBusyChange={setBusy}
        />
      )}
    </main>
  )
}
