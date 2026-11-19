import { post, request } from '../booking/api.ts'
import type { Result } from '../booking/api.ts'
import type { Checkout } from '../booking/types.ts'
import type { MyBooking, RefusalReason } from './types.ts'

type Invalid = { ok: false; kind: 'invalid' }
type Refused = { ok: false; kind: 'refused'; reason: RefusalReason }
type Unavailable = { ok: false; kind: 'unavailable' }
type Gone = { ok: false; kind: 'gone' }

const INVALID: Invalid = { ok: false, kind: 'invalid' }

function bookingUrl(reference: string, action: 'view' | 'cancel' | 'pay'): string {
  return `/api/bookings/${encodeURIComponent(reference)}/${action}`
}

/** The booking this link opens. POST, so the token stays out of URLs and logs. */
export function viewBooking(reference: string, token: string): Promise<Result<MyBooking> | Invalid> {
  return request<MyBooking, Invalid>(bookingUrl(reference, 'view'), post({ token }), { 404: INVALID })
}

/** Cancel the booking. A 409's detail is the reason it was refused. */
export async function cancelBooking(
  reference: string,
  token: string,
): Promise<Result<MyBooking> | Invalid | Refused | Unavailable> {
  const result = await request<MyBooking, Invalid | Unavailable>(bookingUrl(reference, 'cancel'), post({ token }), {
    404: INVALID,
    503: { ok: false, kind: 'unavailable' },
  })
  if (!result.ok && result.kind === 'error' && (result.detail === 'too_late' || result.detail === 'not_cancellable')) {
    return { ok: false, kind: 'refused', reason: result.detail }
  }
  return result
}

/** Open the deposit's payment form for a booking the garage approved. 409: nothing to pay. */
export function startPayment(
  reference: string,
  token: string,
): Promise<Result<Checkout> | Invalid | Gone | Unavailable> {
  return request<Checkout, Invalid | Gone | Unavailable>(bookingUrl(reference, 'pay'), post({ token }), {
    404: INVALID,
    409: { ok: false, kind: 'gone' },
    503: { ok: false, kind: 'unavailable' },
  })
}
