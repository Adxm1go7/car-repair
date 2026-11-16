import { post } from '../booking/api.ts'
import type { Message, StaffMe } from './types.ts'

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
