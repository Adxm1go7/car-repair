import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import type { OpeningDay } from '../../catalogue/types.ts'
import type { Reply } from '../../testing/staffApi.tsx'
import { ADMIN_ME, renderAt, stubFetch } from '../../testing/staffApi.tsx'
import type { AdminTimetable } from '../types.ts'

const URL = '/api/staff/settings/hours'

function weekday(weekday: number): OpeningDay {
  if (weekday < 5) return { weekday, open: '08:00', close: '17:30', breaks: [{ start: '12:30', end: '13:00' }] }
  if (weekday === 5) return { weekday, open: '09:00', close: '14:00', breaks: [] }
  return { weekday, open: '10:00', close: '13:00', breaks: [] }
}

const SEED_WEEK = Array.from({ length: 7 }, (_, d) => weekday(d))
const WINTER_WEEK: OpeningDay[] = SEED_WEEK.map((day) =>
  day.weekday < 5
    ? { ...day, close: '17:00' }
    : { weekday: day.weekday, open: null, close: null, breaks: [] },
)

const FIRST: AdminTimetable = { id: 1, starts_on: '2000-01-01', state: 'current', days: SEED_WEEK }
const WINTER: AdminTimetable = { id: 2, starts_on: '2030-12-03', state: 'future', days: WINTER_WEEK }

function stub(routes: Record<string, Reply> = {}) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: ADMIN_ME },
    [`GET ${URL}`]: { status: 200, body: [FIRST, WINTER] },
    ...routes,
  })
}

function bodyOf(mock: ReturnType<typeof stubFetch>, url: string, method: string): unknown {
  const call = mock.mock.calls.find(([u, init]) => u === url && init?.method === method)
  if (!call) throw new Error(`no ${method} ${url}`)
  return JSON.parse(String(call[1]?.body))
}

function sent(mock: ReturnType<typeof stubFetch>, url: string, method: string): boolean {
  return mock.mock.calls.some(([u, init]) => u === url && init?.method === method)
}

async function timetable(name: string): Promise<HTMLElement> {
  return screen.findByRole('listitem', { name })
}

/** Sets a time or date input, as picking it in the browser would. */
function pick(input: HTMLElement, value: string): void {
  fireEvent.change(input, { target: { value } })
}

afterEach(() => vi.unstubAllGlobals())

it('lists timetables with edit only on future ones', async () => {
  stub()
  renderAt('/staff/settings/hours')
  const now = await timetable('Now (since the start)')
  expect(now).toHaveTextContent('Mon–Fri 08:00–17:30, break 12:30–13:00 · Sat 09:00–14:00 · Sun 10:00–13:00')
  expect(within(now).queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  expect(within(now).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  const winter = await timetable('From Tue 3 Dec')
  expect(winter).toHaveTextContent('Mon–Fri 08:00–17:00, break 12:30–13:00 · Sat–Sun closed')
  expect(within(winter).getByRole('button', { name: 'Edit' })).toBeInTheDocument()
  expect(within(winter).getByRole('button', { name: 'Delete' })).toBeInTheDocument()
})

it('a later current timetable is labelled with its date', async () => {
  stub({
    [`GET ${URL}`]: {
      status: 200,
      body: [
        { ...FIRST, state: 'past' },
        { ...WINTER, starts_on: '2026-11-02', state: 'current' },
      ],
    },
  })
  renderAt('/staff/settings/hours')
  expect(await timetable('Now (from Mon 2 Nov)')).toBeInTheDocument()
  expect(await timetable('From the start (past)')).toBeInTheDocument()
})

it('new hours prefill from the timetable before', async () => {
  const created: AdminTimetable = { id: 3, starts_on: '2031-01-07', state: 'future', days: WINTER_WEEK }
  const mock = stub({ [`POST ${URL}`]: { status: 201, body: created } })
  renderAt('/staff/settings/hours')
  await timetable('Now (since the start)')
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '+ New hours from a date' }))
  const form = screen.getByRole('form', { name: 'New hours' })

  // Before the winter hours: the seed week.
  pick(within(form).getByLabelText('Starts on'), '2030-12-01')
  expect(within(form).getByLabelText('Saturday opens')).toHaveValue('09:00')
  // After them: the winter week, Saturday closed.
  pick(within(form).getByLabelText('Starts on'), '2031-01-07')
  expect(within(form).getByLabelText('Open on Saturday')).not.toBeChecked()
  expect(within(form).getByLabelText('Monday closes')).toHaveValue('17:00')

  await user.click(within(form).getByRole('button', { name: 'Save' }))
  await user.click(within(form).getByRole('button', { name: 'Yes, save' }))
  expect(await timetable('From Tue 7 Jan')).toBeInTheDocument()
  expect(bodyOf(mock, URL, 'POST')).toEqual({ starts_on: '2031-01-07', days: WINTER_WEEK })
  expect(screen.getByRole('status')).toHaveTextContent('New hours from Tue 7 Jan saved')
})

