import { useState } from 'react'
import type { JSX } from 'react'
import { cancelStaffBooking, conflictDetail } from '../api.ts'
import { callFirst } from '../labels.ts'
import type { StaffBooking } from '../types.ts'

const UNAVAILABLE = "We couldn't cancel just now. Please try again."

type Props = {
  booking: StaffBooking
  onCancelled: (booking: StaffBooking) => void
  /** The booking can't be cancelled any more: the page reloads it. */
  onStale: () => void
  onClose: () => void
}

export function CancelPanel({ booking, onCancelled, onStale, onClose }: Props): JSX.Element {
  const [reason, setReason] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const refunded = booking.deposit_status === 'paid'

  async function confirm(): Promise<void> {
    setBusy(true)
    const result = await cancelStaffBooking(booking.reference, reason.trim() ? reason.trim() : null)
    setBusy(false)
    setConfirming(false)
    if (result.ok) {
      onCancelled(result.data)
      return
    }
    if (result.kind === 'conflict' && conflictDetail(result.body) === 'not_allowed') {
      onStale()
      return
    }
    // Stripe unreachable (503) or anything else: nothing changed, so it can be tried again.
    if (result.kind !== 'unauthorised') setError(UNAVAILABLE)
  }

  if (confirming) {
    return (
      <section className="staff-panel" aria-label="Cancel booking">
        <h2>Cancel booking</h2>
        <p>
          {callFirst(
            booking.customer_email !== null,
            refunded ? "They'll be emailed, and their deposit refunded." : "They'll be emailed.",
          )}
        </p>
        <div className="staff-buttons">
          <button type="button" className="staff-button staff-button-danger" disabled={busy} onClick={() => void confirm()}>
            Yes, cancel it
          </button>
          <button type="button" className="staff-button staff-button-quiet" onClick={() => setConfirming(false)}>
            Back
          </button>
        </div>
      </section>
    )
  }

  return (
    <section className="staff-panel" aria-label="Cancel booking">
      <h2>Cancel booking</h2>
      {error && (
        <p role="alert" className="staff-alert">
          {error}
        </p>
      )}
      <div className="field">
        <label htmlFor="cancel-reason">Reason (optional)</label>
        <textarea id="cancel-reason" maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} />
      </div>
      <div className="staff-buttons">
        <button type="button" className="staff-button staff-button-danger" onClick={() => setConfirming(true)}>
          Cancel this booking
        </button>
        <button type="button" className="staff-button staff-button-quiet" onClick={onClose}>
          Close
        </button>
      </div>
    </section>
  )
}
