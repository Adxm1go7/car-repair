import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import { Link } from 'react-router'
import { createHold, fetchAvailability } from './api.ts'
import type { Result } from './api.ts'
import type { BookableDay } from './days.ts'
import { formatDayLabel, formatTime, formatTimeRange } from './format.ts'
import { selectionQuery } from './selection.ts'
import type { Availability, AvailabilitySlot, Hold } from './types.ts'

type Props = {
  services: string[]
  days: BookableDay[]
  zone: string
  onHeld: (hold: Hold) => void
}

/** A loaded day, tagged with what it was loaded for, so a stale answer is never shown. */
type Loaded = { key: string; result: Result<Availability> }

const TAKEN = 'Sorry, someone just took that time.'
const MIXED = "These services can't be booked together — please book them separately"

export function TimePicker({ services, days, zone, onHeld }: Props): JSX.Element {
  const [selected, setSelected] = useState(() => days.find((day) => day.open)?.date ?? null)
  const [version, setVersion] = useState(0) // bump to reload the same day
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [holding, setHolding] = useState(false)

  const key = `${selected ?? ''}#${version}`
  const servicesKey = services.join(',')

  useEffect(() => {
    if (selected === null) return
    let cancelled = false
    void fetchAvailability(servicesKey.split(','), selected).then((result) => {
      if (!cancelled) setLoaded({ key, result })
    })
    return () => {
      cancelled = true
    }
  }, [key, selected, servicesKey])

  function pickDay(date: string): void {
    setNotice(null)
    setSelected(date)
  }

  async function hold(slot: AvailabilitySlot): Promise<void> {
    setHolding(true)
    setNotice(null)
    const result = await createHold(services, slot.start)
    setHolding(false)
    if (result.ok) {
      onHeld(result.data)
    } else if (result.kind === 'taken') {
      setNotice(TAKEN)
      setVersion((v) => v + 1)
    } else {
      setNotice(result.detail ?? 'Sorry, something went wrong. Please try again.')
    }
  }

  const current = loaded?.key === key ? loaded.result : null

  return (
    <>
      <div className="day-strip" role="group" aria-label="Day">
        {days.map((day) => {
          const label = formatDayLabel(day.date)
          return (
            <button
              key={day.date}
              type="button"
              className="day"
              disabled={!day.open}
              aria-pressed={day.date === selected}
              aria-label={`${label.weekday} ${label.day}`}
              onClick={() => pickDay(day.date)}
            >
              <span className="day-weekday">{label.weekday}</span>
              <span className="day-date">{label.day}</span>
            </button>
          )
        })}
      </div>

      {notice && (
        <p role="alert" className="notice">
          {notice}
        </p>
      )}

      {selected === null ? (
        <p>Sorry, there are no open days to book right now.</p>
      ) : current === null ? (
        <p>Loading times…</p>
      ) : !current.ok ? (
        <div className="error">
          <p>{"Sorry, we couldn't load the times."}</p>
          <button type="button" className="link-button" onClick={() => setVersion((v) => v + 1)}>
            Try again
          </button>
        </div>
      ) : current.data.unavailable_reason === 'mixed_bay_types' ? (
        <div className="error">
          <p>{MIXED}</p>
          <Link to={`/${selectionQuery(services)}`}>Change services</Link>
        </div>
      ) : current.data.slots.length === 0 ? (
        <p>No times left on this day</p>
      ) : (
        <SlotGroups slots={current.data.slots} zone={zone} disabled={holding} onPick={hold} />
      )}
    </>
  )
}

type GroupsProps = {
  slots: AvailabilitySlot[]
  zone: string
  disabled: boolean
  onPick: (slot: AvailabilitySlot) => Promise<void>
}

function SlotGroups({ slots, zone, disabled, onPick }: GroupsProps): JSX.Element {
  const groups: [string, AvailabilitySlot[]][] = [
    ['Morning', slots.filter((slot) => formatTime(slot.start, zone) < '12:00')],
    ['Afternoon', slots.filter((slot) => formatTime(slot.start, zone) >= '12:00')],
  ]
  return (
    <>
      {groups
        .filter(([, items]) => items.length > 0)
        .map(([name, items]) => (
          <section key={name} aria-labelledby={`slots-${name}`}>
            <h2 id={`slots-${name}`}>{name}</h2>
            <div className="slots">
              {items.map((slot) => (
                <button
                  key={slot.start}
                  type="button"
                  className="slot"
                  disabled={disabled}
                  onClick={() => void onPick(slot)}
                >
                  {formatTimeRange(slot.start, slot.end, zone)}
                </button>
              ))}
            </div>
          </section>
        ))}
    </>
  )
}
