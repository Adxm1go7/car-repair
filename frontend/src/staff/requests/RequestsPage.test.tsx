import { screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { STAFF_ME, renderAt, stubFetch } from '../../testing/staffApi.tsx'
import type { StaffRequest } from '../types.ts'

const REQUESTS: StaffRequest[] = [
  {
    reference: 'REQU-ESTA',
    customer_name: 'Jane Smith',
    services: ['Clutch replacement'],
    start: '2026-11-20T09:00:00+00:00',
    bay: 'Bay 1',
    deadline: '2026-11-18T09:00:00+00:00',
    created_at: '2026-11-16T09:00:00+00:00',
  },
  {
    reference: 'REQU-ESTB',
    customer_name: 'Sam Driver',
    services: ['Diagnostic check'],
    start: '2026-11-21T13:30:00+00:00',
    bay: 'Bay 2',
    deadline: '2026-11-18T12:00:00+00:00',
    created_at: '2026-11-16T12:00:00+00:00',
  },
]

afterEach(() => vi.unstubAllGlobals())

it('lists the requests waiting, oldest first', async () => {
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'GET /api/staff/requests': { status: 200, body: REQUESTS },
  })
  renderAt('/staff/requests')
  expect(await screen.findByRole('heading', { level: 1, name: 'Requests' })).toBeInTheDocument()
  const rows = await screen.findAllByRole('listitem')
  expect(rows).toHaveLength(2)
  const first = within(rows[0])
  expect(first.getByRole('link', { name: 'REQU-ESTA' })).toHaveAttribute('href', '/staff/bookings/REQU-ESTA')
  expect(first.getByText('Jane Smith')).toBeInTheDocument()
  expect(first.getByText('Clutch replacement')).toBeInTheDocument()
  expect(first.getByText('Fri 20 Nov, 09:00 · Bay 1')).toBeInTheDocument()
  expect(first.getByText('Reply by Wed 18 Nov, 09:00')).toBeInTheDocument()
})

it('says when nothing is waiting', async () => {
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'GET /api/staff/requests': { status: 200, body: [] },
  })
  renderAt('/staff/requests')
  expect(await screen.findByText('No requests waiting.')).toBeInTheDocument()
})

it('the staff menu shows how many requests are waiting', async () => {
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'GET /api/staff/requests': { status: 200, body: REQUESTS },
  })
  renderAt('/staff/requests')
  const nav = await screen.findByRole('navigation', { name: 'Staff' })
  expect(await within(nav).findByRole('link', { name: 'Requests (2)' })).toHaveAttribute('href', '/staff/requests')
})

it('the menu shows no count when none are waiting', async () => {
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'GET /api/staff/requests': { status: 200, body: [] },
  })
  renderAt('/staff/requests')
  const nav = await screen.findByRole('navigation', { name: 'Staff' })
  expect(await within(nav).findByRole('link', { name: 'Requests' })).toBeInTheDocument()
})
