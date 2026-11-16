import { post } from '../booking/api.ts'
import type { Message, Schedule, StaffAvailability, StaffBooking, StaffMe, StatusAction } from './types.ts'

/** Every call resolves, never throws. `detail` is the server's message when it sent one. */
export type StaffResult<T> =
  | { ok: true; data: T }
  | { ok: false; kind: 'unauthorised' }
  | { ok: false; kind: 'forbidden' }
  | { ok: false; kind: 'conflict'; body: unknown }
  | { ok: false; kind: 'error'; detail: string | null }

let onUnauthorised: (() => void) | null = null

/** StaffApp sets this, so a 401 from any call sends the user to the login page. */
export function setUnauthorisedHandler(handler: (() => void) | null): void {
  onUnauthorised = handler
}

async function bodyOf(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

async function send<T>(path: string, init: RequestInit | undefined, reportUnauthorised: boolean): Promise<StaffResult<T>> {
  try {
    const response = await fetch(`/api/staff${path}`, init)
    if (response.status === 401) {
      if (reportUnauthorised) onUnauthorised?.()
      return { ok: false, kind: 'unauthorised' }
    }
    if (response.status === 403) return { ok: false, kind: 'forbidden' }
    if (response.status === 409) return { ok: false, kind: 'conflict', body: await bodyOf(response) }
    if (!response.ok) {
      const body = (await bodyOf(response)) as { detail?: unknown } | null
      return { ok: false, kind: 'error', detail: typeof body?.detail === 'string' ? body.detail : null }
    }
    if (response.status === 204) return { ok: true, data: undefined as T }
    return { ok: true, data: (await response.json()) as T }
  } catch {
    return { ok: false, kind: 'error', detail: null }
  }
}

/** A call to `/api/staff<path>`. A 401 sends the user to the login page. */
export function staffRequest<T>(path: string, init?: RequestInit): Promise<StaffResult<T>> {
  return send<T>(path, init, true)
}

// Login and the password pages answer 401/400 for a wrong password or a bad link, which
// mustn't send anyone to the login page, so they use `send` without the handler.

export function login(email: string, password: string): Promise<StaffResult<StaffMe>> {
  return send<StaffMe>('/login', post({ email, password }), false)
}

export function forgotPassword(email: string): Promise<StaffResult<Message>> {
  return send<Message>('/forgot-password', post({ email }), false)
}

export function setPassword(token: string, password: string): Promise<StaffResult<StaffMe>> {
  return send<StaffMe>('/set-password', post({ token, password }), false)
}

export function logout(): Promise<StaffResult<void>> {
  return send<void>('/logout', { method: 'POST' }, false)
}

export function fetchMe(): Promise<StaffResult<StaffMe>> {
  return staffRequest<StaffMe>('/me')
}

// --- one booking ---------------------------------------------------------------------

function bookingPath(reference: string, action = ''): string {
  return `/bookings/${encodeURIComponent(reference)}${action}`
}

/** The `detail` of a 409 body: "taken", "not_allowed" or "no_change". */
export function conflictDetail(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail
  return typeof detail === 'string' ? detail : null
}

export function fetchStaffBooking(reference: string): Promise<StaffResult<StaffBooking>> {
  return staffRequest<StaffBooking>(bookingPath(reference))
}

export function fetchMoveOptions(reference: string, date: string): Promise<StaffResult<StaffAvailability>> {
  return staffRequest<StaffAvailability>(`${bookingPath(reference, '/move-options')}?date=${date}`)
}

export function moveBooking(
  reference: string,
  move: { start: string; bay_id: number; reason: string | null },
): Promise<StaffResult<StaffBooking>> {
  return staffRequest<StaffBooking>(bookingPath(reference, '/move'), post(move))
}

/** A 503 (error) means the refund couldn't start, and nothing changed. */
export function cancelStaffBooking(reference: string, reason: string | null): Promise<StaffResult<StaffBooking>> {
  return staffRequest<StaffBooking>(bookingPath(reference, '/cancel'), post({ reason }))
}

export function changeStatus(reference: string, action: StatusAction): Promise<StaffResult<StaffBooking>> {
  return staffRequest<StaffBooking>(bookingPath(reference, '/status'), post({ action }))
}

/** The bays, with names, from a day's schedule. */
export function fetchBays(date: string): Promise<StaffResult<Schedule>> {
  return staffRequest<Schedule>(`/schedule?from=${date}&days=1`)
}

// --- phone bookings and blocks ---------------------------------------------------

/** Free starts for these services on `date`, with the bays that can take each. */
export function fetchStaffAvailability(services: string[], date: string): Promise<StaffResult<StaffAvailability>> {
  const params = new URLSearchParams(services.map((slug) => ['services', slug]))
  params.set('date', date)
  return staffRequest<StaffAvailability>(`/availability?${params.toString()}`)
}

export type PhoneBookingIn = {
  services: string[]
  start: string
  bay_id: number
  name: string
  phone: string
  email: string | null
  registration: string
  make: string
  model: string
  notes: string | null
}

/** A 409 means the time was just taken; a 422's detail says what's wrong. */
export function createPhoneBooking(booking: PhoneBookingIn): Promise<StaffResult<{ reference: string }>> {
  return staffRequest<{ reference: string }>('/bookings', post(booking))
}

export type BlockIn = { bay_id: number | null; start: string; end: string; note: string }

/** What a 409 lists as in the way of a new block. Booking starts are garage-local ISO. */
export type BlockClashes = {
  bookings: { reference: string; start: string; bay: string }[]
  blocks: { id: number; note: string }[]
}

export function createBlock(block: BlockIn): Promise<StaffResult<{ id: number }>> {
  return staffRequest<{ id: number }>('/blocks', post(block))
}

export function removeBlock(id: number): Promise<StaffResult<void>> {
  return staffRequest<void>(`/blocks/${id}`, { method: 'DELETE' })
}
