// Shapes returned by the booking API (backend/app/api/holds.py, availability.py, catalogue.py).
// Times are garage-local ISO strings with an offset, e.g. "2026-11-10T08:00:00+00:00".

export type BookingPolicy = {
  booking_window_days: number
  slot_hold_minutes: number
}

export type AvailabilitySlot = {
  start: string
  end: string
}

export type Availability = {
  date: string
  timezone: string
  duration_minutes: number
  unavailable_reason: 'mixed_bay_types' | null
  slots: AvailabilitySlot[]
}

export type ServiceSummary = {
  slug: string
  name: string
  duration_minutes: number
  price_from_pence: number
  price_to_pence: number | null
}

export type Hold = {
  reference: string
  hold_token: string
  expires_at: string
  expires_in_seconds: number
  start: string
  end: string
  services: ServiceSummary[]
}

export type BookingSummary = {
  reference: string
  status: string
  start: string
  end: string
  services: ServiceSummary[]
  registration: string
  make: string
  model: string
}

export type CustomerDetails = {
  name: string
  phone: string
  email: string
  registration: string
  make: string
  model: string
  notes: string
}
