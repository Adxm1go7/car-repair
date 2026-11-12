// Demo-garage data shared by the page tests.
import type { Garage, OpeningDay, Service } from '../catalogue/types.ts'

export const SERVICES: Service[] = [
  {
    slug: 'mot-test',
    name: 'MOT test',
    category: 'MOT',
    description: 'The annual roadworthiness test.',
    duration_minutes: 60,
    price_from_pence: 5485,
    price_to_pence: null,
    approval_mode: 'instant',
  },
  {
    slug: 'full-service',
    name: 'Full service',
    category: 'Servicing',
    description: 'Oil, filters, fluids and a 50-point check.',
    duration_minutes: 180,
    price_from_pence: 21900,
    price_to_pence: null,
    approval_mode: 'instant',
  },
  {
    slug: 'clutch-replacement',
    name: 'Clutch replacement',
    category: 'Repairs',
    description: 'Supply and fit a new clutch kit.',
    duration_minutes: 360,
    price_from_pence: 45000,
    price_to_pence: 75000,
    approval_mode: 'needs_approval',
  },
]

export const LUNCH = [{ start: '12:30', end: '13:00' }]
export const HOURS: OpeningDay[] = [
  ...[0, 1, 2, 3, 4].map((weekday) => ({ weekday, open: '08:00', close: '17:30', breaks: LUNCH })),
  { weekday: 5, open: '09:00', close: '14:00', breaks: [] },
  { weekday: 6, open: '10:00', close: '13:00', breaks: [] },
]

export const GARAGE: Garage = {
  name: 'Hillside Motors',
  address: '12 Station Road, Anytown, AT1 2CD',
  phone: '01632 960123',
  email: 'bookings@example.com',
  timezone: 'Europe/London',
}
