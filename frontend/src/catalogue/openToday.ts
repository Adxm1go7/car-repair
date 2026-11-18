import { addDays, hoursOn, weekdayOf } from './hours.ts'
import type { OpeningDay, Timetable } from './types.ts'

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

type OpenDay = OpeningDay & { open: string; close: string }

function isOpen(day: OpeningDay | undefined): day is OpenDay {
  return day?.open != null && day.close != null
}

/** The calendar date ("YYYY-MM-DD") and "HH:MM" that `now` is in the given time zone. */
function localNow(now: Date, timeZone: string): { date: string; time: string } {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(now)
  const part = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((p) => p.type === type)?.value ?? ''
  return { date: `${part('year')}-${part('month')}-${part('day')}`, time: `${part('hour')}:${part('minute')}` }
}

/**
 * The garage's status line, worked out in the garage's time zone (never the device's).
 * Breaks are ignored: during lunch the garage still counts as open today.
 */
export function openTodayText(timetables: Timetable[], now: Date, timeZone: string): string {
  const { date, time } = localNow(now, timeZone)
  const today = hoursOn(timetables, date)

  // "HH:MM" strings compare correctly as text.
  if (isOpen(today) && time < today.close) return `Open today ${today.open}–${today.close}`

  for (let daysAhead = 1; daysAhead <= 7; daysAhead++) {
    const nextDate = addDays(date, daysAhead)
    const next = hoursOn(timetables, nextDate)
    if (isOpen(next)) {
      const when = daysAhead === 1 ? 'tomorrow' : DAY_NAMES[weekdayOf(nextDate)]
      const status = isOpen(today) ? 'Closed now' : 'Closed today'
      return `${status}, opens ${when} at ${next.open}`
    }
  }
  return 'Closed'
}
