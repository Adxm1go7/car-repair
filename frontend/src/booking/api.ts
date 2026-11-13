import type { Availability, BookingPolicy, BookingSummary, CustomerDetails, Hold } from './types.ts'

/** Every call resolves, never throws. `detail` is the server's message when it sent one. */
export type Result<T> = { ok: true; data: T } | { ok: false; kind: 'error'; detail: string | null }

type Taken = { ok: false; kind: 'taken' }
type Expired = { ok: false; kind: 'expired' }

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

export function confirmHold(
  reference: string,
  token: string,
  details: CustomerDetails,
): Promise<Result<BookingSummary> | Expired> {
  const url = `/api/holds/${encodeURIComponent(reference)}/confirm`
  return request<BookingSummary, Expired>(url, post({ hold_token: token, ...details }), {
    410: { ok: false, kind: 'expired' },
  })
}

/**
 * Gives the slot back. Best effort: if it fails, the hold simply runs out on its own.
 * `keepalive` lets the request finish even if the page is closing or reloading.
 */
export async function cancelHold(reference: string, token: string): Promise<void> {
  try {
    const init = { ...post({ hold_token: token }, 'DELETE'), keepalive: true }
    await fetch(`/api/holds/${encodeURIComponent(reference)}`, init)
  } catch {
    // nothing to do: the hold expires by itself
  }
}
