import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import { Link } from 'react-router'
import { fetchRequests } from '../api.ts'
import { localDate, localTime } from '../labels.ts'
import { shortDay } from '../schedule/layout.ts'
import type { StaffRequest } from '../types.ts'

type State = { kind: 'loading' } | { kind: 'failed' } | { kind: 'ready'; requests: StaffRequest[] }

/** "Wed 18 Nov, 09:00" for a garage-local ISO time. */
function shortMoment(iso: string): string {
  return `${shortDay(localDate(iso))}, ${localTime(iso)}`
}

/** `/staff/requests`: online requests waiting for an answer, oldest first. */
export function RequestsPage(): JSX.Element {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    void fetchRequests().then((result) => {
      if (cancelled) return
      if (result.ok) setState({ kind: 'ready', requests: result.data })
      else if (result.kind !== 'unauthorised') setState({ kind: 'failed' })
    })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="requests-page">
      <h1>Requests</h1>
      <p className="staff-hint">
        Online bookings that need approval. Approve one, propose another time after phoning the customer, or decline it.
      </p>
      {state.kind === 'loading' && <p>Loading…</p>}
      {state.kind === 'failed' && (
        <p role="alert" className="staff-alert">
          {"Sorry, we couldn't load the requests."}
        </p>
      )}
      {state.kind === 'ready' && state.requests.length === 0 && <p>No requests waiting.</p>}
      {state.kind === 'ready' && state.requests.length > 0 && (
        <ul className="requests-list" aria-label="Requests">
          {state.requests.map((request) => (
            <li key={request.reference} className="requests-row">
              <Link to={`/staff/bookings/${request.reference}`}>{request.reference}</Link>
              <span>{request.customer_name}</span>
              <span>{request.services.join(', ')}</span>
              <span>{`${shortMoment(request.start)} · ${request.bay}`}</span>
              <span className="requests-deadline">{`Reply by ${shortMoment(request.deadline)}`}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
