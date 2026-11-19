import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { conflictDetail, declineEnquiry, fetchEnquiry } from '../api.ts'
import { ENQUIRY_HANDLED, ENQUIRY_STATUS_LABEL, FAILED, shortMoment } from '../labels.ts'
import type { StaffEnquiry } from '../types.ts'

type State = { kind: 'loading' } | { kind: 'missing' } | { kind: 'failed' } | { kind: 'ready'; enquiry: StaffEnquiry }

function telHref(phone: string): string {
  return `tel:${phone.replace(/\s+/g, '')}`
}

/** The notice another page handed over, e.g. after booking the enquiry in. */
function noticeIn(state: unknown): string | null {
  const notice = (state as { notice?: unknown } | null)?.notice
  return typeof notice === 'string' ? notice : null
}

function Handled({ enquiry }: { enquiry: StaffEnquiry }): JSX.Element | null {
  if (!enquiry.handled_at) return null
  const verb = enquiry.status === 'converted' ? 'Booked' : 'Declined'
  const who = enquiry.handled_by ?? 'someone'
  return (
    <>
      <p>{`${verb} by ${who}, ${shortMoment(enquiry.handled_at)}`}</p>
      {enquiry.decline_reason && <p>{`Reason: ${enquiry.decline_reason}`}</p>}
      {enquiry.booking_reference && (
        <p>
          Booking: <Link to={`/staff/bookings/${enquiry.booking_reference}`}>{enquiry.booking_reference}</Link>
        </p>
      )}
    </>
  )
}

function DeclinePanel({
  enquiry,
  onDeclined,
  onClose,
}: {
  enquiry: StaffEnquiry
  onDeclined: (enquiry: StaffEnquiry) => void
  onClose: () => void
}): JSX.Element {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function decline(): Promise<void> {
    setBusy(true)
    setError(null)
    const result = await declineEnquiry(enquiry.id, reason.trim() ? reason.trim() : null)
    setBusy(false)
    if (result.ok) onDeclined(result.data)
    else if (result.kind === 'conflict' && conflictDetail(result.body) === 'not_new') setError(ENQUIRY_HANDLED)
    else if (result.kind === 'error' && result.detail) setError(result.detail)
    else if (result.kind !== 'unauthorised') setError(FAILED)
  }

  return (
    <section className="staff-panel" aria-label="Decline enquiry">
      <h2>Decline enquiry</h2>
      <p>The customer will be emailed that the garage can&apos;t take it on.</p>
      {error && (
        <p role="alert" className="staff-alert">
          {error}
        </p>
      )}
      <div className="field">
        <label htmlFor="decline-reason">Reason (optional)</label>
        <textarea id="decline-reason" maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} />
      </div>
      <div className="staff-buttons">
        <button type="button" className="staff-button staff-button-danger" disabled={busy} onClick={() => void decline()}>
          Decline enquiry
        </button>
        <button type="button" className="staff-button staff-button-quiet" onClick={onClose}>
          Keep it
        </button>
      </div>
    </section>
  )
}

/** `/staff/enquiries/:id`: one enquiry, to book in or decline. */
export function EnquiryPage(): JSX.Element {
  const id = Number(useParams().id)
  const location = useLocation()
  const known = Number.isInteger(id) && id > 0
  const [state, setState] = useState<State>({ kind: known ? 'loading' : 'missing' })
  const [declining, setDeclining] = useState(false)
  const [notice, setNotice] = useState<string | null>(() => noticeIn(location.state))

  useEffect(() => {
    if (!known) return
    let cancelled = false
    void fetchEnquiry(id).then((result) => {
      if (cancelled) return
      if (result.ok) setState({ kind: 'ready', enquiry: result.data })
      else if (result.kind === 'error' && result.detail === 'No such enquiry') setState({ kind: 'missing' })
      else if (result.kind !== 'unauthorised') setState({ kind: 'failed' })
    })
    return () => {
      cancelled = true
    }
  }, [id, known])

  if (state.kind === 'loading') return <p>Loading…</p>
  if (state.kind === 'missing') return <p>No such enquiry.</p>
  if (state.kind === 'failed') {
    return (
      <p role="alert" className="staff-alert">
        {"Sorry, we couldn't load this enquiry."}
      </p>
    )
  }

  const { enquiry } = state
  return (
    <article className="booking-page">
      <h1>{`Enquiry · ${ENQUIRY_STATUS_LABEL[enquiry.status]}`}</h1>
      <div className="booking-details">
        <p className="booking-customer">
          <span>{enquiry.customer_name}</span>
          <a href={telHref(enquiry.customer_phone)}>{enquiry.customer_phone}</a>
          <span>{enquiry.customer_email}</span>
        </p>
        <p>{`${enquiry.registration} · ${enquiry.make} ${enquiry.model}`}</p>
        <p className="enquiry-description">{enquiry.description}</p>
        <p>{`Sent ${shortMoment(enquiry.created_at)}`}</p>
        <Handled enquiry={enquiry} />
      </div>
      {notice && (
        <p role="status" className="team-notice">
          {notice}
        </p>
      )}
      {!declining && enquiry.actions.length > 0 && (
        <div className="staff-buttons" role="group" aria-label="Actions">
          {enquiry.actions.includes('approve') && (
            <Link className="staff-button" to={`/staff/enquiries/${enquiry.id}/book`}>
              Approve and book
            </Link>
          )}
          {enquiry.actions.includes('decline') && (
            <button type="button" className="staff-button staff-button-danger" onClick={() => setDeclining(true)}>
              Decline
            </button>
          )}
        </div>
      )}
      {declining && (
        <DeclinePanel
          enquiry={enquiry}
          onDeclined={(declined) => {
            setDeclining(false)
            setNotice('Declined — the customer has been emailed')
            setState({ kind: 'ready', enquiry: declined })
          }}
          onClose={() => setDeclining(false)}
        />
      )}
    </article>
  )
}
