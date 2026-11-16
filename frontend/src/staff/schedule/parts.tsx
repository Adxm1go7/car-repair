import type { CSSProperties, JSX } from 'react'
import { Link } from 'react-router'
import type { BookingStatus, ScheduleItem } from '../types.ts'
import { timeRange } from './layout.ts'
import type { ScheduleState } from './useSchedule.ts'

const STATUS_LABEL: Record<BookingStatus, string> = {
  held: 'Being booked',
  pending_approval: 'Waiting for approval',
  confirmed: 'Confirmed',
  in_progress: 'In progress',
  completed: 'Completed',
  cancelled: 'Cancelled',
  no_show: 'No show',
  expired: 'Expired',
}

type EntryProps = { item: ScheduleItem; zone: string; bayName?: string; style?: CSSProperties }

/** One booking or block. A booking opens its detail page; a held one (a customer is paying
 * right now) and a block can't be opened. */
export function ScheduleEntry({ item, zone, bayName, style }: EntryProps): JSX.Element {
  const time = timeRange(item.start, item.end, zone)
  const bay = bayName && <span className="entry-bay">{bayName}</span>
  if (item.kind === 'block') {
    return (
      <div className="entry entry-block" style={style}>
        <span className="entry-time">{time}</span>
        <strong>{item.note ? `Blocked: ${item.note}` : 'Blocked'}</strong>
        {bay}
      </div>
    )
  }
  if (item.status === 'held') {
    return (
      <div className="entry entry-held" style={style}>
        <span className="entry-time">{`${time} · ${item.registration}`}</span>
        <span>{STATUS_LABEL.held}</span>
        {bay}
      </div>
    )
  }
  return (
    <Link className={`entry entry-${item.status}`} style={style} to={`/staff/bookings/${item.reference}`}>
      <span className="entry-time">{`${time} · ${item.registration}`}</span>
      <span>{item.services.join(', ')}</span>
      <span className="entry-status">{STATUS_LABEL[item.status]}</span>
      {item.source === 'phone' && <span className="entry-note">Phone booking · no deposit</span>}
      {!item.has_email && <span className="entry-note">No email, phone only</span>}
      {bay}
    </Link>
  )
}

type HeaderProps = {
  title: string
  date: string
  previous: { label: string; to: string }
  next: { label: string; to: string }
  today: string
}

/** The date heading with previous / next / today, and the add links for that date. */
export function ScheduleHeader({ title, date, previous, next, today }: HeaderProps): JSX.Element {
  return (
    <div className="schedule-header">
      <div className="schedule-nav">
        <Link className="staff-button staff-button-quiet" to={previous.to} aria-label={previous.label}>
          ◀
        </Link>
        <h1>{title}</h1>
        <Link className="staff-button staff-button-quiet" to={next.to} aria-label={next.label}>
          ▶
        </Link>
        <Link className="staff-button staff-button-quiet" to={today}>
          Today
        </Link>
      </div>
      <div className="schedule-actions">
        <Link className="staff-button" to={`/staff/bookings/new?date=${date}`}>
          + New booking
        </Link>
        <Link className="staff-button staff-button-quiet" to={`/staff/blocks/new?date=${date}`}>
          + Block time
        </Link>
      </div>
    </div>
  )
}

/** Loading and failure messages; null once the schedule is ready. */
export function ScheduleStatus({ state, reload }: { state: ScheduleState; reload: () => void }): JSX.Element | null {
  if (state.kind === 'loading') return <p>Loading…</p>
  if (state.kind === 'failed') {
    return (
      <div role="alert" className="staff-alert">
        <p>{"Sorry, we couldn't load the schedule."}</p>
        <button type="button" className="staff-button" onClick={reload}>
          Try again
        </button>
      </div>
    )
  }
  return null
}
