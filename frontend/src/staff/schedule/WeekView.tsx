import type { JSX } from 'react'
import { Link, useSearchParams } from 'react-router'
import { calendarNoon, todayInZone } from '../../booking/days.ts'
import { useStaff } from '../StaffContext.ts'
import type { Schedule } from '../types.ts'
import { addDays, mondayOf, placeItems, shortDay, validDate } from './layout.ts'
import { ScheduleEntry, ScheduleHeader, ScheduleStatus } from './parts.tsx'
import { useSchedule } from './useSchedule.ts'

/** "16 Nov". */
function dayMonth(date: string): string {
  return new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'short' }).format(calendarNoon(date))
}

function WeekDays({ schedule, monday }: { schedule: Schedule; monday: string }): JSX.Element {
  const bayName = new Map(schedule.bays.map((b) => [b.id, b.active ? b.name : `${b.name} (out of use)`]))
  const dates = Array.from({ length: 7 }, (_, i) => addDays(monday, i))
  return (
    <div className="week-grid">
      {dates.map((date) => {
        const day = schedule.days.find((d) => d.date === date) ?? { date, open: null, close: null, breaks: [] }
        const placed = placeItems(day, schedule.items, schedule.timezone).sort((a, b) => a.topMinutes - b.topMinutes)
        const label = shortDay(date)
        return (
          <section key={date} className="week-day" aria-label={label}>
            <h2>
              <Link to={`/staff?date=${date}`}>{label}</Link>
            </h2>
            {!day.open && <p className="schedule-closed">Closed</p>}
            <ul className="day-list">
              {day.open && placed.length === 0 && <li className="staff-hint">Nothing booked</li>}
              {placed.map((p) => (
                <li key={`${p.item.kind}-${p.item.start}-${p.item.bay_id}`}>
                  <ScheduleEntry item={p.item} zone={schedule.timezone} bayName={bayName.get(p.bayId)} />
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}

function WeekContent({ date, today }: { date: string; today: string | null }): JSX.Element {
  const monday = mondayOf(date)
  const { state, reload } = useSchedule(monday, 7)
  return (
    <>
      <ScheduleHeader
        title={`Week of ${dayMonth(monday)}`}
        date={date}
        previous={{ label: 'Previous week', to: `/staff/week?date=${addDays(monday, -7)}` }}
        next={{ label: 'Next week', to: `/staff/week?date=${addDays(monday, 7)}` }}
        today={today ? `/staff/week?date=${today}` : '/staff/week'}
      />
      <ScheduleStatus state={state} reload={reload} />
      {state.kind === 'ready' && <WeekDays schedule={state.schedule} monday={monday} />}
    </>
  )
}

/** `/staff/week?date=YYYY-MM-DD`: Monday to Sunday of that date's week. */
export function WeekView(): JSX.Element {
  const { garage } = useStaff()
  const [params] = useSearchParams()
  const today = garage ? todayInZone(new Date(), garage.timezone) : null
  const date = validDate(params.get('date')) ?? today
  if (!date) return <p>Loading…</p>
  return <WeekContent date={date} today={today} />
}
