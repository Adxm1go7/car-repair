import { afterEach, expect, it, vi } from 'vitest'
import { cancelHold, createHold, fetchBookingPolicy, fetchHoldStatus, payDemo, startCheckout } from './api.ts'
import type { CustomerDetails } from './types.ts'

function answer(status: number, body: unknown = {}): void {
  const response = status === 204 ? new Response(null, { status }) : new Response(JSON.stringify(body), { status })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
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

const CHECKOUT = { client_secret: 'cs_1_secret', demo_session: null, expires_in_seconds: 600, amount_pence: 2000 }

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

// --- checkout -----------------------------------------------------------------------

it('startCheckout sends the token with the details', async () => {
  answer(200, CHECKOUT)
  expect(await startCheckout('ABCD-EFGH', 'tok', DETAILS)).toEqual({ ok: true, data: CHECKOUT })
  const [url, init] = vi.mocked(fetch).mock.calls[0]
  expect(url).toBe('/api/holds/ABCD-EFGH/checkout')
  expect(init?.method).toBe('POST')
  expect(JSON.parse(String(init?.body))).toEqual({ hold_token: 'tok', ...DETAILS })
})

it('startCheckout maps a 410 to expired', async () => {
  answer(410, { detail: 'Your hold has expired' })
  expect(await startCheckout('ABCD-EFGH', 'tok', DETAILS)).toEqual({ ok: false, kind: 'expired' })
})

it('startCheckout maps a 409 to paid', async () => {
  answer(409, { detail: 'This booking is already paid' })
  expect(await startCheckout('ABCD-EFGH', 'tok', DETAILS)).toEqual({ ok: false, kind: 'paid' })
})

it('startCheckout gives the 503 message as an error', async () => {
  const detail = 'Payment is unavailable right now — please try again or call us'
  answer(503, { detail })
  expect(await startCheckout('ABCD-EFGH', 'tok', DETAILS)).toEqual({ ok: false, kind: 'error', detail })
})

it('a 422 gives an error carrying the detail', async () => {
  answer(422, { detail: 'phone: Please enter a phone number we can call' })
  expect(await startCheckout('ABCD-EFGH', 'tok', DETAILS)).toEqual({
    ok: false,
    kind: 'error',
    detail: 'phone: Please enter a phone number we can call',
  })
})

// --- status -------------------------------------------------------------------------

it('fetchHoldStatus posts the token in the body, never the URL', async () => {
  answer(200, { status: 'held', deposit_status: 'unpaid', summary: null })
  const result = await fetchHoldStatus('ABCD-EFGH', 'secret-token')
  expect(result).toEqual({ ok: true, data: { status: 'held', deposit_status: 'unpaid', summary: null } })
  const [url, init] = vi.mocked(fetch).mock.calls[0]
  expect(url).toBe('/api/holds/ABCD-EFGH/status')
  expect(String(url)).not.toContain('secret-token')
  expect(init?.method).toBe('POST')
  expect(JSON.parse(String(init?.body))).toEqual({ hold_token: 'secret-token' })
})

// --- release ------------------------------------------------------------------------

it.each([
  [204, 'released'],
  [404, 'released'],
  [409, 'paid'],
  [500, 'failed'],
] as const)('cancelHold maps %i to %s', async (status, outcome) => {
  answer(status)
  expect(await cancelHold('ABCD-EFGH', 'tok')).toBe(outcome)
})

it('cancelHold never throws, and asks the browser to finish the request', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
  await expect(cancelHold('ABCD-EFGH', 'tok')).resolves.toBe('failed')
  const [url, init] = vi.mocked(fetch).mock.calls[0]
  expect(url).toBe('/api/holds/ABCD-EFGH')
  expect(init).toMatchObject({ method: 'DELETE', keepalive: true })
})

// --- demo ---------------------------------------------------------------------------

it('payDemo posts the outcome', async () => {
  answer(200, { status: 'confirmed' })
  expect(await payDemo('demo_abc', 'pay')).toEqual({ ok: true, data: { status: 'confirmed' } })
  const [url, init] = vi.mocked(fetch).mock.calls[0]
  expect(url).toBe('/api/demo/checkout/demo_abc')
  expect(JSON.parse(String(init?.body))).toEqual({ outcome: 'pay' })
})

it('payDemo maps a 402 to declined', async () => {
  answer(402, { detail: 'Your card was declined (demo)' })
  expect(await payDemo('demo_abc', 'decline')).toEqual({ ok: false, kind: 'declined' })
})

it('a network failure gives an error without a detail', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
  expect(await fetchBookingPolicy()).toEqual({ ok: false, kind: 'error', detail: null })
})
