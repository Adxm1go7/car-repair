import type { JSX } from 'react'
import { formatTime } from '../../booking/format.ts'
import type { StaffSlot } from '../types.ts'

export type PickedSlot = { start: string; bayId: number }

type Props = {
  slots: StaffSlot[]
  bays: { id: number; name: string }[]
  zone: string
  selected: PickedSlot | null
  onPick: (start: string, bayId: number) => void
}

/** The free start times, then the bays that can take the chosen one. Choosing a time picks
 * its first bay; tapping another bay changes it. Used by move and phone bookings. */
export function TimePickerGrid({ slots, bays, zone, selected, onPick }: Props): JSX.Element {
  if (slots.length === 0) return <p className="staff-hint">No free times that day</p>
  const names = new Map(bays.map((b) => [b.id, b.name]))
  const chosen = selected ? slots.find((s) => s.start === selected.start) : undefined

  return (
    <div className="time-picker">
      <div className="time-grid" role="group" aria-label="Times">
        {slots.map((slot) => (
          <button
            key={slot.start}
            type="button"
            className="staff-button staff-button-quiet"
            aria-pressed={slot.start === selected?.start}
            onClick={() => onPick(slot.start, slot.bay_ids[0])}
          >
            {formatTime(slot.start, zone)}
          </button>
        ))}
      </div>
      {chosen && (
        <div className="time-grid" role="group" aria-label="Bays">
          {chosen.bay_ids.map((bayId) => (
            <button
              key={bayId}
              type="button"
              className="staff-button staff-button-quiet"
              aria-pressed={bayId === selected?.bayId}
              onClick={() => onPick(chosen.start, bayId)}
            >
              {names.get(bayId) ?? `Bay ${bayId}`}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
