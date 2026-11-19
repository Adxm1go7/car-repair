import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { STAFF_ME, renderAt, stubFetch } from '../../testing/staffApi.tsx'
import type { StaffEnquiryRow } from '../types.ts'

const NEW: StaffEnquiryRow[] = [
  {
    id: 7,
    status: 'new',
    customer_name: 'Jane Smith',
    registration: 'AB12CDE',
    make: 'Ford',
    model: 'Focus',
    summary: 'Rattle from the front left when braking',
    created_at: '2026-11-18T09:00:00+00:00',
    handled_at: null,
  },
  {
    id: 8,
    status: 'new',
    customer_name: 'Sam Driver',
    registration: 'CD34EFG',
    make: 'Vauxhall',
    model: 'Corsa',
    summary: 'Engine light on',
    created_at: '2026-11-18T12:30:00+00:00',
    handled_at: null,
  },
]
const DECLINED: StaffEnquiryRow[] = [
  { ...NEW[0], id: 3, status: 'declined', handled_at: '2026-11-19T10:15:00+00:00' },
]

afterEach(() => vi.unstubAllGlobals())

it('lists new enquiries, oldest first', async () => {
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'GET /api/staff/enquiries?status=new': { status: 200, body: NEW },
  })
  renderAt('/staff/enquiries')
  expect(await screen.findByRole('heading', { level: 1, name: 'Enquiries' })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'New' })).toHaveAttribute('aria-selected', 'true')
  const list = await screen.findByRole('list', { name: 'Enquiries' })
  const rows = within(list).getAllByRole('listitem')
  expect(rows).toHaveLength(2)
  const first = within(rows[0])
  expect(first.getByRole('link', { name: 'Jane Smith' })).toHaveAttribute('href', '/staff/enquiries/7')
  expect(first.getByText('AB12CDE · Ford Focus')).toBeInTheDocument()
  expect(first.getByText('Rattle from the front left when braking')).toBeInTheDocument()
  expect(first.getByText('Sent Wed 18 Nov, 09:00')).toBeInTheDocument()
})

it('the tabs show booked and declined', async () => {
  const mock = stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'GET /api/staff/enquiries?status=new': { status: 200, body: NEW },
    'GET /api/staff/enquiries?status=declined': { status: 200, body: DECLINED },
    'GET /api/staff/enquiries?status=converted': { status: 200, body: [] },
  })
  renderAt('/staff/enquiries')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('tab', { name: 'Declined' }))
  expect(screen.getByRole('tab', { name: 'Declined' })).toHaveAttribute('aria-selected', 'true')
  expect(await screen.findByText('Handled Thu 19 Nov, 10:15')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Jane Smith' })).toHaveAttribute('href', '/staff/enquiries/3')
  expect(mock.mock.calls.some(([url]) => url === '/api/staff/enquiries?status=declined')).toBe(true)
  await user.click(screen.getByRole('tab', { name: 'Booked' }))
  expect(await screen.findByText('No booked enquiries.')).toBeInTheDocument()
})

it('opens on the tab named in the address', async () => {
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'GET /api/staff/enquiries?status=new': { status: 200, body: NEW },
    'GET /api/staff/enquiries?status=declined': { status: 200, body: [] },
  })
  renderAt('/staff/enquiries?status=declined')
  expect(await screen.findByText('No declined enquiries.')).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'Declined' })).toHaveAttribute('aria-selected', 'true')
})

it('says when there are no new enquiries', async () => {
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'GET /api/staff/enquiries?status=new': { status: 200, body: [] },
  })
  renderAt('/staff/enquiries')
  expect(await screen.findByText('No new enquiries.')).toBeInTheDocument()
})

it('the menu shows how many enquiries are new', async () => {
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'GET /api/staff/enquiries?status=new': { status: 200, body: NEW },
  })
  renderAt('/staff/enquiries')
  const nav = await screen.findByRole('navigation', { name: 'Staff' })
  expect(await within(nav).findByRole('link', { name: 'Enquiries (2)' })).toHaveAttribute('href', '/staff/enquiries')
})

it('the menu shows no count when none are new', async () => {
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'GET /api/staff/enquiries?status=new': { status: 200, body: [] },
  })
  renderAt('/staff/enquiries')
  const nav = await screen.findByRole('navigation', { name: 'Staff' })
  expect(await within(nav).findByRole('link', { name: 'Enquiries' })).toBeInTheDocument()
})
