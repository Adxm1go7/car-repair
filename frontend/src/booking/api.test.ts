import { afterEach, expect, it, vi } from 'vitest'
import { cancelHold, confirmHold, createHold, fetchBookingPolicy } from './api.ts'
import type { CustomerDetails } from './types.ts'

function answer(status: number, body: unknown = {}): void {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })))
}

const DETAILS: CustomerDetails = {
  name: 'Sam Driver',
  phone: '07700 900123',
  email: 'sam@example.com',
  registration: 'AB12CDE',
  make: 'Ford',
  model: 'Focus',
  notes: '',
}

afterEach(() => vi.unstubAllGlobals())

it('createHold posts the services and start', async () => {
  answer(201, { reference: 'ABCD-EFGH' })
  const result = await createHold(['mot-test'], '2026-11-10T08:00:00+00:00')
  expect(result).toEqual({ ok: true, data: { reference: 'ABCD-EFGH' } })
  expect(fetch).toHaveBeenCalledWith('/api/holds', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ services: ['mot-test'], start: '2026-11-10T08:00:00+00:00' }),
  })
})

it('createHold maps a 409 to taken', async () => {
  answer(409, { detail: 'That time has just been taken' })
  expect(await createHold(['mot-test'], 'x')).toEqual({ ok: false, kind: 'taken' })
})

it('confirmHold maps a 410 to expired', async () => {
  answer(410, { detail: 'Your hold has expired' })
  expect(await confirmHold('ABCD-EFGH', 'tok', DETAILS)).toEqual({ ok: false, kind: 'expired' })
})

it('confirmHold sends the token with the details', async () => {
  answer(200, { reference: 'ABCD-EFGH' })
  await confirmHold('ABCD-EFGH', 'tok', DETAILS)
  const [url, init] = vi.mocked(fetch).mock.calls[0]
  expect(url).toBe('/api/holds/ABCD-EFGH/confirm')
  expect(JSON.parse(String(init?.body))).toEqual({ hold_token: 'tok', ...DETAILS })
})

it('a 422 gives an error carrying the detail', async () => {
  answer(422, { detail: 'phone: Please enter a phone number we can call' })
  expect(await confirmHold('ABCD-EFGH', 'tok', DETAILS)).toEqual({
    ok: false,
    kind: 'error',
    detail: 'phone: Please enter a phone number we can call',
  })
})

it('a network failure gives an error without a detail', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
  expect(await fetchBookingPolicy()).toEqual({ ok: false, kind: 'error', detail: null })
})

it('cancelHold never throws', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
  await expect(cancelHold('ABCD-EFGH', 'tok')).resolves.toBeUndefined()
})
