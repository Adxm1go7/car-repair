// Shapes returned by the booking API (backend/app/api/holds.py, availability.py, catalogue.py).
// Times are garage-local ISO strings with an offset, e.g. "2026-11-10T08:00:00+00:00".

/** How the page takes the deposit: Stripe's embedded form, or demo buttons with no keys set. */
export type PaymentConfig = { provider: 'stripe'; publishable_key: string } | { provider: 'demo' }

export type BookingPolicy = {
  booking_window_days: number
  slot_hold_minutes: number
  payment_hold_minutes: number
  deposit_amount_pence: number
  payment: PaymentConfig
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
  deposit_paid_pence: number
}

/** The deposit's payment form, from POST /api/holds/{reference}/checkout. */
export type Checkout = {
  client_secret: string | null
  demo_session: string | null
  expires_in_seconds: number
  amount_pence: number
}

export type DepositStatus = 'unpaid' | 'paid' | 'refund_pending' | 'refunded' | 'refund_failed' | 'waived'

/** Where a booking stands, from POST /api/holds/{reference}/status. */
export type HoldStatus =
  | { status: 'held' | 'expired'; deposit_status: DepositStatus; summary: null }
  | { status: 'confirmed'; deposit_status: DepositStatus; summary: BookingSummary }

export type CustomerDetails = {
  name: string
  phone: string
  email: string
  registration: string
  make: string
  model: string
  notes: string
}
