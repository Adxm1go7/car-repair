import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { ADMIN_ME, renderAt, stubFetch } from '../../testing/staffApi.tsx'
import type { AuditEntry, AuditPage, TeamMember } from '../types.ts'

const TEAM: TeamMember[] = [
  { id: 1, name: 'Alex Admin', email: 'alex@example.com', role: 'admin', state: 'active' },
  { id: 2, name: 'Sam Staff', email: 'sam@example.com', role: 'staff', state: 'active' },
]

function entry(overrides: Partial<AuditEntry>): AuditEntry {
  return {
    at: '2026-11-17T09:30:00+00:00',
    staff_name: 'Sam Staff',
    action: 'booking.move',
    entity_type: 'booking',
    entity_id: 7,
    booking_reference: 'ABCD-EFGH',
    before: null,
    after: null,
    reason: null,
    ...overrides,
  }
}

function page(entries: AuditEntry[], number: number, hasMore: boolean): AuditPage {
  return { entries, page: number, has_more: hasMore }
}

const FIRST = page(
  [
    entry({ reason: 'Customer asked' }),
    entry({ at: '2026-11-16T14:05:00+00:00', action: 'booking.status', after: { status: 'in_progress' } }),
  ],
  1,
  true,
)
const SECOND = page([entry({ at: '2026-11-10T08:00:00+00:00', action: 'booking.create' })], 2, false)

function stubAudit(routes: Record<string, { status: number; body?: unknown }> = {}) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: ADMIN_ME },
    'GET /api/staff/team': { status: 200, body: TEAM },
    'GET /api/staff/audit?page=1': {
      status: 200,
      body: page([entry({ action: 'staff.invite', entity_type: 'staff_user', booking_reference: null, after: { name: 'Jo Bloggs' } })], 1, false),
    },
    ...routes,
  })
}

afterEach(() => vi.unstubAllGlobals())

it('shows the newest changes with readable actions', async () => {
  stubAudit({ 'GET /api/staff/audit?page=1': { status: 200, body: FIRST } })
  renderAt('/staff/audit')
  expect(await screen.findByRole('heading', { level: 1, name: 'Audit log' })).toBeInTheDocument()

  const rows = await screen.findAllByRole('listitem')
  expect(rows).toHaveLength(2)
  expect(within(rows[0]).getByText('17 Nov 2026, 09:30')).toBeInTheDocument()
  expect(within(rows[0]).getByText('Sam Staff')).toBeInTheDocument()
  expect(within(rows[0]).getByText('Moved booking')).toBeInTheDocument()
  expect(within(rows[0]).getByRole('link', { name: 'ABCD-EFGH' })).toHaveAttribute('href', '/staff/bookings/ABCD-EFGH')
  expect(within(rows[0]).getByText('“Customer asked”')).toBeInTheDocument()
  expect(within(rows[1]).getByText('Status changed to In progress')).toBeInTheDocument()
})

it('names the account for staff changes', async () => {
  stubAudit()
  renderAt('/staff/audit')
  expect(await screen.findByText('Invited Jo Bloggs')).toBeInTheDocument()
  expect(within(screen.getByRole('list', { name: 'Changes' })).queryByRole('link')).not.toBeInTheDocument()
})

