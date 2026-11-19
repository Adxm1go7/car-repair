// Shapes returned by the booking-link API (backend/app/api/my_booking.py).
import type { BookingSummary } from '../booking/types.ts'

/** A booking opened from its emailed link. The API, not the page's clock, says if it can be cancelled. */
export type MyBooking = {
  summary: BookingSummary
  deposit_status: string
  can_cancel: boolean
  refund_if_cancelled: boolean
  free_cancellation_until: string
  /** A request: when the garage will answer by. An approval: when the deposit is due by. */
  deadline?: string | null
}

export type RefusalReason = 'too_late' | 'not_cancellable'
