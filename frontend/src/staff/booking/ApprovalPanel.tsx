import { useState } from 'react'
import type { JSX } from 'react'
import { approveBooking, conflictDetail, declineBooking } from '../api.ts'
import type { StaffResult } from '../api.ts'
import { FAILED } from '../labels.ts'
import type { StaffBooking } from '../types.ts'

const TOO_SOON_TO_APPROVE = 'Too soon for the customer to pay — propose a later time'
const LAPSED = 'This request has lapsed, so its time has been released.'

type Props = {
  booking: StaffBooking
  /** Done: the page shows the booking as it is now, with `notice` saying what happened. */
  onDone: (booking: StaffBooking, notice: string) => void
  /** The booking can't take this any more: the page reloads it. */
  onStale: () => void
  onClose: () => void
}

/** What to tell staff when approving or declining didn't go through, or null to reload. */
function refusal(result: StaffResult<StaffBooking>): string | null {
  if (result.ok || result.kind === 'unauthorised') return FAILED
  if (result.kind !== 'conflict') return FAILED
  const detail = conflictDetail(result.body)
  if (detail === 'too_soon') return TOO_SOON_TO_APPROVE
  if (detail === 'expired') return LAPSED
  return null
}

/** Approve a request as asked: the customer is emailed to pay the deposit. */
export function ApprovePanel({ booking, onDone, onStale, onClose }: Props): JSX.Element {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function approve(): Promise<void> {
    setBusy(true)
    setError(null)
    const result = await approveBooking(booking.reference)
    setBusy(false)
    if (result.ok) {
      onDone(result.data, 'Approved — the customer has been emailed')
      return
    }
    if (result.kind === 'unauthorised') return
    const message = refusal(result)
    if (message === null) onStale()
    else setError(message)
  }

  return (
    <section className="staff-panel" aria-label="Approve request">
      <h2>Approve request</h2>
      <p>
        {booking.customer_email === null
          ? 'Approve this request? The customer has no email, so phone them to arrange the deposit.'
          : 'Approve this request? The customer will be emailed to pay the £20 deposit within 24 hours.'}
      </p>
      {error && (
        <p role="alert" className="staff-alert">
          {error}
        </p>
      )}
      <div className="staff-buttons">
        <button type="button" className="staff-button" disabled={busy} onClick={() => void approve()}>
          Yes, approve
        </button>
        <button type="button" className="staff-button staff-button-quiet" onClick={onClose}>
          Back
        </button>
      </div>
    </section>
  )
}

/** Turn a request down, with an optional reason for the email. Nothing was paid. */
export function DeclinePanel({ booking, onDone, onStale, onClose }: Props): JSX.Element {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function decline(): Promise<void> {
    setBusy(true)
    setError(null)
    const result = await declineBooking(booking.reference, reason.trim() ? reason.trim() : null)
    setBusy(false)
    if (result.ok) {
      onDone(result.data, 'Declined — the customer has been emailed')
      return
    }
    if (result.kind === 'unauthorised') return
    const message = refusal(result)
    if (message === null) onStale()
    else setError(message)
  }

  return (
    <section className="staff-panel" aria-label="Decline request">
      <h2>Decline request</h2>
      <p>The customer will be emailed that the garage can&apos;t take it. Nothing has been paid.</p>
      {error && (
        <p role="alert" className="staff-alert">
          {error}
        </p>
      )}
      <div className="field">
        <label htmlFor="decline-reason">Reason (optional)</label>
        <textarea
          id="decline-reason"
          maxLength={500}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </div>
      <div className="staff-buttons">
        <button type="button" className="staff-button staff-button-danger" disabled={busy} onClick={() => void decline()}>
          Decline request
        </button>
        <button type="button" className="staff-button staff-button-quiet" onClick={onClose}>
          Back
        </button>
      </div>
    </section>
  )
}
