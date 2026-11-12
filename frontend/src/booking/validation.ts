import type { CustomerDetails } from './types.ts'

// The customer's details, checked by the same rules as backend/app/bookings/rules.py so
// mistakes show up before the form is sent. The server checks again; it has the last word.

export type FieldErrors = Partial<Record<keyof CustomerDetails, string>>

const PHONE_CHARACTERS = /^[0-9 +()-]+$/
const REGISTRATION = /^[A-Z0-9]{2,8}$/

/** Length in characters as Python counts them (code points), not UTF-16 units. */
function length(value: string): number {
  return [...value].length
}

function checkLength(value: string, low: number, high: number, what: string): string | null {
  const trimmed = value.trim()
  if (trimmed === '') return `Please enter your ${what}`
  if (length(trimmed) < low || length(trimmed) > high) return `Your ${what} must be ${low}–${high} characters`
  return null
}

function checkPhone(value: string): string | null {
  const trimmed = value.trim()
  const digits = [...trimmed].filter((char) => char >= '0' && char <= '9').length
  const ok = trimmed.length >= 7 && trimmed.length <= 20 && PHONE_CHARACTERS.test(trimmed) && digits >= 7
  return ok ? null : 'Please enter a phone number we can call'
}

function checkEmail(value: string): string | null {
  const email = value.trim().toLowerCase()
  const at = email.indexOf('@')
  const local = at === -1 ? '' : email.slice(0, at)
  const domain = at === -1 ? '' : email.slice(at + 1)
  const ok =
    length(email) <= 254 &&
    at !== -1 &&
    local !== '' &&
    !domain.includes('@') &&
    domain.replace(/^\.+|\.+$/g, '').includes('.') &&
    !/\s/.test(email)
  return ok ? null : 'Please enter a valid email address'
}

function checkRegistration(value: string): string | null {
  const plate = value.replace(/\s+/g, '').toUpperCase()
  return REGISTRATION.test(plate) ? null : 'Please enter your registration, 2–8 letters or numbers'
}

function checkNotes(value: string): string | null {
  return length(value.trim()) > 1000 ? 'Notes can be at most 1000 characters' : null
}

/** Every field's problem, if it has one. Empty means valid. */
export function validateDetails(values: CustomerDetails): FieldErrors {
  const checks: [keyof CustomerDetails, string | null][] = [
    ['name', checkLength(values.name, 1, 100, 'name')],
    ['phone', checkPhone(values.phone)],
    ['email', checkEmail(values.email)],
    ['registration', checkRegistration(values.registration)],
    ['make', checkLength(values.make, 1, 50, 'car make and model')],
    ['model', checkLength(values.model, 1, 50, 'car make and model')],
    ['notes', checkNotes(values.notes)],
  ]
  const errors: FieldErrors = {}
  for (const [field, message] of checks) {
    if (message !== null) errors[field] = message
  }
  return errors
}
