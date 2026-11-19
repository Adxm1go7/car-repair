import { useState } from 'react'
import type { CSSProperties, JSX } from 'react'
import { Link } from 'react-router'
import { FAILED, NO_DEPOSIT_NOTE, NO_EMAIL, STATUS_LABEL } from '../labels.ts'
import type { ScheduleBlock, ScheduleItem } from '../types.ts'
import { removeBlock } from '../api.ts'
import { localParts, shortDay, timeRange } from './layout.ts'
import type { ScheduleState } from './useSchedule.ts'

type EntryProps = {
  item: ScheduleItem
  zone: string
  bayName?: string
  style?: CSSProperties
  /** Given, a block is a button that calls this (the day view's block panel). */
  onSelectBlock?: (block: ScheduleBlock) => void
}

function blockLabel(block: ScheduleBlock): string {
  return block.note ? `Blocked: ${block.note}` : 'Blocked'
}

/** One booking or block. A booking opens its detail page; a held one (a customer is paying
 * right now) can't be opened. */
export function ScheduleEntry({ item, zone, bayName, style, onSelectBlock }: EntryProps): JSX.Element {
  const time = timeRange(item.start, item.end, zone)
  const bay = bayName && <span className="entry-bay">{bayName}</span>
  if (item.kind === 'block') {
    const content = (
      <>
        <span className="entry-time">{time}</span>
        <strong>{blockLabel(item)}</strong>
        {bay}
      </>
    )
    return onSelectBlock ? (
      <button type="button" className="entry entry-block" style={style} onClick={() => onSelectBlock(item)}>
        {content}
      </button>
    ) : (
      <div className="entry entry-block" style={style}>
        {content}
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
      {item.source !== 'online' && <span className="entry-note">{NO_DEPOSIT_NOTE[item.source]}</span>}
      {!item.has_email && <span className="entry-note">{NO_EMAIL}</span>}
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

function hhmm(minutes: number): string {
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
}

type BlockPanelProps = {
  block: ScheduleBlock
  zone: string
  bayName: string
  onRemoved: () => void
  onClose: () => void
}

/** A block's details and Remove block, which asks first. */
export function BlockPanel({ block, zone, bayName, onRemoved, onClose }: BlockPanelProps): JSX.Element {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const start = localParts(block.start, zone)
  const end = localParts(block.end, zone)
  const when =
    start.date === end.date
      ? `${shortDay(start.date)}, ${hhmm(start.minutes)}–${hhmm(end.minutes)}`
      : `${shortDay(start.date)} ${hhmm(start.minutes)} – ${shortDay(end.date)} ${hhmm(end.minutes)}`

  async function remove(): Promise<void> {
    setBusy(true)
    const result = await removeBlock(block.block_id)
    setBusy(false)
    // Already gone (404) is as good as removed: the schedule reloads either way.
    if (result.ok || (result.kind === 'error' && result.detail === 'No such block')) onRemoved()
    else if (result.kind !== 'unauthorised') {
      setConfirming(false)
      setError(FAILED)
    }
  }

  return (
    <section className="staff-panel" aria-label="Block">
      <h2>{blockLabel(block)}</h2>
      <p>{`${when} · ${bayName}`}</p>
      {error && (
        <p role="alert" className="staff-alert">
          {error}
        </p>
      )}
      {confirming ? (
        <>
          <p>Remove this block? Its time can be booked again.</p>
          <div className="staff-buttons">
            <button type="button" className="staff-button staff-button-danger" disabled={busy} onClick={() => void remove()}>
              Yes, remove it
            </button>
            <button type="button" className="staff-button staff-button-quiet" onClick={() => setConfirming(false)}>
              Back
            </button>
          </div>
        </>
      ) : (
        <div className="staff-buttons">
          <button type="button" className="staff-button staff-button-danger" onClick={() => setConfirming(true)}>
            Remove block
          </button>
          <button type="button" className="staff-button staff-button-quiet" onClick={onClose}>
            Close
          </button>
        </div>
      )}
    </section>
  )
}
