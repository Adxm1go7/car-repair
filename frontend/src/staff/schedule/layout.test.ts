import { expect, it } from 'vitest'
import type { ScheduleBlock, ScheduleBooking, ScheduleDay } from '../types.ts'
import { addDays, dayRange, mondayOf, placeItems, zonedIso } from './layout.ts'

const ZONE = 'Europe/London'

function day(date: string, open: string | null = '08:00', close: string | null = '17:30'): ScheduleDay {
  return { date, open, close, breaks: [] }
}

function booking(start: string, end: string, bay_id = 1): ScheduleBooking {
  return {
    kind: 'booking',
    bay_id,
    start,
    end,
    reference: 'ABCD-EFGH',
    status: 'confirmed',
    registration: 'AB12CDE',
    services: ['MOT test'],
    source: 'online',
    has_email: true,
  }
}

it('places a 09:30–10:30 item on an 08:00 day at top 90, height 60', () => {
  const placed = placeItems(
    day('2026-11-17'),
    [booking('2026-11-17T09:30:00+00:00', '2026-11-17T10:30:00+00:00', 3)],
    ZONE,
  )
  expect(placed).toHaveLength(1)
  expect(placed[0]).toMatchObject({ bayId: 3, topMinutes: 90, heightMinutes: 60 })
})

it('stays correct on the day the clocks go forward', () => {
  // 29 March 2026: 09:30 local is 08:30 UTC.
  const placed = placeItems(
    day('2026-03-29'),
    [booking('2026-03-29T09:30:00+01:00', '2026-03-29T10:30:00+01:00')],
    ZONE,
  )
  expect(placed[0]).toMatchObject({ topMinutes: 90, heightMinutes: 60 })
})

it('stays correct on the day the clocks go back', () => {
  // 25 October 2026: after 02:00 local, London is on UTC again.
  const placed = placeItems(
    day('2026-10-25'),
    [booking('2026-10-25T09:30:00+00:00', '2026-10-25T10:30:00+00:00')],
    ZONE,
  )
  expect(placed[0]).toMatchObject({ topMinutes: 90, heightMinutes: 60 })
})

it('leaves out items on other days and clips a block that runs past the day', () => {
  const block: ScheduleBlock = {
    kind: 'block',
    bay_id: 2,
    start: '2026-11-16T08:00:00+00:00',
    end: '2026-11-18T17:30:00+00:00',
    block_id: 7,
    note: 'Lift repair',
  }
  const other = booking('2026-11-18T09:00:00+00:00', '2026-11-18T10:00:00+00:00')
  const placed = placeItems(day('2026-11-17'), [block, other], ZONE)
  expect(placed).toHaveLength(1)
  expect(placed[0]).toMatchObject({ bayId: 2, topMinutes: 0, heightMinutes: 570 })
})

it('dayRange runs from opening to closing', () => {
  expect(dayRange(day('2026-11-17'))).toEqual({ startMinutes: 480, endMinutes: 1050 })
})

it('dayRange on a closed day falls back to 08:00–18:00', () => {
  expect(dayRange(day('2026-11-22', null, null))).toEqual({ startMinutes: 480, endMinutes: 1080 })
})

it('mondayOf and addDays work on calendar dates', () => {
  expect(mondayOf('2026-11-18')).toBe('2026-11-16')
  expect(mondayOf('2026-11-22')).toBe('2026-11-16')
  expect(mondayOf('2026-11-16')).toBe('2026-11-16')
  expect(addDays('2026-10-24', 1)).toBe('2026-10-25')
  expect(addDays('2026-11-16', -1)).toBe('2026-11-15')
})

it('zonedIso turns a garage-local date and time into UTC', () => {
  expect(zonedIso('2026-11-17', '08:00', ZONE)).toBe('2026-11-17T08:00:00.000Z')
  expect(zonedIso('2026-06-17', '09:00', ZONE)).toBe('2026-06-17T08:00:00.000Z')
  // The days the clocks change: before and after the change.
  expect(zonedIso('2026-03-29', '00:30', ZONE)).toBe('2026-03-29T00:30:00.000Z')
  expect(zonedIso('2026-03-29', '09:00', ZONE)).toBe('2026-03-29T08:00:00.000Z')
  expect(zonedIso('2026-10-25', '09:00', ZONE)).toBe('2026-10-25T09:00:00.000Z')
  expect(zonedIso('2026-07-01', '09:00', 'America/New_York')).toBe('2026-07-01T13:00:00.000Z')
})
