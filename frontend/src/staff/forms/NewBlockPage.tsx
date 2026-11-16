import { useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { todayInZone } from '../../booking/days.ts'
import { createBlock } from '../api.ts'
import type { BlockClashes } from '../api.ts'
import { FAILED, localDate, localTime } from '../labels.ts'
import { shortDay, validDate, zonedIso } from '../schedule/layout.ts'
import { useStaff } from '../StaffContext.ts'
import { useBays } from '../useBays.ts'

const NOTE_REQUIRED = 'Please say what the block is for'
const END_FIRST = 'The end must be after the start'
const TIME = /^\d{2}:\d{2}$/

function Clashes({ clashes }: { clashes: BlockClashes }): JSX.Element {
  return (
    <div role="alert" className="staff-alert">
      {clashes.bookings.length > 0 && (
        <>
          <p>These bookings are in the way:</p>
          <ul className="clash-list">
            {clashes.bookings.map((booking) => (
              <li key={booking.reference}>
                <Link to={`/staff/bookings/${booking.reference}`}>
                  {`${booking.reference} · ${shortDay(localDate(booking.start))} ${localTime(booking.start)} · ${booking.bay}`}
                </Link>
              </li>
            ))}
          </ul>
          <p>Call these customers and move or cancel their bookings first.</p>
          <p>A booking being paid for right now clears in a few minutes if it isn&apos;t finished.</p>
        </>
      )}
      {clashes.blocks.length > 0 && (
        <ul className="clash-list">
          {clashes.blocks.map((block) => (
            <li key={block.id}>{`Already blocked: ${block.note}`}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** `/staff/blocks/new?date=&bay=`: block one bay or all of them, for any length up to 31 days. */
export function NewBlockPage(): JSX.Element {
  const navigate = useNavigate()
  const { garage } = useStaff()
  const [params] = useSearchParams()
  const first = validDate(params.get('date')) ?? todayInZone(new Date(), garage?.timezone ?? 'UTC')
  const bays = useBays(first)
  const [bayId, setBayId] = useState(params.get('bay') ?? '')
  const [startDate, setStartDate] = useState(first)
  const [startTime, setStartTime] = useState('08:00')
  const [endDate, setEndDate] = useState(first)
  const [endTime, setEndTime] = useState('17:30')
  const [note, setNote] = useState('')
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [clashes, setClashes] = useState<BlockClashes | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    setMessage(null)
    setClashes(null)
    if (note.trim() === '') {
      setFieldError(NOTE_REQUIRED)
      return
    }
    if (!validDate(startDate) || !validDate(endDate) || !TIME.test(startTime) || !TIME.test(endTime)) {
      setFieldError('Please enter the start and end dates and times')
      return
    }
    if (!garage) {
      // Times are the garage's local time, so its time zone must be known first.
      setMessage('Still loading the garage details. Please try again.')
      return
    }
    const start = zonedIso(startDate, startTime, garage.timezone)
    const end = zonedIso(endDate, endTime, garage.timezone)
    if (end <= start) {
      setFieldError(END_FIRST)
      return
    }
    setFieldError(null)

    setBusy(true)
    const result = await createBlock({ bay_id: bayId === '' ? null : Number(bayId), start, end, note: note.trim() })
    setBusy(false)
    if (result.ok) {
      void navigate(`/staff?date=${startDate}`)
      return
    }
    if (result.kind === 'conflict') setClashes(result.body as BlockClashes)
    else if (result.kind === 'error' && result.detail) setMessage(result.detail)
    else if (result.kind !== 'unauthorised') setMessage(FAILED)
  }

  return (
    <form className="staff-form booking-form" onSubmit={(event) => void submit(event)} noValidate>
      <h1>Block time</h1>
      <div className="field">
        <label htmlFor="block-bay">Bay</label>
        <select id="block-bay" value={bayId} onChange={(event) => setBayId(event.target.value)}>
          <option value="">All bays</option>
          {bays.map((bay) => (
            <option key={bay.id} value={String(bay.id)}>
              {bay.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field-pair">
        <div className="field">
          <label htmlFor="block-start-date">Start date</label>
          <input id="block-start-date" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="block-start-time">Start time</label>
          <input id="block-start-time" type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} />
        </div>
      </div>
      <div className="field-pair">
        <div className="field">
          <label htmlFor="block-end-date">End date</label>
          <input id="block-end-date" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="block-end-time">End time</label>
          <input id="block-end-time" type="time" value={endTime} onChange={(event) => setEndTime(event.target.value)} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="block-note">Note</label>
        <input
          id="block-note"
          maxLength={200}
          placeholder="Holiday, Lift broken…"
          aria-invalid={fieldError === NOTE_REQUIRED ? true : undefined}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </div>
      {fieldError && <p className="field-error">{fieldError}</p>}
      {message && (
        <p role="alert" className="staff-alert">
          {message}
        </p>
      )}
      {clashes && <Clashes clashes={clashes} />}
      <button type="submit" className="staff-button" disabled={busy}>
        Block time
      </button>
    </form>
  )
}
