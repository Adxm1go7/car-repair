import type { OpeningDay } from './types.ts'

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

type OpenDay = OpeningDay & { open: string; close: string }

function isOpen(day: OpeningDay | undefined): day is OpenDay {
  return day?.open != null && day.close != null
}

/** The weekday (0 = Monday) and "HH:MM" that `now` is in the given time zone. */
function localNow(now: Date, timeZone: string): { weekday: number; time: string } {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone,
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(now)
  const part = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((p) => p.type === type)?.value ?? ''
  return { weekday: DAY_NAMES.indexOf(part('weekday')), time: `${part('hour')}:${part('minute')}` }
}

/**
 * The garage's status line, worked out in the garage's time zone (never the device's).
 * Breaks are ignored: during lunch the garage still counts as open today.
 */
export function openTodayText(hours: OpeningDay[], now: Date, timeZone: string): string {
  const byWeekday = new Map(hours.map((day) => [day.weekday, day]))
  const { weekday, time } = localNow(now, timeZone)
  const today = byWeekday.get(weekday)

  // "HH:MM" strings compare correctly as text.
  if (isOpen(today) && time < today.close) return `Open today ${today.open}–${today.close}`

  for (let daysAhead = 1; daysAhead <= 7; daysAhead++) {
    const nextWeekday = (weekday + daysAhead) % 7
    const next = byWeekday.get(nextWeekday)
    if (isOpen(next)) {
      const when = daysAhead === 1 ? 'tomorrow' : DAY_NAMES[nextWeekday]
      const status = isOpen(today) ? 'Closed now' : 'Closed today'
      return `${status}, opens ${when} at ${next.open}`
    }
  }
  return 'Closed'
}
