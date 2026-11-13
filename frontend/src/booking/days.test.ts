import { expect, it } from 'vitest'
import type { OpeningDay } from '../catalogue/types.ts'
import { bookableDays, todayInZone } from './days.ts'
import { formatDayLabel, formatTime } from './format.ts'

// Monday–Saturday open, Sunday (6) closed.
const HOURS: OpeningDay[] = [
  ...[0, 1, 2, 3, 4, 5].map((weekday) => ({ weekday, open: '08:00', close: '17:30', breaks: [] })),
  { weekday: 6, open: null, close: null, breaks: [] },
]

it('uses the garage date just after midnight UTC in BST', () => {
  expect(todayInZone(new Date('2026-06-30T23:30:00Z'), 'Europe/London')).toBe('2026-07-01')
})

it('uses the garage date, not the device date, in winter', () => {
  expect(todayInZone(new Date('2026-11-10T23:30:00Z'), 'Europe/London')).toBe('2026-11-10')
})

it('covers today through the last window day', () => {
  const days = bookableDays('2026-11-10', 60, HOURS)
  expect(days[0]).toEqual({ date: '2026-11-10', weekday: 1, open: true })
  expect(days).toHaveLength(61)
  expect(days.at(-1)?.date).toBe('2027-01-09')
})

it('marks closed weekdays', () => {
  const days = bookableDays('2026-11-14', 2, HOURS) // Saturday, Sunday, Monday
  expect(days.map((d) => [d.date, d.weekday, d.open])).toEqual([
    ['2026-11-14', 5, true],
    ['2026-11-15', 6, false],
    ['2026-11-16', 0, true],
  ])
})

it('treats a weekday missing from the hours as closed', () => {
  expect(bookableDays('2026-11-16', 0, [])).toEqual([{ date: '2026-11-16', weekday: 0, open: false }])
})

it('steps over the October clock change without repeating a day', () => {
  expect(bookableDays('2026-10-24', 2, HOURS).map((d) => d.date)).toEqual([
    '2026-10-24',
    '2026-10-25',
    '2026-10-26',
  ])
})

it('steps over the March clock change without skipping a day', () => {
  expect(bookableDays('2027-03-27', 2, HOURS).map((d) => d.date)).toEqual([
    '2027-03-27',
    '2027-03-28',
    '2027-03-29',
  ])
})

it('formats a time in the garage zone', () => {
  expect(formatTime('2026-07-01T08:30:00+01:00', 'Europe/London')).toBe('08:30')
  expect(formatTime('2026-07-01T07:30:00Z', 'Europe/London')).toBe('08:30')
})

it('labels a day with its short weekday and date', () => {
  expect(formatDayLabel('2026-11-16')).toEqual({ weekday: 'Mon', day: '16 Nov' })
})
