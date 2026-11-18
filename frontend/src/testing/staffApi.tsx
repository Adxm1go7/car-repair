import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { App } from '../App.tsx'
import type { StaffMe } from '../staff/types.ts'
import { GARAGE } from './fixtures.ts'

export const STAFF_ME: StaffMe = { id: 2, name: 'Sam Staff', email: 'sam@example.com', role: 'staff' }
export const ADMIN_ME: StaffMe = { id: 1, name: 'Alex Admin', email: 'alex@example.com', role: 'admin' }

/** A reply with a JSON body, or 'never' for a request that never answers. */
export type Reply = { status: number; body?: unknown } | 'never'

/**
 * Answers fetches by "METHOD /url" (or just "/url" for any method). Unlisted URLs get a 404,
 * except /api/garage, which answers with the fixture unless listed. Returns the mock.
 */
export function stubFetch(routes: Record<string, Reply>) {
  const all: Record<string, Reply> = { '/api/garage': { status: 200, body: GARAGE }, ...routes }
  const mock = vi.fn((url: string, init?: RequestInit) => {
    const reply = all[`${init?.method ?? 'GET'} ${url}`] ?? all[url]
    if (reply === 'never') return new Promise<Response>(() => {})
    if (!reply) return Promise.resolve(new Response('{}', { status: 404 }))
    const body = reply.body === undefined ? null : JSON.stringify(reply.body)
    return Promise.resolve(new Response(body, { status: reply.status }))
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

/** The JSON body sent with the first call to `url`. */
export function sentBody(mock: ReturnType<typeof stubFetch>, url: string): unknown {
  const call = mock.mock.calls.find(([called]) => called === url)
  if (!call) throw new Error(`no call to ${url}`)
  return JSON.parse(String(call[1]?.body))
}

/** Renders the whole app at `entry`, as the browser would. */
export function renderAt(entry: string): void {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <App />
    </MemoryRouter>,
  )
}

/** The day view's and week view's page headings, e.g. "Tue 17 Nov" and "Week of 16 Nov". */
export const DAY_HEADING = /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2}$/
export const WEEK_HEADING = /^Week of /
