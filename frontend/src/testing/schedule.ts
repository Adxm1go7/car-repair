import type { Schedule, ScheduleBooking, ScheduleDay } from '../staff/types.ts'

export function scheduleUrl(from: string, days: 1 | 7): string {
  return `/api/staff/schedule?from=${from}&days=${days}`
}

export function openDay(date: string): ScheduleDay {
  return { date, open: '08:00', close: '17:30', breaks: [{ start: '12:30', end: '13:00' }] }
}

export function bookingItem(overrides: Partial<ScheduleBooking> = {}): ScheduleBooking {
  return {
    kind: 'booking',
    bay_id: 1,
    start: '2026-11-17T09:30:00+00:00',
    end: '2026-11-17T10:30:00+00:00',
    reference: 'ABCD-EFGH',
    status: 'confirmed',
    registration: 'AB12CDE',
    services: ['MOT test'],
    source: 'online',
    has_email: true,
    ...overrides,
  }
}

/** Tuesday 17 November 2026: an online booking and a block in the MOT bay, a phone
 * booking with no email and a held booking in Bay 1. */
export const DAY_SCHEDULE: Schedule = {
  timezone: 'Europe/London',
  bays: [
    { id: 1, slug: 'mot-bay', name: 'MOT bay', bay_type: 'MOT' },
    { id: 2, slug: 'bay-1', name: 'Bay 1', bay_type: 'General' },
  ],
  days: [openDay('2026-11-17')],
  items: [
    bookingItem(),
    bookingItem({
      bay_id: 2,
      reference: 'PHON-EONE',
      start: '2026-11-17T08:00:00+00:00',
      end: '2026-11-17T09:00:00+00:00',
      registration: 'CD34EFG',
      services: ['Full service', 'Brake check'],
      status: 'in_progress',
      source: 'phone',
      has_email: false,
    }),
    bookingItem({
      bay_id: 2,
      reference: 'HELD-HELD',
      start: '2026-11-17T11:00:00+00:00',
      end: '2026-11-17T12:00:00+00:00',
      registration: 'EF56GHI',
      status: 'held',
    }),
    {
      kind: 'block',
      bay_id: 1,
      start: '2026-11-17T14:00:00+00:00',
      end: '2026-11-17T15:00:00+00:00',
      block_id: 9,
      note: 'Lift repair',
    },
  ],
}
