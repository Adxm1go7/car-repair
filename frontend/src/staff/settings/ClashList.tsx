import type { JSX } from 'react'
import { Link } from 'react-router'
import { shortDay } from '../schedule/layout.ts'
import type { Clash } from '../types.ts'

/** "Tue 17 Nov 09:30": `start` is garage-local ISO, so its own date and time are the garage's. */
function when(start: string): string {
  return `${shortDay(start.slice(0, 10))} ${start.slice(11, 16)}`
}

/** The bookings in the way of a bay or hours change, each linking to its page, so staff can
 * call the customer, move or cancel it, and then try again. */
export function ClashList({ bookings }: { bookings: Clash[] }): JSX.Element {
  return (
    <div role="alert" className="staff-alert">
      <p>
        {bookings.length === 1
          ? 'Nothing was changed: this booking is in the way. Move or cancel it first, then try again.'
          : `Nothing was changed: these ${bookings.length} bookings are in the way. Move or cancel them first, then try again.`}
      </p>
      <ul className="clash-list" aria-label="Bookings in the way">
        {bookings.map((clash) => (
          <li key={clash.reference}>
            <Link to={`/staff/bookings/${encodeURIComponent(clash.reference)}`}>{clash.reference}</Link>
            {` · ${when(clash.start)} · ${clash.bay}`}
            {clash.held && ' · being paid for, clears in a few minutes'}
          </li>
        ))}
      </ul>
    </div>
  )
}
