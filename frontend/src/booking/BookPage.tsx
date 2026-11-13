import { useEffect, useRef, useState } from 'react'
import type { JSX, RefObject } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'
import { formatDuration } from '../catalogue/format.ts'
import type { Catalogue } from '../catalogue/types.ts'
import { cancelHold, fetchBookingPolicy } from './api.ts'
import type { Result } from './api.ts'
import { bookableDays, todayInZone } from './days.ts'
import { DetailsForm } from './DetailsForm.tsx'
import { parseSelection, selectionQuery, totalMinutes } from './selection.ts'
import { TimePicker } from './TimePicker.tsx'
import type { BookingPolicy, CustomerDetails, Hold } from './types.ts'

type Step = { kind: 'picking'; notice?: string } | { kind: 'details'; hold: Hold }

const RAN_OUT = 'Your hold ran out, so we released that time.'

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

/** Choose a time, then enter details. The chosen services come from the URL. */
export function BookPage({ catalogue, now }: Props): JSX.Element {
  const { services, hours, garage } = catalogue
  const location = useLocation()
  const [policy, setPolicy] = useState<Result<BookingPolicy> | null>(null)
  const [step, setStep] = useState<Step>({ kind: 'picking' })
  // What the customer typed. It lives here, not in the form, so it survives changing time
  // and a hold running out. Changing services leaves this page, which drops it.
  const [details, setDetails] = useState<CustomerDetails>(EMPTY_DETAILS)
  const [submitting, setSubmitting] = useState(false)
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
  const held = step.kind === 'details' ? step.hold : null

  function release(): void {
    releaseHold(unreleased)
  }

  function changeTime(): void {
    release()
    setStep({ kind: 'picking' })
  }

  return (
    <main className="page">
      <nav className="back" aria-label="Booking steps">
        <Link
          to={`/${selectionQuery(chosen)}`}
          aria-disabled={submitting || undefined}
          className={submitting ? 'link-disabled' : undefined}
          onClick={(event) => {
            // Mid-confirm the booking may already be made: stay until the reply decides.
            if (submitting) event.preventDefault()
            else release()
          }}
        >
          ← Change services
        </Link>
        {held && (
          <button type="button" className="link-button" disabled={submitting} onClick={changeTime}>
            Change time
          </button>
        )}
      </nav>
      <h1 className="step-title">{step.kind === 'picking' ? 'Choose a time' : 'Your details'}</h1>
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
      ) : (
        <DetailsForm
          key={step.hold.reference}
          hold={step.hold}
          zone={zone}
          values={details}
          onValuesChange={setDetails}
          onSubmittingChange={setSubmitting}
          onExpired={() => {
            unreleased.current = null // the server has already let it go
            setStep({ kind: 'picking', notice: RAN_OUT })
          }}
          onBooked={(summary) => {
            unreleased.current = null // booked: never give it back
            void navigate(`/booked/${summary.reference}`, { state: summary })
          }}
        />
      )}
    </main>
  )
}
