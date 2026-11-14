import type { JSX } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { formatPrice } from '../catalogue/format.ts'
import type { Garage } from '../catalogue/types.ts'
import { formatLongDate, formatTimeRange } from './format.ts'
import type { BookingSummary } from './types.ts'

function telHref(phone: string): string {
  return `tel:${phone.replace(/\s+/g, '')}`
}

/** The summary handed over by the booking page, if it is for this reference. */
function summaryFor(state: unknown, reference: string): BookingSummary | null {
  if (typeof state !== 'object' || state === null) return null
  const summary = state as Partial<BookingSummary>
  return summary.reference === reference && typeof summary.start === 'string' ? (summary as BookingSummary) : null
}

export function BookedPage({ garage }: { garage: Garage }): JSX.Element {
  const { reference = '' } = useParams()
  const summary = summaryFor(useLocation().state, reference)
  const phone = <a href={telHref(garage.phone)}>{garage.phone}</a>

  if (summary === null) {
    // Opened from a bookmark or after a refresh: the details aren't kept in the page.
    return (
      <main className="page booked">
        <h1 className="step-title">Your booking</h1>
        <p>
          Your booking reference is {reference}. Call us on {phone} if you need to change it.
        </p>
        <p>
          <Link to="/">Back to {garage.name}</Link>
        </p>
      </main>
    )
  }

  const zone = garage.timezone
  return (
    <main className="page booked">
      <h1 className="step-title">{"You're booked"}</h1>
      <p className="booked-when">
        {`${formatLongDate(summary.start, zone)}, ${formatTimeRange(summary.start, summary.end, zone)}`}
      </p>
      <ul className="booked-services">
        {summary.services.map((service) => (
          <li key={service.slug}>{service.name}</li>
        ))}
      </ul>
      <p>{`${summary.registration} · ${summary.make} ${summary.model}`}</p>
      {summary.deposit_paid_pence > 0 && (
        <p className="booked-deposit">{`Deposit paid: ${formatPrice(summary.deposit_paid_pence, null)}`}</p>
      )}
      <dl className="booked-reference">
        <dt>Reference</dt>
        <dd>{summary.reference}</dd>
      </dl>
      <p>
        {garage.address}. Need to change something? Call us on {phone}.
      </p>
      <p>
        <Link to="/">Back to {garage.name}</Link>
      </p>
    </main>
  )
}