it('a closed day hides its times', async () => {
  stub()
  renderAt('/staff/settings/hours')
  await timetable('Now (since the start)')
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '+ New hours from a date' }))
  const form = screen.getByRole('form', { name: 'New hours' })
  pick(within(form).getByLabelText('Starts on'), '2030-12-01')
  expect(within(form).getByLabelText('Monday opens')).toBeInTheDocument()
  await user.click(within(form).getByLabelText('Open on Monday'))
  expect(within(form).queryByLabelText('Monday opens')).not.toBeInTheDocument()
  expect(within(form).queryByLabelText('Monday break 1 starts')).not.toBeInTheDocument()
  await user.click(within(form).getByLabelText('Open on Monday'))
  expect(within(form).getByLabelText('Monday opens')).toHaveValue('08:00')
})

it('edits breaks and checks the hours before sending', async () => {
  const mock = stub()
  renderAt('/staff/settings/hours')
  await timetable('Now (since the start)')
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '+ New hours from a date' }))
  const form = screen.getByRole('form', { name: 'New hours' })
  pick(within(form).getByLabelText('Starts on'), '2030-12-01')
  await user.click(within(form).getByRole('button', { name: 'Add a break on Saturday' }))
  pick(within(form).getByLabelText('Saturday break 1 starts'), '13:30')
  pick(within(form).getByLabelText('Saturday break 1 ends'), '15:00')
  await user.click(within(form).getByRole('button', { name: 'Remove Monday break 1' }))
  expect(within(form).queryByLabelText('Monday break 1 starts')).not.toBeInTheDocument()
  await user.click(within(form).getByRole('button', { name: 'Save' }))
  expect(within(form).getByText('Saturday: breaks must be inside the hours and not overlap')).toBeInTheDocument()
  expect(within(form).queryByRole('button', { name: 'Yes, save' })).not.toBeInTheDocument()
  expect(sent(mock, URL, 'POST')).toBe(false)
})

it('a clash lists the bookings and saves nothing', async () => {
  const mock = stub({
    [`PUT ${URL}/2`]: {
      status: 409,
      body: {
        detail: 'clashes',
        bookings: [{ reference: 'ABCD-EFGH', start: '2030-12-03T16:30:00+00:00', bay: 'MOT bay', held: false }],
      },
    },
  })
  renderAt('/staff/settings/hours')
  const user = userEvent.setup()
  const winter = await timetable('From Tue 3 Dec')
  await user.click(within(winter).getByRole('button', { name: 'Edit' }))
  const form = screen.getByRole('form', { name: 'Edit hours from Tue 3 Dec' })
  expect(within(form).queryByLabelText('Starts on')).not.toBeInTheDocument()
  pick(within(form).getByLabelText('Tuesday closes'), '16:00')
  await user.click(within(form).getByRole('button', { name: 'Save' }))
  await user.click(within(form).getByRole('button', { name: 'Yes, save' }))

  const clashes = await within(form).findByRole('list', { name: 'Bookings in the way' })
  expect(within(clashes).getByRole('link', { name: 'ABCD-EFGH' })).toHaveAttribute('href', '/staff/bookings/ABCD-EFGH')
  expect(within(clashes).getByText(/Tue 3 Dec 16:30/)).toBeInTheDocument()
  const put = bodyOf(mock, `${URL}/2`, 'PUT') as { days: OpeningDay[] }
  expect(put.days[1]).toEqual({ ...WINTER_WEEK[1], close: '16:00' })
  // Nothing saved: the list still shows the old hours, and the form stays open.
  expect(winter).toHaveTextContent('Mon–Fri 08:00–17:00')
  expect(screen.getByRole('form', { name: 'Edit hours from Tue 3 Dec' })).toBeInTheDocument()
})

it('delete asks to confirm', async () => {
  const mock = stub({ [`DELETE ${URL}/2`]: { status: 204 } })
  renderAt('/staff/settings/hours')
  const user = userEvent.setup()
  const winter = await timetable('From Tue 3 Dec')
  await user.click(within(winter).getByRole('button', { name: 'Delete' }))
  expect(within(winter).getByText(/the hours before carry on/i)).toBeInTheDocument()
  expect(sent(mock, `${URL}/2`, 'DELETE')).toBe(false)
  await user.click(within(winter).getByRole('button', { name: 'Yes, delete' }))
  await vi.waitFor(() => expect(screen.queryByRole('listitem', { name: 'From Tue 3 Dec' })).not.toBeInTheDocument())
  expect(screen.getByRole('status')).toHaveTextContent('Deleted the hours from Tue 3 Dec')
})

it('a refused delete lists the bookings', async () => {
  stub({
    [`DELETE ${URL}/2`]: {
      status: 409,
      body: {
        detail: 'clashes',
        bookings: [{ reference: 'WXYZ-1234', start: '2030-12-07T11:00:00+00:00', bay: 'Bay 1', held: true }],
      },
    },
  })
  renderAt('/staff/settings/hours')
  const user = userEvent.setup()
  const winter = await timetable('From Tue 3 Dec')
  await user.click(within(winter).getByRole('button', { name: 'Delete' }))
  await user.click(within(winter).getByRole('button', { name: 'Yes, delete' }))
  const clashes = await within(winter).findByRole('list', { name: 'Bookings in the way' })
  expect(within(clashes).getByText(/being paid for/)).toBeInTheDocument()
})
