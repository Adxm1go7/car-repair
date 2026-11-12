import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import { Link, Navigate, useLocation } from 'react-router'
import { formatDuration } from '../catalogue/format.ts'
import type { Catalogue } from '../catalogue/types.ts'
import { fetchBookingPolicy } from './api.ts'
import type { Result } from './api.ts'
import { bookableDays, todayInZone } from './days.ts'
import { formatLongDate, formatTimeRange } from './format.ts'
import { parseSelection, selectionQuery, totalMinutes } from './selection.ts'
import { TimePicker } from './TimePicker.tsx'
import type { BookingPolicy, Hold } from './types.ts'

type Step = { kind: 'picking' } | { kind: 'details'; hold: Hold }

type Props = { catalogue: Catalogue; now: () => Date }

/** Choose a time, then (next task) enter details. The chosen services come from the URL. */
export function BookPage({ catalogue, now }: Props): JSX.Element {
  const { services, hours, garage } = catalogue
  const location = useLocation()
  const [policy, setPolicy] = useState<Result<BookingPolicy> | null>(null)
  const [step, setStep] = useState<Step>({ kind: 'picking' })

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

  return (
    <main className="page">
      <p className="back">
        <Link to={`/${selectionQuery(chosen)}`}>← Change services</Link>
      </p>
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
          services={chosen}
          days={bookableDays(todayInZone(now(), zone), policy.data.booking_window_days, hours)}
          zone={zone}
          onHeld={(hold) => setStep({ kind: 'details', hold })}
        />
      ) : (
        // Replaced by the details form in the next task.
        <p className="held">
          {formatLongDate(step.hold.start, zone)}, {formatTimeRange(step.hold.start, step.hold.end, zone)}
        </p>
      )}
    </main>
  )
}
