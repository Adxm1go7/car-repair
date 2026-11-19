import type { StaffResult } from '../api.ts'
import { FAILED } from '../labels.ts'

/** What to tell the admin when a settings call fails: the server's own words when it sent a
 * sentence (a 409's or a 422's detail), otherwise the general message. Null for a 401, which
 * already sends them to the login page. */
export function failure(result: StaffResult<unknown>): string | null {
  if (result.ok || result.kind === 'unauthorised') return null
  if (result.kind === 'conflict') {
    const detail = (result.body as { detail?: unknown } | null)?.detail
    if (typeof detail === 'string' && detail !== 'clashes' && detail !== 'not_allowed') return detail
  }
  if (result.kind === 'error' && result.detail) return result.detail
  return FAILED
}

const POUNDS = /^\d{1,5}(\.\d{1,2})?$/

/** "54.85" → 5485, "50" → 5000, "" or anything else → null. At most £99,999.99. */
export function parsePounds(text: string): number | null {
  const value = text.trim().replace(/^£/, '')
  if (!POUNDS.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  return Number(whole) * 100 + Number(fraction.padEnd(2, '0'))
}

/** 5485 → "54.85", 5000 → "50.00": how a price looks in a form field. */
export function penceToPounds(pence: number): string {
  return (pence / 100).toFixed(2)
}
