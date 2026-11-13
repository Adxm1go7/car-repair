import { expect, it } from 'vitest'
import type { CustomerDetails } from './types.ts'
import { validateDetails } from './validation.ts'

// The same rules and boundaries as backend/app/bookings/rules.py.
const VALID: CustomerDetails = {
  name: 'Sam Driver',
  phone: '07700 900123',
  email: 'sam@example.com',
  registration: 'ab12 cde',
  make: 'Ford',
  model: 'Focus',
  notes: '',
}

function errorsFor(changes: Partial<CustomerDetails>): Partial<Record<keyof CustomerDetails, string>> {
  return validateDetails({ ...VALID, ...changes })
}

it('accepts valid details', () => {
  expect(validateDetails(VALID)).toEqual({})
})

it.each([
  ['name', 'A', true],
  ['name', 'x'.repeat(100), true],
  ['name', '   ', false],
  ['name', 'x'.repeat(101), false],
  ['phone', '+44 (0)7700-900123', true],
  ['phone', '1234567', true],
  ['phone', '123456', false],
  ['phone', '07700 90012a', false],
  ['phone', '1'.repeat(21), false],
  ['phone', '+++ ()) 123456', false], // only six digits
  ['email', ' Sam@Example.COM ', true],
  ['email', 'sam', false],
  ['email', 'sam@example', false],
  ['email', 'sam@@example.com', false],
  ['email', '@example.com', false],
  ['email', 'sam @example.com', false],
  ['email', `${'x'.repeat(243)}@example.com`, false], // 255 characters
  ['registration', 'AB', true],
  ['registration', 'ab12 cde', true],
  ['registration', 'A', false],
  ['registration', 'ABCDEFGHJ', false],
  ['registration', 'AB-12', false],
  ['make', 'x'.repeat(50), true],
  ['make', '', false],
  ['model', 'x'.repeat(51), false],
  ['notes', '', true],
  ['notes', 'x'.repeat(1000), true],
  ['notes', 'x'.repeat(1001), false],
] as const)('%s %j valid: %s', (field, value, valid) => {
  const errors = errorsFor({ [field]: value })
  if (valid) expect(errors).toEqual({})
  else expect(Object.keys(errors)).toEqual([field])
})

it('counts characters, not UTF-16 units, like the backend', () => {
  expect(errorsFor({ name: '😀'.repeat(100) })).toEqual({})
})

it('uses the backend wording', () => {
  expect(errorsFor({ phone: '1' })).toEqual({ phone: 'Please enter a phone number we can call' })
  expect(errorsFor({ name: '' })).toEqual({ name: 'Please enter your name' })
})
