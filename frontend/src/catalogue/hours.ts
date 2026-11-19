import type { OpeningDay, Timetable } from './types.ts'

/** Noon UTC on a calendar date ("YYYY-MM-DD"): adding whole days to it never lands on the wrong date. */
function noon(date: string): Date {
  const [year, month, day] = date.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day, 12))
}

/** 0 = Monday … 6 = Sunday, for a calendar date. */
export function weekdayOf(date: string): number {
  return (noon(date).getUTCDay() + 6) % 7 // JavaScript counts from Sunday
}

/** `date` plus `days` calendar days, "YYYY-MM-DD". */
export function addDays(date: string, days: number): string {
  const day = noon(date)
  day.setUTCDate(day.getUTCDate() + days)
  return day.toISOString().slice(0, 10)
}

/**
 * The hours on `date`, from the timetable in force then: the latest to start on or before it.
 * A weekday the timetable has no row for, or a date before every timetable, is closed.
 */
export function hoursOn(timetables: Timetable[], date: string): OpeningDay {
  const weekday = weekdayOf(date)
  // "YYYY-MM-DD" strings compare correctly as text.
  const inForce = timetables.filter((t) => t.starts_on <= date).at(-1)
  return inForce?.days.find((d) => d.weekday === weekday) ?? { weekday, open: null, close: null, breaks: [] }
}

/** "Tue 1 Dec" for a calendar date. */
export function shortDate(date: string): string {
  return new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' })
    .format(noon(date))
    .replace(',', '')
}
