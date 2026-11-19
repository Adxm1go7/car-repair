import { hoursOn } from '../catalogue/hours.ts'
import type { Timetable } from '../catalogue/types.ts'

/** One day in the day strip. weekday: 0 = Monday … 6 = Sunday. */
export type BookableDay = { date: string; weekday: number; open: boolean }

const DAY_MS = 24 * 60 * 60 * 1000

/** The garage's calendar date ("YYYY-MM-DD") at `now`, whatever the device's zone. */
export function todayInZone(now: Date, zone: string): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now)
}

/** Noon UTC on a calendar date: adding whole days to it can never land on the wrong date. */
export function calendarNoon(date: string): Date {
  const [year, month, day] = date.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day, 12))
}

/** `today` up to and including `today + windowDays`, each marked open or closed by the
 * timetable in force on that date. */
export function bookableDays(today: string, windowDays: number, timetables: Timetable[]): BookableDay[] {
  const first = calendarNoon(today).getTime()
  const days: BookableDay[] = []
  for (let offset = 0; offset <= windowDays; offset++) {
    const day = new Date(first + offset * DAY_MS)
    const weekday = (day.getUTCDay() + 6) % 7 // JavaScript counts from Sunday
    const date = day.toISOString().slice(0, 10)
    const hours = hoursOn(timetables, date)
    days.push({ date, weekday, open: hours.open !== null && hours.close !== null })
  }
  return days
}
