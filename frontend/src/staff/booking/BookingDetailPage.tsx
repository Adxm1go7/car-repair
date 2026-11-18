import { useCallback, useEffect, useState } from 'react'
import type { JSX } from 'react'
import { Link, useParams } from 'react-router'
import { calendarNoon } from '../../booking/days.ts'
import { changeStatus, conflictDetail, fetchStaffBooking } from '../api.ts'
import type { StaffResult } from '../api.ts'
import { ACTION_LABEL, DEPOSIT_LABEL, FAILED, NO_EMAIL, STALE, STATUS_LABEL, localDate, localTime } from '../labels.ts'
import { shortDay } from '../schedule/layout.ts'
import type { BookingAction, StaffBooking, StatusAction } from '../types.ts'
import { CancelPanel } from './CancelPanel.tsx'
import { MovePanel } from './MovePanel.tsx'

const NOT_FOUND = 'No such booking' // the API's 404 detail

type PageState = { kind: 'loading' } | { kind: 'missing' } | { kind: 'failed' } | { kind: 'ready'; booking: StaffBooking }
type Panel = null | 'move' | 'cancel' | 'confirm-start'

function telHref(phone: string): string {
  return `tel:${phone.replace(/\s+/g, '')}`
}

/** "16 Nov 14:02" for a garage-local ISO time. */
function historyTime(iso: string): string {
  const day = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'short' }).format(
    calendarNoon(localDate(iso)),
  )
  return `${day} ${localTime(iso)}`
}

function Details({ booking }: { booking: StaffBooking }): JSX.Element {
  const car = [booking.make, booking.model].filter(Boolean).join(' ')
  return (
    <div className="booking-details">
      <p className="booking-when">
        {`${shortDay(localDate(booking.start))}, ${localTime(booking.start)} – ${localTime(booking.end)} · ${booking.bay.name}`}
      </p>
      <p>{booking.services.join(', ')}</p>
      {booking.registration && <p>{car ? `${booking.registration} · ${car}` : booking.registration}</p>}
      <p className="booking-customer">
        {booking.customer_name && <span>{booking.customer_name}</span>}
        {booking.customer_phone && <a href={telHref(booking.customer_phone)}>{booking.customer_phone}</a>}
        <span>{booking.customer_email ?? NO_EMAIL}</span>
      </p>
      {booking.notes && <p>{`Notes: "${booking.notes}"`}</p>}
      <p>{DEPOSIT_LABEL[booking.deposit_status]}</p>
    </div>
  )
}

function History({ booking }: { booking: StaffBooking }): JSX.Element | null {
  if (booking.history.length === 0) return null
  return (
    <section>
      <h2 id="history-heading">History</h2>
      <ol className="booking-history" aria-labelledby="history-heading">
        {booking.history.map((entry, i) => (
          <li key={`${entry.at}-${i}`}>
            <time dateTime={entry.at}>{historyTime(entry.at)}</time>
            <span>{entry.text}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}

/** `/staff/bookings/:reference`: the booking, the buttons its status allows, and its history. */
export function BookingDetailPage(): JSX.Element {
  const { reference = '' } = useParams()
  const [state, setState] = useState<PageState>({ kind: 'loading' })
  const [panel, setPanel] = useState<Panel>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const show = useCallback((result: StaffResult<StaffBooking>): void => {
    if (result.ok) setState({ kind: 'ready', booking: result.data })
    else if (result.kind === 'error' && result.detail === NOT_FOUND) setState({ kind: 'missing' })
    else if (result.kind !== 'unauthorised') setState({ kind: 'failed' })
  }, [])

  const load = useCallback(async (): Promise<void> => show(await fetchStaffBooking(reference)), [reference, show])

  useEffect(() => {
    let cancelled = false
    void fetchStaffBooking(reference).then((result) => {
      if (!cancelled) show(result)
    })
    return () => {
      cancelled = true
    }
  }, [reference, show])

  function updated(booking: StaffBooking): void {
    setState({ kind: 'ready', booking })
    setPanel(null)
    setMessage(null)
  }

  function stale(): void {
    setPanel(null)
    setMessage(STALE)
    void load()
  }

  async function runStatus(action: StatusAction): Promise<void> {
    setPanel(null)
    setBusy(true)
    const result = await changeStatus(reference, action)
    setBusy(false)
    if (result.ok) updated(result.data)
    else if (result.kind === 'conflict' && conflictDetail(result.body) === 'not_allowed') stale()
    else if (result.kind !== 'unauthorised') setMessage(FAILED)
  }

  function press(booking: StaffBooking, action: BookingAction): void {
    setMessage(null)
    if (action === 'move' || action === 'cancel') setPanel(action)
    else if (action === 'start' && booking.starts_on_another_day) setPanel('confirm-start')
    else void runStatus(action)
  }

  if (state.kind === 'loading') return <p>Loading…</p>
  if (state.kind === 'missing' || state.kind === 'failed') {
    return (
      <div role="alert" className="staff-alert">
        <p>{state.kind === 'missing' ? "Sorry, we couldn't find that booking." : "Sorry, we couldn't load this booking."}</p>
        <Link to="/staff">Back to the day view</Link>
      </div>
    )
  }

  const { booking } = state
  return (
    <article className="booking-page">
      <h1>{`${booking.reference} · ${STATUS_LABEL[booking.status]}`}</h1>
      <Details booking={booking} />
      {message && (
        <p role="alert" className="staff-alert">
          {message}
        </p>
      )}
      {panel === null && booking.actions.length > 0 && (
        <div className="staff-buttons" role="group" aria-label="Actions">
          {booking.actions.map((action) => (
            <button
              key={action}
              type="button"
              className={action === 'cancel' ? 'staff-button staff-button-danger' : 'staff-button'}
              disabled={busy}
              onClick={() => press(booking, action)}
            >
              {ACTION_LABEL[action]}
            </button>
          ))}
        </div>
      )}
      {panel === 'confirm-start' && (
        <section className="staff-panel" aria-label="Start job">
          <p>{`This job is booked for ${shortDay(localDate(booking.start))}. Start it now?`}</p>
          <div className="staff-buttons">
            <button type="button" className="staff-button" onClick={() => void runStatus('start')}>
              Yes, start it
            </button>
            <button type="button" className="staff-button staff-button-quiet" onClick={() => setPanel(null)}>
              Not now
            </button>
          </div>
        </section>
      )}
      {panel === 'move' && (
        <MovePanel booking={booking} onMoved={updated} onStale={stale} onClose={() => setPanel(null)} />
      )}
      {panel === 'cancel' && (
        <CancelPanel booking={booking} onCancelled={updated} onStale={stale} onClose={() => setPanel(null)} />
      )}
      <History booking={booking} />
    </article>
  )
}
