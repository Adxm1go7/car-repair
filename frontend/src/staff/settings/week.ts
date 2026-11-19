import { shortDate } from '../../catalogue/hours.ts'
import type { OpeningDay } from '../../catalogue/types.ts'
import type { AdminTimetable } from '../types.ts'

export const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** The first timetable starts long ago, so every date has one in force. */
export const FIRST_STARTS = '2000-01-01'

function dayText(day: OpeningDay): string {
  if (!day.open || !day.close) return 'closed'
  const breaks = day.breaks.map((b) => `${b.start}–${b.end}`)
  const breakText = breaks.length === 0 ? '' : `, ${breaks.length === 1 ? 'break' : 'breaks'} ${breaks.join(', ')}`
  return `${day.open}–${day.close}${breakText}`
}

/** "Mon–Fri 08:00–17:30, break 12:30–13:00 · Sat 09:00–14:00 · Sun closed": runs of weekdays
 * with the same hours share one entry. */
export function weekSummary(days: OpeningDay[]): string {
  const texts = Array.from({ length: 7 }, (_, weekday) => {
    const day = days.find((d) => d.weekday === weekday)
    return day ? dayText(day) : 'closed'
  })
  const parts: string[] = []
  let start = 0
  for (let weekday = 1; weekday <= 7; weekday++) {
    if (weekday < 7 && texts[weekday] === texts[start]) continue
    const end = weekday - 1
    const name = end === start ? SHORT[start] : `${SHORT[start]}–${SHORT[end]}`
    parts.push(`${name} ${texts[start]}`)
    start = weekday
  }
  return parts.join(' · ')
}

/** "Now (since the start)", "Now (from Mon 2 Nov)", "From Tue 1 Dec", "From the start (past)". */
export function timetableLabel(timetable: AdminTimetable): string {
  const first = timetable.starts_on === FIRST_STARTS
  const from = first ? 'the start' : shortDate(timetable.starts_on)
  switch (timetable.state) {
    case 'current':
      return first ? 'Now (since the start)' : `Now (from ${from})`
    case 'future':
      return `From ${from}`
    case 'past':
      return `From ${from} (past)`
  }
}
