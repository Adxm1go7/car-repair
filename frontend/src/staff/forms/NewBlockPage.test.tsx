import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { DAY_SCHEDULE, scheduleUrl } from '../../testing/schedule.ts'
import type { Reply } from '../../testing/staffApi.tsx'
import { STAFF_ME, renderAt, sentBody, stubFetch } from '../../testing/staffApi.tsx'

const CLASHES = {
  detail: 'clashes',
  bookings: [
    { reference: 'ABCD-EFGH', start: '2026-11-17T09:30:00+00:00', bay: 'MOT bay' },
    { reference: 'WXYZ-1234', start: '2026-11-17T14:00:00+00:00', bay: 'Bay 1' },
  ],
  blocks: [{ id: 4, note: 'Lift repair' }],
}

function stubBlock(post: Reply = { status: 201, body: { id: 12 } }) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    [`GET ${scheduleUrl('2026-11-17', 1)}`]: { status: 200, body: DAY_SCHEDULE },
    'POST /api/staff/blocks': post,
  })
}

function posted(mock: ReturnType<typeof stubFetch>): boolean {
  return mock.mock.calls.some(([url, init]) => url === '/api/staff/blocks' && init?.method === 'POST')
}

afterEach(() => vi.unstubAllGlobals())

it('adds a block on all bays and returns to the day', async () => {
  const mock = stubBlock()
  renderAt('/staff/blocks/new?date=2026-11-17')
  expect(await screen.findByRole('heading', { level: 1, name: 'Block time' })).toBeInTheDocument()
  expect(await screen.findByRole('option', { name: 'MOT bay' })).toBeInTheDocument()
  expect(screen.getByLabelText('Bay')).toHaveValue('')
  expect(screen.getByLabelText('Start date')).toHaveValue('2026-11-17')
  expect(screen.getByLabelText('End date')).toHaveValue('2026-11-17')

  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Note'), 'Staff training')
  await user.click(screen.getByRole('button', { name: 'Block time' }))

  expect(await screen.findByRole('heading', { level: 1, name: 'Tue 17 Nov' })).toBeInTheDocument()
  expect(sentBody(mock, '/api/staff/blocks')).toEqual({
    bay_id: null,
    start: '2026-11-17T08:00:00.000Z',
    end: '2026-11-17T17:30:00.000Z',
    note: 'Staff training',
  })
})

it('blocks one bay, chosen from the link or the select, in garage time', async () => {
  const mock = stubBlock()
  renderAt('/staff/blocks/new?date=2026-11-17&bay=2')
  expect(await screen.findByRole('option', { name: 'Bay 1' })).toBeInTheDocument()
  expect(screen.getByLabelText('Bay')).toHaveValue('2')

  fireEvent.change(screen.getByLabelText('Start date'), { target: { value: '2026-06-17' } })
  fireEvent.change(screen.getByLabelText('Start time'), { target: { value: '09:00' } })
  fireEvent.change(screen.getByLabelText('End date'), { target: { value: '2026-06-18' } })
  fireEvent.change(screen.getByLabelText('End time'), { target: { value: '12:00' } })
  const user = userEvent.setup()
  await user.selectOptions(screen.getByLabelText('Bay'), 'MOT bay')
  await user.type(screen.getByLabelText('Note'), 'Lift broken')
  await user.click(screen.getByRole('button', { name: 'Block time' }))

  await screen.findByRole('heading', { level: 1, name: 'Wed 17 Jun' })
  // June is British Summer Time: 09:00 there is 08:00 UTC.
  expect(sentBody(mock, '/api/staff/blocks')).toEqual({
    bay_id: 1,
    start: '2026-06-17T08:00:00.000Z',
    end: '2026-06-18T11:00:00.000Z',
    note: 'Lift broken',
  })
})

it('block note is required', async () => {
  const mock = stubBlock()
  renderAt('/staff/blocks/new?date=2026-11-17')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Block time' }))
  expect(screen.getByText('Please say what the block is for')).toBeInTheDocument()

  await user.type(screen.getByLabelText('Note'), '   ')
  await user.click(screen.getByRole('button', { name: 'Block time' }))
  expect(screen.getByText('Please say what the block is for')).toBeInTheDocument()
  expect(posted(mock)).toBe(false)
})

it('the end must be after the start', async () => {
  const mock = stubBlock()
  renderAt('/staff/blocks/new?date=2026-11-17')
  fireEvent.change(await screen.findByLabelText('End time'), { target: { value: '08:00' } })
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Note'), 'Holiday')
  await user.click(screen.getByRole('button', { name: 'Block time' }))
  expect(screen.getByText('The end must be after the start')).toBeInTheDocument()
  expect(posted(mock)).toBe(false)
})

it('block form lists clashing bookings with links', async () => {
  stubBlock({ status: 409, body: CLASHES })
  renderAt('/staff/blocks/new?date=2026-11-17')
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Note'), 'Holiday')
  await user.click(screen.getByRole('button', { name: 'Block time' }))

  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('Call these customers and move or cancel their bookings first.')
  const links = within(alert).getAllByRole('link')
  expect(links.map((l) => l.getAttribute('href'))).toEqual(['/staff/bookings/ABCD-EFGH', '/staff/bookings/WXYZ-1234'])
  expect(links[0]).toHaveTextContent('ABCD-EFGH · Tue 17 Nov 09:30 · MOT bay')
  expect(within(alert).getByText('Already blocked: Lift repair')).toBeInTheDocument()
})

it("shows the server's message for a refused block", async () => {
  stubBlock({ status: 422, body: { detail: 'Unknown bay' } })
  renderAt('/staff/blocks/new?date=2026-11-17')
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Note'), 'Holiday')
  await user.click(screen.getByRole('button', { name: 'Block time' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Unknown bay')
})
