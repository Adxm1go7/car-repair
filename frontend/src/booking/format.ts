import { calendarNoon } from './days.ts'

/** "08:30": the time in the garage's zone, whatever the device's. */
export function formatTime(iso: string, zone: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: zone,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(iso))
}

/** "08:00 – 09:00". */
export function formatTimeRange(start: string, end: string, zone: string): string {
  return `${formatTime(start, zone)} – ${formatTime(end, zone)}`
}

/** { weekday: "Mon", day: "16 Nov" } for "2026-11-16". */
export function formatDayLabel(date: string): { weekday: string; day: string } {
  const noon = calendarNoon(date)
  const weekday = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short' }).format(noon)
  const day = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'short' }).format(noon)
  return { weekday, day }
}

/** "Monday 16 November" for a garage-local ISO time. */
export function formatLongDate(iso: string, zone: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: zone,
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  }).format(new Date(iso))
}
