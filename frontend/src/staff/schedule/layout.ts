import { calendarNoon } from '../../booking/days.ts'
import type { ScheduleDay, ScheduleItem } from '../types.ts'

const DAY_MS = 24 * 60 * 60 * 1000
const MINUTES_IN_DAY = 24 * 60
// A closed day still gets a grid, so blocks or stray bookings on it can be seen.
const CLOSED_RANGE = { startMinutes: 8 * 60, endMinutes: 18 * 60 }

export type PlacedItem = {
  item: ScheduleItem
  bayId: number
  /** Minutes from the top of the grid (the day's opening). */
  topMinutes: number
  heightMinutes: number
}

function hhmmMinutes(value: string): number {
  const [hours, minutes] = value.split(':').map(Number)
  return hours * 60 + minutes
}

/** The grid's time span: opening to closing, as minutes after local midnight. */
export function dayRange(day: ScheduleDay): { startMinutes: number; endMinutes: number } {
  if (!day.open || !day.close) return CLOSED_RANGE
  return { startMinutes: hhmmMinutes(day.open), endMinutes: hhmmMinutes(day.close) }
}

/** The garage-local calendar date and minutes after midnight of an instant. Wall-clock
 * minutes, so a clock change never moves a 09:30 booking off the 09:30 line. */
export function localParts(iso: string, zone: string): { date: string; minutes: number } {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(iso))
  const part = (type: string): string => parts.find((p) => p.type === type)?.value ?? ''
  return {
    date: `${part('year')}-${part('month')}-${part('day')}`,
    minutes: Number(part('hour')) * 60 + Number(part('minute')),
  }
}

/** Minutes after `date`'s midnight, clamped to that day: earlier days are 0, later ones 24:00. */
function minutesOnDay(iso: string, date: string, zone: string): number {
  const local = localParts(iso, zone)
  if (local.date < date) return 0
  if (local.date > date) return MINUTES_IN_DAY
  return local.minutes
}

/** The items that fall on `day`, placed on its grid and clipped to its opening hours. */
export function placeItems(day: ScheduleDay, items: ScheduleItem[], zone: string): PlacedItem[] {
  const range = dayRange(day)
  const placed: PlacedItem[] = []
  for (const item of items) {
    const start = Math.max(minutesOnDay(item.start, day.date, zone), range.startMinutes)
    const end = Math.min(minutesOnDay(item.end, day.date, zone), range.endMinutes)
    if (end <= start) continue
    placed.push({ item, bayId: item.bay_id, topMinutes: start - range.startMinutes, heightMinutes: end - start })
  }
  return placed
}

/** `value` if it's a real "YYYY-MM-DD" date, otherwise null. */
export function validDate(value: string | null): string | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const noon = new Date(`${value}T12:00:00Z`)
  return !Number.isNaN(noon.getTime()) && noon.toISOString().startsWith(value) ? value : null
}

/** "2026-11-17" plus `days` (which may be negative). */
export function addDays(date: string, days: number): string {
  return new Date(calendarNoon(date).getTime() + days * DAY_MS).toISOString().slice(0, 10)
}

/** The Monday of `date`'s week. */
export function mondayOf(date: string): string {
  const weekday = (calendarNoon(date).getUTCDay() + 6) % 7 // 0 = Monday
  return addDays(date, -weekday)
}

/** "Tue 17 Nov". */
export function shortDay(date: string): string {
  return new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' })
    .format(calendarNoon(date))
    .replace(',', '')
}

/** "09:30–10:30" in the garage's zone. */
export function timeRange(start: string, end: string, zone: string): string {
  const hhmm = (iso: string): string => {
    const { minutes } = localParts(iso, zone)
    return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
  }
  return `${hhmm(start)}–${hhmm(end)}`
}

/** How far `zone` is ahead of UTC at an instant, in minutes. */
function offsetMinutes(instant: number, zone: string): number {
  const local = localParts(new Date(instant).toISOString(), zone)
  const wall = calendarNoon(local.date).getTime() - 12 * 60 * 60 * 1000 + local.minutes * 60_000
  return Math.round((wall - Math.floor(instant / 60_000) * 60_000) / 60_000)
}

/** The UTC ISO time of a garage-local date ("2026-11-17") and time ("09:30"). */
export function zonedIso(date: string, time: string, zone: string): string {
  const wall = calendarNoon(date).getTime() - 12 * 60 * 60 * 1000 + hhmmMinutes(time) * 60_000
  // Guess with the offset at the wall time, then correct with the offset at the guess,
  // which is right either side of a clock change.
  const guess = wall - offsetMinutes(wall, zone) * 60_000
  return new Date(wall - offsetMinutes(guess, zone) * 60_000).toISOString()
}
