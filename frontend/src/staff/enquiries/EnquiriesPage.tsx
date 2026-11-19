import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import { Link, useSearchParams } from 'react-router'
import { fetchEnquiries } from '../api.ts'
import { shortMoment } from '../labels.ts'
import type { EnquiryStatus, StaffEnquiryRow } from '../types.ts'

type State =
  | { kind: 'loading'; status: EnquiryStatus }
  | { kind: 'failed'; status: EnquiryStatus }
  | { kind: 'ready'; status: EnquiryStatus; rows: StaffEnquiryRow[] }

const TABS: { status: EnquiryStatus; label: string; empty: string }[] = [
  { status: 'new', label: 'New', empty: 'No new enquiries.' },
  { status: 'converted', label: 'Booked', empty: 'No booked enquiries.' },
  { status: 'declined', label: 'Declined', empty: 'No declined enquiries.' },
]

function statusIn(value: string | null): EnquiryStatus {
  return TABS.find((tab) => tab.status === value)?.status ?? 'new'
}

/** `/staff/enquiries?status=`: new enquiries to answer, and the ones already booked or declined. */
export function EnquiriesPage(): JSX.Element {
  const [params, setParams] = useSearchParams()
  const status = statusIn(params.get('status'))
  const [state, setState] = useState<State>({ kind: 'loading', status })

  useEffect(() => {
    let cancelled = false
    void fetchEnquiries(status).then((result) => {
      if (cancelled) return
      if (result.ok) setState({ kind: 'ready', status, rows: result.data })
      else if (result.kind !== 'unauthorised') setState({ kind: 'failed', status })
    })
    return () => {
      cancelled = true
    }
  }, [status])

  const current = state.status === status ? state : { kind: 'loading' as const, status }
  const tab = TABS.find((t) => t.status === status) ?? TABS[0]

  return (
    <section className="requests-page">
      <h1>Enquiries</h1>
      <p className="staff-hint">
        Customers describing a problem. Phone them if you need to know more, then book them in or decline.
      </p>
      <div className="enquiry-tabs" role="tablist" aria-label="Which enquiries">
        {TABS.map((t) => (
          <button
            key={t.status}
            type="button"
            role="tab"
            className="staff-button staff-button-quiet"
            aria-selected={t.status === status}
            onClick={() => setParams(t.status === 'new' ? {} : { status: t.status })}
          >
            {t.label}
          </button>
        ))}
      </div>
      {current.kind === 'loading' && <p>Loading…</p>}
      {current.kind === 'failed' && (
        <p role="alert" className="staff-alert">
          {"Sorry, we couldn't load the enquiries."}
        </p>
      )}
      {current.kind === 'ready' && current.rows.length === 0 && <p>{tab.empty}</p>}
      {current.kind === 'ready' && current.rows.length > 0 && (
        <ul className="requests-list" aria-label="Enquiries">
          {current.rows.map((row) => (
            <li key={row.id} className="requests-row">
              <Link to={`/staff/enquiries/${row.id}`}>{row.customer_name}</Link>
              <span>{`${row.registration} · ${row.make} ${row.model}`}</span>
              <span>{row.summary}</span>
              <span>{`Sent ${shortMoment(row.created_at)}`}</span>
              {row.handled_at && <span className="requests-deadline">{`Handled ${shortMoment(row.handled_at)}`}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
