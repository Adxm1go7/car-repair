import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import { formatTime } from '../../booking/format.ts'
import { conflictDetail, fetchBays, fetchMoveOptions, moveBooking } from '../api.ts'
import { FAILED, callFirst, localDate } from '../labels.ts'
import { shortDay } from '../schedule/layout.ts'
import { useStaff } from '../StaffContext.ts'
import type { StaffAvailability, StaffBooking } from '../types.ts'
import { TimePickerGrid } from './TimePickerGrid.tsx'
import type { PickedSlot } from './TimePickerGrid.tsx'

const TAKEN = 'That time has just been taken'
const NO_CHANGE = 'That is the time and bay it already has.'

type Props = {
  booking: StaffBooking
  onMoved: (booking: StaffBooking) => void
  /** The booking can't be moved any more: the page reloads it. */
  onStale: () => void
  onClose: () => void
}

type Options = { date: string; options: StaffAvailability | null; failed: boolean }

/** The bays' names, for the picker, from the booking's own day (bays don't change from
 * day to day). If this fails, the picker shows "Bay <id>". */
function useBayNames(date: string): { id: number; name: string }[] {
  const [bays, setBays] = useState<{ id: number; name: string }[]>([])
  useEffect(() => {
    let cancelled = false
    void fetchBays(date).then((result) => {
      if (!cancelled && result.ok) setBays(result.data.bays)
    })
    return () => {
      cancelled = true
    }
  }, [date])
  return bays
}

export function MovePanel({ booking, onMoved, onStale, onClose }: Props): JSX.Element {
  const [date, setDate] = useState(localDate(booking.start))
  const [loaded, setLoaded] = useState<Options | null>(null)
  const [reloads, setReloads] = useState(0)
  const [picked, setPicked] = useState<PickedSlot | null>(null)
  const [reason, setReason] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bays = useBayNames(localDate(booking.start))
  const { garage } = useStaff()

  useEffect(() => {
    let cancelled = false
    void fetchMoveOptions(booking.reference, date).then((result) => {
      if (cancelled) return
      setLoaded({ date, options: result.ok ? result.data : null, failed: !result.ok })
    })
    return () => {
      cancelled = true
    }
  }, [booking.reference, date, reloads])

  const options = loaded?.date === date ? loaded.options : null
  const zone = options?.timezone ?? garage?.timezone ?? 'UTC'
  const bayName = (id: number): string => bays.find((b) => b.id === id)?.name ?? `Bay ${id}`

  function changeDate(value: string): void {
    if (!value) return
    setDate(value)
    setPicked(null)
    setError(null)
  }

  async function confirm(): Promise<void> {
    if (!picked) return
    setBusy(true)
    const result = await moveBooking(booking.reference, {
      start: picked.start,
      bay_id: picked.bayId,
      reason: reason.trim() ? reason.trim() : null,
    })
    setBusy(false)
    setConfirming(false)
    if (result.ok) {
      onMoved(result.data)
      return
    }
    if (result.kind === 'conflict') {
      const detail = conflictDetail(result.body)
      if (detail === 'not_allowed') {
        onStale()
        return
      }
      if (detail === 'taken') {
        setError(TAKEN)
        setPicked(null)
        setReloads((n) => n + 1)
        return
      }
      if (detail === 'no_change') {
        setError(NO_CHANGE)
        return
      }
    }
    if (result.kind !== 'unauthorised') setError(FAILED)
  }

  if (confirming && picked) {
    return (
      <section className="staff-panel" aria-label="Move booking">
        <h2>Move booking</h2>
        <p>{`Move to ${shortDay(date)}, ${formatTime(picked.start, zone)} · ${bayName(picked.bayId)}?`}</p>
        <p>{callFirst(booking.customer_email !== null, "They'll be emailed the new time.")}</p>
        <div className="staff-buttons">
          <button type="button" className="staff-button" disabled={busy} onClick={() => void confirm()}>
            Yes, move it
          </button>
          <button type="button" className="staff-button staff-button-quiet" onClick={() => setConfirming(false)}>
            Back
          </button>
        </div>
      </section>
    )
  }

  return (
    <section className="staff-panel" aria-label="Move booking">
      <h2>Move booking</h2>
      <div className="field">
        <label htmlFor="move-date">Date</label>
        <input id="move-date" type="date" value={date} onChange={(event) => changeDate(event.target.value)} />
      </div>
      {error && (
        <p role="alert" className="staff-alert">
          {error}
        </p>
      )}
      {loaded?.date === date && loaded.failed && (
        <p className="staff-alert">{"Sorry, we couldn't load the free times."}</p>
      )}
      {!options && !(loaded?.date === date && loaded.failed) && <p>Loading…</p>}
      {options && (
        <TimePickerGrid
          slots={options.slots}
          bays={bays}
          zone={zone}
          selected={picked}
          onPick={(start, bayId) => {
            setPicked({ start, bayId })
            setError(null)
          }}
        />
      )}
      <div className="field">
        <label htmlFor="move-reason">Reason (optional)</label>
        <textarea id="move-reason" maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} />
      </div>
      <div className="staff-buttons">
        <button type="button" className="staff-button" disabled={!picked} onClick={() => setConfirming(true)}>
          Move booking
        </button>
        <button type="button" className="staff-button staff-button-quiet" onClick={onClose}>
          Close
        </button>
      </div>
    </section>
  )
}