it('audit filters by reference and pages', async () => {
  const mock = stubAudit({
    'GET /api/staff/audit?reference=ABCD-EFGH&page=1': { status: 200, body: FIRST },
    'GET /api/staff/audit?reference=ABCD-EFGH&page=2': { status: 200, body: SECOND },
  })
  renderAt('/staff/audit')
  await screen.findByText('Invited Jo Bloggs')
  expect(screen.queryByRole('button', { name: 'Newer' })).not.toBeInTheDocument()

  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Booking reference'), 'abcd-efgh')
  await user.click(screen.getByRole('button', { name: 'Show' }))

  expect(await screen.findByText('Moved booking')).toBeInTheDocument()
  expect(screen.getByText('Page 1')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Older' }))

  expect(await screen.findByText('Phone booking')).toBeInTheDocument()
  expect(screen.getByText('Page 2')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Older' })).not.toBeInTheDocument()
  expect(mock.mock.calls.map(([url]) => url)).toContain('/api/staff/audit?reference=ABCD-EFGH&page=2')

  await user.click(screen.getByRole('button', { name: 'Newer' }))
  expect(await screen.findByText('Moved booking')).toBeInTheDocument()
})

it('filters by dates and staff member', async () => {
  const mock = stubAudit({
    'GET /api/staff/audit?from=2026-11-01&to=2026-11-17&staff=2&page=1': { status: 200, body: page([], 1, false) },
  })
  renderAt('/staff/audit')
  expect(await screen.findByRole('option', { name: 'Sam Staff' })).toBeInTheDocument()

  fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-11-01' } })
  fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-11-17' } })
  const user = userEvent.setup()
  await user.selectOptions(screen.getByLabelText('Staff member'), 'Sam Staff')
  await user.click(screen.getByRole('button', { name: 'Show' }))

  expect(await screen.findByText('No changes match these filters.')).toBeInTheDocument()
  expect(mock.mock.calls.map(([url]) => url)).toContain('/api/staff/audit?from=2026-11-01&to=2026-11-17&staff=2&page=1')
})

it('shows a message when the log cannot load', async () => {
  stubAudit({ 'GET /api/staff/audit?page=1': { status: 500 } })
  renderAt('/staff/audit')
  expect(await screen.findByRole('alert')).toHaveTextContent("Sorry, we couldn't load the audit log.")
})

it('audit describes settings changes', async () => {
  const settings = (action: string, before: Record<string, unknown> | null, after: Record<string, unknown> | null) =>
    entry({ action, entity_type: 'settings', booking_reference: null, before, after })
  const hours = { starts_on: '2026-12-01', days: [] }
  const cases: [AuditEntry, string][] = [
    [settings('service.create', null, { name: 'MOT test' }), 'Added service MOT test'],
    [settings('service.update', { name: 'MOT test' }, { name: 'MOT test' }), 'Changed service MOT test'],
    [settings('service.update', { name: 'MOT test' }, { name: 'MOT' }), 'Renamed service MOT test to MOT'],
    [settings('service.hide', { name: 'Diagnostic check' }, { name: 'Diagnostic check' }), 'Hid service Diagnostic check'],
    [settings('service.show', { name: 'Diagnostic check' }, { name: 'Diagnostic check' }), 'Showed service Diagnostic check'],
    [settings('service.move', { name: 'MOT test', position: 2 }, { name: 'MOT test', position: 1 }), 'Moved service MOT test up'],
    [settings('service.move', { name: 'MOT test', position: 1 }, { name: 'MOT test', position: 2 }), 'Moved service MOT test down'],
    [settings('bay.create', null, { name: 'Bay 3' }), 'Added bay Bay 3'],
    [settings('bay.rename', { name: 'Bay 3' }, { name: 'Front bay' }), 'Renamed bay Bay 3 to Front bay'],
    [settings('bay.out_of_use', { name: 'Bay 3' }, { name: 'Bay 3' }), 'Took Bay 3 out of use'],
    [settings('bay.back_in_use', { name: 'Bay 3' }, { name: 'Bay 3' }), 'Put Bay 3 back in use'],
    [settings('bay_type.create', null, { name: 'Tyre bay' }), 'Added bay type Tyre bay'],
    [settings('hours.create', null, hours), 'New hours from Tue 1 Dec'],
    [settings('hours.update', hours, hours), 'Changed hours from Tue 1 Dec'],
    [settings('hours.delete', hours, null), 'Deleted hours from Tue 1 Dec'],
    [settings('contact.update', {}, {}), 'Changed contact details'],
  ]
  stubAudit({ 'GET /api/staff/audit?page=1': { status: 200, body: page(cases.map(([e]) => e), 1, false) } })
  renderAt('/staff/audit')
  const rows = await screen.findAllByRole('listitem')
  expect(rows).toHaveLength(cases.length)
  cases.forEach(([, words], index) => {
    expect(within(rows[index]).getByText(words)).toBeInTheDocument()
  })
})
