import type { Availability, BookingPolicy, Checkout, CustomerDetails, Hold, HoldStatus } from './types.ts'

/** Every call resolves, never throws. `detail` is the server's message when it sent one. */
export type Result<T> = { ok: true; data: T } | { ok: false; kind: 'error'; detail: string | null }

type Taken = { ok: false; kind: 'taken' }
type Expired = { ok: false; kind: 'expired' }
type Paid = { ok: false; kind: 'paid' }
type Declined = { ok: false; kind: 'declined' }

const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function detailOf(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    return typeof body.detail === 'string' ? body.detail : null
  } catch {
    return null
  }
}

/** Fetches and reads JSON. `special` maps a status to a result of its own, like 409 → taken. */
async function request<T, S = never>(
  url: string,
  init?: RequestInit,
  special: Record<number, S> = {},
): Promise<Result<T> | S> {
  try {
    const response = await fetch(url, init)
    if (response.status in special) return special[response.status]
    if (!response.ok) return { ok: false, kind: 'error', detail: await detailOf(response) }
    return { ok: true, data: (await response.json()) as T }
  } catch {
    return { ok: false, kind: 'error', detail: null }
  }
}

function post(body: unknown, method = 'POST'): RequestInit {
  return { method, headers: JSON_HEADERS, body: JSON.stringify(body) }
}

export function fetchBookingPolicy(): Promise<Result<BookingPolicy>> {
  return request<BookingPolicy>('/api/booking-policy')
}

export function fetchAvailability(services: string[], date: string): Promise<Result<Availability>> {
  const params = new URLSearchParams(services.map((slug) => ['services', slug]))
  params.set('date', date)
  return request<Availability>(`/api/availability?${params.toString()}`)
}

export function createHold(services: string[], start: string): Promise<Result<Hold> | Taken> {
  return request<Hold, Taken>('/api/holds', post({ services, start }), {
    409: { ok: false, kind: 'taken' },
  })
}

function holdUrl(reference: string, action = ''): string {
  return `/api/holds/${encodeURIComponent(reference)}${action}`
}

/** Save the details and open the deposit's payment form. A repeat returns the same form. */
export function startCheckout(
  reference: string,
  token: string,
  details: CustomerDetails,
): Promise<Result<Checkout> | Expired | Paid> {
  return request<Checkout, Expired | Paid>(holdUrl(reference, '/checkout'), post({ hold_token: token, ...details }), {
    409: { ok: false, kind: 'paid' },
    410: { ok: false, kind: 'expired' },
  })
}

/** Where the booking stands. POST, so the token stays out of URLs and logs. */
export function fetchHoldStatus(reference: string, token: string): Promise<Result<HoldStatus>> {
  return request<HoldStatus>(holdUrl(reference, '/status'), post({ hold_token: token }))
}

/**
 * Gives the slot back and closes its payment form. Best effort: if it fails, the hold runs
 * out on its own. `keepalive` lets the request finish even if the page is closing.
 * `paid` means a payment got in first, so the booking was confirmed instead.
 */
export async function cancelHold(reference: string, token: string): Promise<'released' | 'paid' | 'failed'> {
  try {
    const init = { ...post({ hold_token: token }, 'DELETE'), keepalive: true }
    const response = await fetch(holdUrl(reference), init)
    if (response.status === 409) return 'paid'
    return response.ok || response.status === 404 ? 'released' : 'failed'
  } catch {
    return 'failed' // the hold expires by itself
  }
}

/** Demo mode only: pretend the card was charged, or declined. */
export function payDemo(
  session: string,
  outcome: 'pay' | 'decline',
): Promise<Result<{ status: string }> | Declined> {
  return request<{ status: string }, Declined>(
    `/api/demo/checkout/${encodeURIComponent(session)}`,
    post({ outcome }),
    { 402: { ok: false, kind: 'declined' } },
  )
}
