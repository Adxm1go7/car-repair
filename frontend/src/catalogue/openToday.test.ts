import { describe, expect, it } from 'vitest'
import { openTodayText } from './openToday.ts'
import type { OpeningDay } from './types.ts'

const LUNCH = [{ start: '12:30', end: '13:00' }]

// The seeded week: Mon–Fri 08:00–17:30 with lunch, Sat 09:00–14:00, Sun 10:00–13:00.
const DEMO_HOURS: OpeningDay[] = [
  { weekday: 0, open: '08:00', close: '17:30', breaks: LUNCH },
  { weekday: 1, open: '08:00', close: '17:30', breaks: LUNCH },
  { weekday: 2, open: '08:00', close: '17:30', breaks: LUNCH },
  { weekday: 3, open: '08:00', close: '17:30', breaks: LUNCH },
  { weekday: 4, open: '08:00', close: '17:30', breaks: LUNCH },
  { weekday: 5, open: '09:00', close: '14:00', breaks: [] },
  { weekday: 6, open: '10:00', close: '13:00', breaks: [] },
]

const closed = (weekday: number): OpeningDay => ({ weekday, open: null, close: null, breaks: [] })

const LONDON = 'Europe/London'

// 2026-11-10 is a Tuesday (UK on GMT, so UTC = local). 2026-07-14 is a Tuesday (UK on BST, UTC+1).
describe('openTodayText', () => {
  it.each([
    ['open mid-morning', '2026-11-10T10:00:00Z', 'Open today 08:00–17:30'],
    ['before opening', '2026-11-10T07:00:00Z', 'Open today 08:00–17:30'],
    ['during lunch', '2026-11-10T12:45:00Z', 'Open today 08:00–17:30'],
    ['after closing', '2026-11-10T18:00:00Z', 'Closed now, opens tomorrow at 08:00'],
    ['Friday evening, Saturday hours', '2026-11-13T18:00:00Z', 'Closed now, opens tomorrow at 09:00'],
    ['summer time, open (08:30 BST)', '2026-07-14T07:30:00Z', 'Open today 08:00–17:30'],
    ['summer time, closed (17:45 BST)', '2026-07-14T16:45:00Z', 'Closed now, opens tomorrow at 08:00'],
  ])('%s', (_label, now, expected) => {
    expect(openTodayText(DEMO_HOURS, new Date(now), LONDON)).toBe(expected)
  })

  it('on a closed day, names the next open day', () => {
    const hours = DEMO_HOURS.map((day) => (day.weekday === 2 || day.weekday === 3 ? closed(day.weekday) : day))
    // Wednesday 2026-11-11, with Wednesday and Thursday closed.
    expect(openTodayText(hours, new Date('2026-11-11T12:00:00Z'), LONDON)).toBe(
      'Closed today, opens Fri at 08:00',
    )
  })

  it('uses the given time zone, not the device clock', () => {
    // 23:30 UTC on Tuesday is already Wednesday 08:30 in Tokyo.
    expect(openTodayText(DEMO_HOURS, new Date('2026-11-10T23:30:00Z'), 'Asia/Tokyo')).toBe(
      'Open today 08:00–17:30',
    )
  })

  it('says Closed when no day is open', () => {
    const hours = [0, 1, 2, 3, 4, 5, 6].map(closed)
    expect(openTodayText(hours, new Date('2026-11-10T10:00:00Z'), LONDON)).toBe('Closed')
  })
})
