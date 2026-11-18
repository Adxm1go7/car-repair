import { useState, useSyncExternalStore } from 'react'
import type { JSX } from 'react'
import { useSearchParams } from 'react-router'
import { todayInZone } from '../../booking/days.ts'
import { useStaff } from '../StaffContext.ts'
import type { Schedule, ScheduleBlock, ScheduleDay } from '../types.ts'
import { addDays, dayRange, placeItems, shortDay, validDate } from './layout.ts'
import type { PlacedItem } from './layout.ts'
import { BlockPanel, ScheduleEntry, ScheduleHeader, ScheduleStatus } from './parts.tsx'
import { useSchedule } from './useSchedule.ts'

const NARROW_QUERY = '(max-width: 699px)'
const PX_PER_MINUTE = 1.2

function subscribeNarrow(onChange: () => void): () => void {
  const list = window.matchMedia?.(NARROW_QUERY)
  list?.addEventListener('change', onChange)
  return () => list?.removeEventListener('change', onChange)
}

/** True below about 700px, where the grid becomes a list with bay tabs. */
function useNarrow(): boolean {
  return useSyncExternalStore(
    subscribeNarrow,
    () => window.matchMedia?.(NARROW_QUERY).matches ?? false,
    () => false,
  )
}

function hhmmMinutes(value: string): number {
  const [hours, minutes] = value.split(':').map(Number)
  return hours * 60 + minutes
}

type ViewProps = {
  schedule: Schedule
  day: ScheduleDay
  placed: PlacedItem[]
  onSelectBlock: (block: ScheduleBlock) => void
}

function closedDay(date: string): ScheduleDay {
  return { date, open: null, close: null, breaks: [] }
}

function px(minutes: number): string {
  return `${minutes * PX_PER_MINUTE}px`
}

function DayGrid({ schedule, day, placed, onSelectBlock }: ViewProps): JSX.Element {
  const range = dayRange(day)
  const height = px(range.endMinutes - range.startMinutes)
  const hours: number[] = []
  for (let m = Math.ceil(range.startMinutes / 60) * 60; m < range.endMinutes; m += 60) hours.push(m)

  return (
    <div className="day-grid" style={{ gridTemplateColumns: `56px repeat(${schedule.bays.length}, minmax(140px, 1fr))` }}>
      <div className="day-times" style={{ height }} aria-hidden="true">
        {hours.map((m) => (
          <span key={m} style={{ top: px(m - range.startMinutes) }}>
            {`${String(m / 60).padStart(2, '0')}:00`}
          </span>
        ))}
      </div>
      {schedule.bays.map((bay) => (
        <section key={bay.id} className="day-bay" aria-label={bay.name}>
          <h2>{bay.name}</h2>
          <div className="day-bay-body" style={{ height }}>
            {day.breaks.map((b) => (
              <div
                key={b.start}
                className="day-break"
                style={{
                  top: px(hhmmMinutes(b.start) - range.startMinutes),
                  height: px(hhmmMinutes(b.end) - hhmmMinutes(b.start)),
                }}
              >
                Closed
              </div>
            ))}
            {placed
              .filter((p) => p.bayId === bay.id)
              .map((p) => (
                <ScheduleEntry
                  key={`${p.item.kind}-${p.item.start}-${p.item.bay_id}`}
                  item={p.item}
                  zone={schedule.timezone}
                  onSelectBlock={onSelectBlock}
                  style={{ position: 'absolute', top: px(p.topMinutes), height: px(p.heightMinutes) }}
                />
              ))}
          </div>
        </section>
      ))}
    </div>
  )
}

type ListRow = { top: number; key: string; element: JSX.Element }

function DayList({ schedule, day, placed, onSelectBlock }: ViewProps): JSX.Element {
  const [chosen, setChosen] = useState(0)
  const index = Math.min(chosen, schedule.bays.length - 1)
  const bay = schedule.bays[index]
  if (!bay) return <p>No bays</p>
  const range = dayRange(day)

  const rows: ListRow[] = [
    ...placed
      .filter((p) => p.bayId === bay.id)
      .map((p) => ({
        top: p.topMinutes,
        key: `${p.item.kind}-${p.item.start}`,
        element: <ScheduleEntry item={p.item} zone={schedule.timezone} onSelectBlock={onSelectBlock} />,
      })),
    ...day.breaks.map((b) => ({
      top: hhmmMinutes(b.start) - range.startMinutes,
      key: `break-${b.start}`,
      element: <div className="entry entry-closed">{`Closed ${b.start}–${b.end}`}</div>,
    })),
  ].sort((a, b) => a.top - b.top)

  return (
    <>
      <div role="tablist" aria-label="Bays" className="bay-tabs">
        {schedule.bays.map((b, i) => (
          <button
            key={b.id}
            type="button"
            role="tab"
            id={`bay-tab-${b.id}`}
            aria-selected={i === index}
            aria-controls="bay-panel"
            className="staff-button staff-button-quiet"
            onClick={() => setChosen(i)}
          >
            {b.name}
          </button>
        ))}
      </div>
      <ul role="tabpanel" id="bay-panel" aria-labelledby={`bay-tab-${bay.id}`} className="day-list">
        {rows.length === 0 && <li>Nothing booked</li>}
        {rows.map((row) => (
          <li key={row.key}>{row.element}</li>
        ))}
      </ul>
    </>
  )
}

function DayContent({ date, today }: { date: string; today: string | null }): JSX.Element {
  const { state, reload } = useSchedule(date, 1)
  const narrow = useNarrow()
  const [block, setBlock] = useState<ScheduleBlock | null>(null)

  let body: JSX.Element | null = null
  if (state.kind === 'ready') {
    const { schedule } = state
    const day = schedule.days.find((d) => d.date === date) ?? closedDay(date)
    const placed = placeItems(day, schedule.items, schedule.timezone)
    body = (
      <>
        {!day.open && <p className="schedule-closed">Closed all day</p>}
        {block && (
          <BlockPanel
            key={`${block.block_id}-${block.bay_id}`}
            block={block}
            zone={schedule.timezone}
            bayName={schedule.bays.find((b) => b.id === block.bay_id)?.name ?? `Bay ${block.bay_id}`}
            onRemoved={() => {
              setBlock(null)
              reload()
            }}
            onClose={() => setBlock(null)}
          />
        )}
        {narrow ? (
          <DayList schedule={schedule} day={day} placed={placed} onSelectBlock={setBlock} />
        ) : (
          <DayGrid schedule={schedule} day={day} placed={placed} onSelectBlock={setBlock} />
        )}
      </>
    )
  }

  return (
    <>
      <ScheduleHeader
        title={shortDay(date)}
        date={date}
        previous={{ label: 'Previous day', to: `/staff?date=${addDays(date, -1)}` }}
        next={{ label: 'Next day', to: `/staff?date=${addDays(date, 1)}` }}
        today={today ? `/staff?date=${today}` : '/staff'}
      />
      <ScheduleStatus state={state} reload={reload} />
      {body}
    </>
  )
}

/** `/staff?date=YYYY-MM-DD`: every bay's day. Without a date, today in the garage's zone. */
export function DayView(): JSX.Element {
  const { garage } = useStaff()
  const [params] = useSearchParams()
  const today = garage ? todayInZone(new Date(), garage.timezone) : null
  const date = validDate(params.get('date')) ?? today
  if (!date) return <p>Loading…</p>
  return <DayContent key={date} date={date} today={today} />
}
