import { useCallback, useEffect, useState } from 'react'
import type { JSX } from 'react'
import { todayInZone } from '../../booking/days.ts'
import { addDays, shortDate } from '../../catalogue/hours.ts'
import type { OpeningDay } from '../../catalogue/types.ts'
import { addTimetable, clashesOf, deleteTimetable, fetchTimetables, replaceTimetable } from '../api.ts'
import type { StaffResult } from '../api.ts'
import { useStaff } from '../StaffContext.ts'
import type { AdminTimetable, Clash } from '../types.ts'
import { ClashList } from './ClashList.tsx'
import { failure } from './shared.ts'
import { TimetableForm } from './TimetableForm.tsx'
import type { SaveOutcome } from './TimetableForm.tsx'
import { timetableLabel, weekSummary } from './week.ts'

type Loaded = { kind: 'loading' } | { kind: 'failed' } | { kind: 'loaded'; timetables: AdminTimetable[] }

const IN_FORCE = "These hours are in force now, so they can't be changed. Add new hours from a later date instead."

/** A failed save or delete as the form or row shows it: the bookings in the way, or words. */
function outcomeOf(result: StaffResult<unknown>): SaveOutcome {
  if (result.ok) return null
  if (result.kind === 'conflict') {
    const clashes = clashesOf(result.body)
    if (clashes) return { clashes }
    if ((result.body as { detail?: unknown } | null)?.detail === 'not_allowed') return { error: IN_FORCE }
  }
  return { error: failure(result) ?? '' }
}

function byDate(timetables: AdminTimetable[]): AdminTimetable[] {
  return [...timetables].sort((a, b) => a.starts_on.localeCompare(b.starts_on))
}

type RowProps = {
  timetable: AdminTimetable
  timetables: AdminTimetable[]
  earliest: string
  onSaved: (timetable: AdminTimetable) => void
  onDeleted: (timetable: AdminTimetable) => void
}

function TimetableRow({ timetable, timetables, earliest, onSaved, onDeleted }: RowProps): JSX.Element {
  const [editing, setEditing] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [clashes, setClashes] = useState<Clash[] | null>(null)
  const label = timetableLabel(timetable)

  async function save(_startsOn: string, days: OpeningDay[]): Promise<SaveOutcome> {
    const result = await replaceTimetable(timetable.id, days)
    if (!result.ok) return outcomeOf(result)
    setEditing(false)
    onSaved(result.data)
    return null
  }

  async function remove(): Promise<void> {
    setBusy(true)
    const result = await deleteTimetable(timetable.id)
    setBusy(false)
    setConfirmingDelete(false)
    if (result.ok) {
      onDeleted(timetable)
      return
    }
    const outcome = outcomeOf(result)
    if (outcome && 'clashes' in outcome) setClashes(outcome.clashes)
    else if (outcome) setError(outcome.error)
  }

  function askDelete(): void {
    setError(null)
    setClashes(null)
    setConfirmingDelete(true)
  }

  return (
    <li className="hours-row" aria-label={label}>
      <span className="settings-name">{label}</span>
      <span className="hours-summary">{weekSummary(timetable.days)}</span>
      {timetable.state === 'future' && !editing && (
        <div className="staff-buttons">
          <button type="button" className="staff-button staff-button-quiet" onClick={() => setEditing(true)}>
            Edit
          </button>
          <button type="button" className="staff-button staff-button-quiet" onClick={askDelete}>
            Delete
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="staff-alert">
          {error}
        </p>
      )}
      {clashes && <ClashList bookings={clashes} />}
      {confirmingDelete && (
        <div className="staff-panel">
          <p>{`Delete the hours from ${shortDate(timetable.starts_on)}? The hours before carry on over those dates.`}</p>
          <div className="staff-buttons">
            <button type="button" className="staff-button staff-button-danger" disabled={busy} onClick={() => void remove()}>
              Yes, delete
            </button>
            <button type="button" className="staff-button staff-button-quiet" onClick={() => setConfirmingDelete(false)}>
              Back
            </button>
          </div>
        </div>
      )}
      {editing && (
        <TimetableForm
          mode="edit"
          timetable={timetable}
          timetables={timetables}
          earliest={earliest}
          onSave={save}
          onCancel={() => setEditing(false)}
        />
      )}
    </li>
  )
}

