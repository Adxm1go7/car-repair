import { useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { addDays, shortDate } from '../../catalogue/hours.ts'
import type { OpeningDay } from '../../catalogue/types.ts'
import type { AdminTimetable, Clash } from '../types.ts'
import { ClashList } from './ClashList.tsx'
import { DAY_NAMES } from './week.ts'

/** One weekday while it's being edited. Times are kept while the day is closed, so ticking
 * it open again brings them back. */
type DayDraft = { weekday: number; open: boolean; opens: string; closes: string; breaks: { start: string; end: string }[] }

/** What saving came to: null once saved, or what to show. */
export type SaveOutcome = null | { error: string } | { clashes: Clash[] }

type Props = {
  /** 'new' asks for a start date and prefills the week from the hours in force the day before. */
  mode: 'new' | 'edit'
  timetable?: AdminTimetable
  timetables: AdminTimetable[]
  /** Tomorrow in the garage's time zone: new hours can't start sooner. */
  earliest: string
  onSave: (startsOn: string, days: OpeningDay[]) => Promise<SaveOutcome>
  onCancel: () => void
}

function draftsOf(days: OpeningDay[]): DayDraft[] {
  return DAY_NAMES.map((_, weekday) => {
    const day = days.find((d) => d.weekday === weekday)
    const open = Boolean(day?.open && day.close)
    return {
      weekday,
      open,
      opens: day?.open ?? '09:00',
      closes: day?.close ?? '17:00',
      breaks: open && day ? day.breaks.map((b) => ({ ...b })) : [],
    }
  })
}

function daysOf(drafts: DayDraft[]): OpeningDay[] {
  return drafts.map((d) =>
    d.open
      ? {
          weekday: d.weekday,
          open: d.opens,
          close: d.closes,
          breaks: [...d.breaks].sort((a, b) => a.start.localeCompare(b.start)),
        }
      : { weekday: d.weekday, open: null, close: null, breaks: [] },
  )
}

/** The week in force the day before `date` (the timetable a new one would follow). */
function weekBefore(timetables: AdminTimetable[], date: string): OpeningDay[] {
  const before = addDays(date, -1)
  return timetables.filter((t) => t.starts_on <= before).at(-1)?.days ?? []
}

/** What's wrong with the week, one line per day. Times are "HH:MM", so text order is time order. */
function problems(drafts: DayDraft[]): string[] {
  const found: string[] = []
  for (const day of drafts) {
    if (!day.open) continue
    const name = DAY_NAMES[day.weekday]
    if (!day.opens || !day.closes || day.opens >= day.closes) {
      found.push(`${name}: opening must be before closing`)
      continue
    }
    let previousEnd = day.opens
    for (const b of [...day.breaks].sort((x, y) => x.start.localeCompare(y.start))) {
      if (!b.start || !b.end || b.start >= b.end || b.start < previousEnd || b.end > day.closes) {
        found.push(`${name}: breaks must be inside the hours and not overlap`)
        break
      }
      previousEnd = b.end
    }
  }
  return found
}

/** New hours from a date, or a future timetable's week edited. Saving asks to confirm. */
export function TimetableForm({ mode, timetable, timetables, earliest, onSave, onCancel }: Props): JSX.Element {
  const [startsOn, setStartsOn] = useState(timetable?.starts_on ?? '')
  const [drafts, setDrafts] = useState<DayDraft[] | null>(timetable ? draftsOf(timetable.days) : null)
  const [touched, setTouched] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [confirming, setConfirming] = useState(false)
  const [outcome, setOutcome] = useState<SaveOutcome>(null)
  const [busy, setBusy] = useState(false)
  const id = `hours-${timetable?.id ?? 'new'}`

  function chooseDate(date: string): void {
    setStartsOn(date)
    setConfirming(false)
    // Prefill until the admin changes a day: after that, a new date keeps their week.
    if (date && !touched) setDrafts(draftsOf(weekBefore(timetables, date)))
  }

  function change(weekday: number, edit: (day: DayDraft) => DayDraft): void {
    setTouched(true)
    setConfirming(false)
    setDrafts((current) => current && current.map((day) => (day.weekday === weekday ? edit(day) : day)))
  }

  function submit(event: FormEvent): void {
    event.preventDefault()
    setOutcome(null)
    const found: string[] = []
    if (mode === 'new' && !startsOn) found.push('Please choose the date the new hours start')
    else if (mode === 'new' && startsOn < earliest) found.push('New hours can start tomorrow at the earliest')
    if (drafts) found.push(...problems(drafts))
    setErrors(found)
    setConfirming(found.length === 0 && drafts !== null)
  }

  async function save(): Promise<void> {
    if (!drafts) return
    setBusy(true)
    const result = await onSave(startsOn, daysOf(drafts))
    setBusy(false)
    setConfirming(false)
    setOutcome(result)
  }

  const title = mode === 'new' ? 'New hours' : `Edit hours from ${shortDate(startsOn)}`
  return (
    <form className="staff-form settings-form" aria-label={title} onSubmit={submit} noValidate>
      <h3>{title}</h3>
      {mode === 'new' && (
        <div className="field">
          <label htmlFor={`${id}-starts`}>Starts on</label>
          <input
            id={`${id}-starts`}
            type="date"
            min={earliest}
            value={startsOn}
            onChange={(event) => chooseDate(event.target.value)}
          />
          <span className="staff-hint">
            Tomorrow at the earliest. The week starts as a copy of the hours before that date.
          </span>
        </div>
      )}
      {drafts && (
        <div className="hours-week">
          {drafts.map((day) => {
            const name = DAY_NAMES[day.weekday]
            return (
              <fieldset key={day.weekday} className="hours-day">
                <legend>{name}</legend>
                <label className="hours-open">
                  <input
                    type="checkbox"
                    checked={day.open}
                    aria-label={`Open on ${name}`}
                    onChange={(event) => change(day.weekday, (d) => ({ ...d, open: event.target.checked }))}
                  />
                  Open
                </label>
                {day.open && (
                  <>
                    <div className="hours-times">
                      <label>
                        Opens
                        <input
                          type="time"
                          aria-label={`${name} opens`}
                          value={day.opens}
                          onChange={(event) => change(day.weekday, (d) => ({ ...d, opens: event.target.value }))}
                        />
                      </label>
                      <label>
                        Closes
                        <input
                          type="time"
                          aria-label={`${name} closes`}
                          value={day.closes}
                          onChange={(event) => change(day.weekday, (d) => ({ ...d, closes: event.target.value }))}
                        />
                      </label>
                    </div>
                    {day.breaks.map((b, index) => {
                      const which = `${name} break ${index + 1}`
                      const setBreak = (edit: Partial<{ start: string; end: string }>): void =>
                        change(day.weekday, (d) => ({
                          ...d,
                          breaks: d.breaks.map((each, i) => (i === index ? { ...each, ...edit } : each)),
                        }))
                      return (
                        <div key={index} className="hours-times">
                          <label>
                            Break from
                            <input
                              type="time"
                              aria-label={`${which} starts`}
                              value={b.start}
                              onChange={(event) => setBreak({ start: event.target.value })}
                            />
                          </label>
                          <label>
                            to
                            <input
                              type="time"
                              aria-label={`${which} ends`}
                              value={b.end}
                              onChange={(event) => setBreak({ end: event.target.value })}
                            />
                          </label>
                          <button
                            type="button"
                            className="staff-button staff-button-quiet"
                            aria-label={`Remove ${which}`}
                            onClick={() =>
                              change(day.weekday, (d) => ({ ...d, breaks: d.breaks.filter((_, i) => i !== index) }))
                            }
                          >
                            Remove
                          </button>
                        </div>
                      )
                    })}
                    <button
                      type="button"
                      className="staff-button staff-button-quiet"
                      aria-label={`Add a break on ${name}`}
                      onClick={() =>
                        change(day.weekday, (d) => ({ ...d, breaks: [...d.breaks, { start: '12:00', end: '12:30' }] }))
                      }
                    >
                      + Break
                    </button>
                  </>
                )}
              </fieldset>
            )
          })}
        </div>
      )}
      {errors.length > 0 && (
        <ul role="alert" className="staff-alert clash-list">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
      {outcome && 'error' in outcome && (
        <p role="alert" className="staff-alert">
          {outcome.error}
        </p>
      )}
      {outcome && 'clashes' in outcome && <ClashList bookings={outcome.clashes} />}
      {confirming ? (
        <div className="staff-panel">
          <p>{`Save these hours from ${shortDate(startsOn)}? Customers booking for those dates will see them at once.`}</p>
          <div className="staff-buttons">
            <button type="button" className="staff-button" disabled={busy} onClick={() => void save()}>
              Yes, save
            </button>
            <button type="button" className="staff-button staff-button-quiet" onClick={() => setConfirming(false)}>
              Back
            </button>
          </div>
        </div>
      ) : (
        <div className="staff-buttons">
          <button type="submit" className="staff-button" disabled={mode === 'new' && !drafts}>
            Save
          </button>
          <button type="button" className="staff-button staff-button-quiet" onClick={onCancel}>
            Cancel
          </button>
        </div>
      )}
    </form>
  )
}
