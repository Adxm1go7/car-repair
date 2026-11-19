import { post } from '../booking/api.ts'
import type { OpeningDay } from '../catalogue/types.ts'
import type {
  AdminBay,
  AdminTimetable,
  AdminService,
  AuditPage,
  BayType,
  Clash,
  Message,
  NewService,
  Schedule,
  ServiceFields,
  StaffAvailability,
  StaffBooking,
  StaffMe,
  StaffRole,
  StatusAction,
  TeamMember,
} from './types.ts'

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

// --- admin: team and audit ---------------------------------------------------------

export function fetchTeam(): Promise<StaffResult<TeamMember[]>> {
  return staffRequest<TeamMember[]>('/team')
}

/** A 409 means the email already has an account; its detail says so. */
export function inviteStaff(invite: { name: string; email: string; role: StaffRole }): Promise<StaffResult<TeamMember>> {
  return staffRequest<TeamMember>('/team', post(invite))
}

/** A 409 means the garage would be left without an admin; its detail says so. */
export function updateStaff(id: number, change: { role: StaffRole } | { active: boolean }): Promise<StaffResult<TeamMember>> {
  return staffRequest<TeamMember>(`/team/${id}`, post(change, 'PATCH'))
}

export function resetStaffPassword(id: number): Promise<StaffResult<TeamMember>> {
  return staffRequest<TeamMember>(`/team/${id}/reset-password`, { method: 'POST' })
}

export type AuditFilters = { from: string; to: string; staff: string; reference: string; page: number }

/** Newest first, 50 a page. Blank filters are left out. */
export function fetchAudit(filters: AuditFilters): Promise<StaffResult<AuditPage>> {
  const params = new URLSearchParams()
  for (const key of ['from', 'to', 'staff', 'reference'] as const) {
    if (filters[key]) params.set(key, filters[key])
  }
  params.set('page', String(filters.page))
  return staffRequest<AuditPage>(`/audit?${params.toString()}`)
}

// --- admin: settings ---------------------------------------------------------------

const SETTINGS = '/settings'

export function fetchAdminServices(): Promise<StaffResult<AdminService[]>> {
  return staffRequest<AdminService[]>(`${SETTINGS}/services`)
}

/** A 409 means the name is already used; its detail says so. */
export function addService(service: NewService): Promise<StaffResult<AdminService>> {
  return staffRequest<AdminService>(`${SETTINGS}/services`, post(service))
}

/** Hide or show with `{ active }`; only the fields given change. */
export function updateService(
  id: number,
  change: ServiceFields | { active: boolean },
): Promise<StaffResult<AdminService>> {
  return staffRequest<AdminService>(`${SETTINGS}/services/${id}`, post(change, 'PATCH'))
}

/** Swaps it with its neighbour; answers with the whole list in its new order. */
export function moveService(id: number, direction: 'up' | 'down'): Promise<StaffResult<AdminService[]>> {
  return staffRequest<AdminService[]>(`${SETTINGS}/services/${id}/move`, post({ direction }))
}

export function fetchBayTypes(): Promise<StaffResult<BayType[]>> {
  return staffRequest<BayType[]>(`${SETTINGS}/bay-types`)
}

export function fetchAdminBays(): Promise<StaffResult<AdminBay[]>> {
  return staffRequest<AdminBay[]>(`${SETTINGS}/bays`)
}

/** A 409 means the name is already used; its detail says so. */
export function addBay(bay: { name: string; bay_type_id: number }): Promise<StaffResult<AdminBay>> {
  return staffRequest<AdminBay>(`${SETTINGS}/bays`, post(bay))
}

/** Rename, or take out of use / put back. Out of use is refused with a 409 listing the
 * bookings in the way (see `clashesOf`); a name already used is a 409 with a detail. */
export function updateBay(id: number, change: { name: string } | { active: boolean }): Promise<StaffResult<AdminBay>> {
  return staffRequest<AdminBay>(`${SETTINGS}/bays/${id}`, post(change, 'PATCH'))
}

/** A 409 means the name is already used. */
export function addBayType(name: string): Promise<StaffResult<BayType>> {
  return staffRequest<BayType>(`${SETTINGS}/bay-types`, post({ name }))
}

/** The bookings a 409 lists as in the way of a bay or hours change, or null for another 409. */
export function clashesOf(body: unknown): Clash[] | null {
  const parsed = body as { detail?: unknown; bookings?: unknown } | null
  return parsed?.detail === 'clashes' && Array.isArray(parsed.bookings) ? (parsed.bookings as Clash[]) : null
}

export function fetchTimetables(): Promise<StaffResult<AdminTimetable[]>> {
  return staffRequest<AdminTimetable[]>(`${SETTINGS}/hours`)
}

/** New hours from `startsOn` (tomorrow at the earliest). A 409 lists the bookings the new
 * hours would leave outside (see `clashesOf`); a 422's detail says what's wrong. */
export function addTimetable(startsOn: string, days: OpeningDay[]): Promise<StaffResult<AdminTimetable>> {
  return staffRequest<AdminTimetable>(`${SETTINGS}/hours`, post({ starts_on: startsOn, days }))
}

/** Replace a future timetable's week. A 409 lists clashes, or says "not_allowed" once it's in force. */
export function replaceTimetable(id: number, days: OpeningDay[]): Promise<StaffResult<AdminTimetable>> {
  return staffRequest<AdminTimetable>(`${SETTINGS}/hours/${id}`, post({ days }, 'PUT'))
}

/** Delete a future timetable; the one before carries on. A 409 as for replacing. */
export function deleteTimetable(id: number): Promise<StaffResult<void>> {
  return staffRequest<void>(`${SETTINGS}/hours/${id}`, { method: 'DELETE' })
}

export type Contact = { name: string; address: string; phone: string; email: string }

export function fetchContact(): Promise<StaffResult<Contact>> {
  return staffRequest<Contact>(`${SETTINGS}/contact`)
}

/** Answers with the details as saved (trimmed, email in lower case). A 422's detail says what's wrong. */
export function saveContact(contact: Contact): Promise<StaffResult<Contact>> {
  return staffRequest<Contact>(`${SETTINGS}/contact`, post(contact, 'PUT'))
}