/** The Hours tab: every timetable, oldest first. Only future ones can be edited or deleted;
 * to change today's hours, add new hours from tomorrow or later. */
export function HoursTab(): JSX.Element {
  const { garage } = useStaff()
  const [state, setState] = useState<Loaded>({ kind: 'loading' })
  const [adding, setAdding] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  // The server checks this too; it only sets the date picker's first day.
  const earliest = addDays(todayInZone(new Date(), garage?.timezone ?? 'Europe/London'), 1)

  const show = useCallback((result: StaffResult<AdminTimetable[]>): void => {
    if (result.ok) setState({ kind: 'loaded', timetables: result.data })
    else if (result.kind !== 'unauthorised') setState({ kind: 'failed' })
  }, [])

  useEffect(() => {
    let cancelled = false
    void fetchTimetables().then((result) => {
      if (!cancelled) show(result)
    })
    return () => {
      cancelled = true
    }
  }, [show])

  async function retry(): Promise<void> {
    setState({ kind: 'loading' })
    show(await fetchTimetables())
  }

  function update(change: (timetables: AdminTimetable[]) => AdminTimetable[]): void {
    setState((current) =>
      current.kind === 'loaded' ? { kind: 'loaded', timetables: byDate(change(current.timetables)) } : current,
    )
  }

  async function add(startsOn: string, days: OpeningDay[]): Promise<SaveOutcome> {
    const result = await addTimetable(startsOn, days)
    if (!result.ok) return outcomeOf(result)
    setAdding(false)
    update((timetables) => [...timetables, result.data])
    setNotice(`New hours from ${shortDate(result.data.starts_on)} saved`)
    return null
  }

  function saved(timetable: AdminTimetable): void {
    update((timetables) => timetables.map((t) => (t.id === timetable.id ? timetable : t)))
    setNotice(`Saved the hours from ${shortDate(timetable.starts_on)}`)
  }

  function deleted(timetable: AdminTimetable): void {
    update((timetables) => timetables.filter((t) => t.id !== timetable.id))
    setNotice(`Deleted the hours from ${shortDate(timetable.starts_on)}`)
  }

  const timetables = state.kind === 'loaded' ? state.timetables : []
  return (
    <section className="settings-tab" aria-labelledby="hours-heading">
      <div className="settings-heading">
        <h2 id="hours-heading">Hours</h2>
        {state.kind === 'loaded' && !adding && (
          <button type="button" className="staff-button" onClick={() => setAdding(true)}>
            + New hours from a date
          </button>
        )}
      </div>
      <p role="status" className="team-notice">
        {notice}
      </p>
      {state.kind === 'loading' && <p>Loading…</p>}
      {state.kind === 'failed' && (
        <>
          <p role="alert" className="staff-alert">
            {"Sorry, we couldn't load the opening hours."}
          </p>
          <button type="button" className="staff-button" onClick={() => void retry()}>
            Try again
          </button>
        </>
      )}
      {adding && (
        <TimetableForm
          mode="new"
          timetables={timetables}
          earliest={earliest}
          onSave={add}
          onCancel={() => setAdding(false)}
        />
      )}
      {state.kind === 'loaded' && (
        <ul className="settings-list" aria-label="Hours">
          {timetables.map((timetable) => (
            <TimetableRow
              key={timetable.id}
              timetable={timetable}
              timetables={timetables}
              earliest={earliest}
              onSaved={saved}
              onDeleted={deleted}
            />
          ))}
        </ul>
      )}
    </section>
  )
}
