import { post, request } from '../booking/api.ts'
import type { Result } from '../booking/api.ts'
import type { MyBooking, RefusalReason } from './types.ts'

type Invalid = { ok: false; kind: 'invalid' }
type Refused = { ok: false; kind: 'refused'; reason: RefusalReason }
type Unavailable = { ok: false; kind: 'unavailable' }

const INVALID: Invalid = { ok: false, kind: 'invalid' }

function bookingUrl(reference: string, action: 'view' | 'cancel'): string {
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
