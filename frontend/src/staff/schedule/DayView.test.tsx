import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { DAY_SCHEDULE, bookingItem, scheduleUrl } from '../../testing/schedule.ts'
import { STAFF_ME, renderAt, stubFetch } from '../../testing/staffApi.tsx'

/** Makes matchMedia answer as a phone (narrow) or a desktop. */
function stubScreen(narrow: boolean): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: narrow,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })),
  )
}

function stubDay(extra = {}) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    [scheduleUrl('2026-11-17', 1)]: { status: 200, body: DAY_SCHEDULE },
    ...extra,
  })
}

function scheduleCalls(mock: ReturnType<typeof stubFetch>): string[] {
  return mock.mock.calls.map(([url]) => url).filter((url) => url.startsWith('/api/staff/schedule'))
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('day view groups by bay and links bookings', async () => {
  stubScreen(false)
  stubDay()
  renderAt('/staff?date=2026-11-17')

  expect(await screen.findByRole('heading', { level: 1, name: 'Tue 17 Nov' })).toBeInTheDocument()
  const mot = await screen.findByRole('region', { name: 'MOT bay' })
  const bay1 = screen.getByRole('region', { name: 'Bay 1' })

  const online = within(mot).getByRole('link', { name: /AB12CDE/ })
  expect(online).toHaveAttribute('href', '/staff/bookings/ABCD-EFGH')
  expect(online).toHaveTextContent('09:30–10:30')
  expect(online).toHaveTextContent('MOT test')
  expect(online).toHaveTextContent('Confirmed')
  expect(within(mot).getByText('Blocked: Lift repair')).toBeInTheDocument()

  const phone = within(bay1).getByRole('link', { name: /CD34EFG/ })
  expect(phone).toHaveAttribute('href', '/staff/bookings/PHON-EONE')
  expect(phone).toHaveTextContent('Full service, Brake check')
  expect(phone).toHaveTextContent('In progress')
  expect(phone).toHaveTextContent('Phone booking · no deposit')
  expect(phone).toHaveTextContent('No email, phone only')
  expect(within(mot).queryByRole('link', { name: /CD34EFG/ })).not.toBeInTheDocument()
})

it('held booking is not a link', async () => {
  stubScreen(false)
  stubDay()
  renderAt('/staff?date=2026-11-17')
  const bay1 = await screen.findByRole('region', { name: 'Bay 1' })
  expect(within(bay1).getByText(/EF56GHI/)).toBeInTheDocument()
  expect(within(bay1).getByText('Being booked')).toBeInTheDocument()
  expect(within(bay1).queryByRole('link', { name: /EF56GHI/ })).not.toBeInTheDocument()
})

it('day view on a narrow screen shows bay tabs', async () => {
  stubScreen(true)
  stubDay()
  renderAt('/staff?date=2026-11-17')

  const tabs = await screen.findAllByRole('tab')
  expect(tabs.map((t) => t.textContent)).toEqual(['MOT bay', 'Bay 1'])
  expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
  const panel = screen.getByRole('tabpanel')
  expect(within(panel).getByRole('link', { name: /AB12CDE/ })).toBeInTheDocument()
  expect(within(panel).getByText('Closed 12:30–13:00')).toBeInTheDocument()
  expect(within(panel).queryByRole('link', { name: /CD34EFG/ })).not.toBeInTheDocument()

  await userEvent.setup().click(tabs[1])
  const bay1 = screen.getByRole('tabpanel')
  expect(within(bay1).getByRole('link', { name: /CD34EFG/ })).toBeInTheDocument()
  expect(within(bay1).queryByRole('link', { name: /AB12CDE/ })).not.toBeInTheDocument()
})

it('has new booking and block time links for the day', async () => {
  stubScreen(false)
  stubDay()
  renderAt('/staff?date=2026-11-17')
  expect(await screen.findByRole('link', { name: '+ New booking' })).toHaveAttribute(
    'href',
    '/staff/bookings/new?date=2026-11-17',
  )
  expect(screen.getByRole('link', { name: '+ Block time' })).toHaveAttribute('href', '/staff/blocks/new?date=2026-11-17')
})

it('prev and next change the date', async () => {
  stubScreen(false)
  const mock = stubDay({
    [scheduleUrl('2026-11-18', 1)]: { status: 200, body: { ...DAY_SCHEDULE, days: [], items: [] } },
    [scheduleUrl('2026-11-16', 1)]: { status: 200, body: { ...DAY_SCHEDULE, days: [], items: [] } },
  })
  renderAt('/staff?date=2026-11-17')
  await screen.findByRole('region', { name: 'MOT bay' })

  const user = userEvent.setup()
  await user.click(screen.getByRole('link', { name: 'Next day' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Wed 18 Nov' })).toBeInTheDocument()
  await user.click(screen.getByRole('link', { name: 'Previous day' }))
  await user.click(screen.getByRole('link', { name: 'Previous day' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Mon 16 Nov' })).toBeInTheDocument()
  expect(scheduleCalls(mock)).toContain(scheduleUrl('2026-11-18', 1))
  expect(scheduleCalls(mock)).toContain(scheduleUrl('2026-11-16', 1))
})

it("defaults to today in the garage's zone", async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-11-17T08:00:00Z'))
  stubScreen(false)
  const mock = stubDay()
  renderAt('/staff')
  expect(await screen.findByRole('heading', { level: 1, name: 'Tue 17 Nov' })).toBeInTheDocument()
  expect(scheduleCalls(mock)).toContain(scheduleUrl('2026-11-17', 1))
})

it('refreshes after 30 seconds', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  stubScreen(false)
  const mock = stubDay()
  renderAt('/staff?date=2026-11-17')
  await screen.findByRole('region', { name: 'MOT bay' })
  expect(scheduleCalls(mock)).toHaveLength(1)

  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000)
  })
  expect(scheduleCalls(mock)).toHaveLength(2)
})

it('does not refresh while the page is hidden', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  stubScreen(false)
  const mock = stubDay()
  renderAt('/staff?date=2026-11-17')
  await screen.findByRole('region', { name: 'MOT bay' })

  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000)
  })
  expect(scheduleCalls(mock)).toHaveLength(1)
})

it('shows an error when the schedule fails to load', async () => {
  stubScreen(false)
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    [scheduleUrl('2026-11-17', 1)]: { status: 503, body: { detail: 'Schedule unavailable' } },
  })
  renderAt('/staff?date=2026-11-17')
  expect(await screen.findByRole('alert')).toHaveTextContent("couldn't load the schedule")
})

it('remove block asks to confirm and refreshes', async () => {
  stubScreen(false)
  const mock = stubDay({ 'DELETE /api/staff/blocks/9': { status: 204 } })
  renderAt('/staff?date=2026-11-17')
  const mot = await screen.findByRole('region', { name: 'MOT bay' })

  const user = userEvent.setup()
  await user.click(within(mot).getByRole('button', { name: /Lift repair/ }))
  const panel = screen.getByRole('region', { name: 'Block' })
  expect(within(panel).getByText('Blocked: Lift repair')).toBeInTheDocument()
  expect(within(panel).getByText('Tue 17 Nov, 14:00–15:00 · MOT bay')).toBeInTheDocument()

  await user.click(within(panel).getByRole('button', { name: 'Remove block' }))
  expect(mock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
  await user.click(within(panel).getByRole('button', { name: 'Yes, remove it' }))

  await vi.waitFor(() => expect(scheduleCalls(mock)).toHaveLength(2))
  expect(mock.mock.calls.some(([url, init]) => url === '/api/staff/blocks/9' && init?.method === 'DELETE')).toBe(true)
  expect(screen.queryByRole('region', { name: 'Block' })).not.toBeInTheDocument()
})

it('closing the block panel keeps the block', async () => {
  stubScreen(true)
  const mock = stubDay()
  renderAt('/staff?date=2026-11-17')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /Lift repair/ }))
  await user.click(screen.getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('region', { name: 'Block' })).not.toBeInTheDocument()
  expect(mock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
})

it('day view marks an out-of-use bay', async () => {
  stubScreen(false)
  const bays = DAY_SCHEDULE.bays.map((bay) => (bay.id === 2 ? { ...bay, active: false } : bay))
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    [scheduleUrl('2026-11-17', 1)]: { status: 200, body: { ...DAY_SCHEDULE, bays } },
  })
  renderAt('/staff?date=2026-11-17')
  const bay1 = await screen.findByRole('region', { name: 'Bay 1' })
  expect(within(bay1).getByText('Out of use')).toBeInTheDocument()
  const mot = screen.getByRole('region', { name: 'MOT bay' })
  expect(within(mot).queryByText('Out of use')).not.toBeInTheDocument()
})

it('narrow day view marks an out-of-use bay tab', async () => {
  stubScreen(true)
  const bays = DAY_SCHEDULE.bays.map((bay) => (bay.id === 2 ? { ...bay, active: false } : bay))
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    [scheduleUrl('2026-11-17', 1)]: { status: 200, body: { ...DAY_SCHEDULE, bays } },
  })
  renderAt('/staff?date=2026-11-17')
  const tabs = await screen.findAllByRole('tab')
  expect(tabs.map((t) => t.textContent)).toEqual(['MOT bay', 'Bay 1 (out of use)'])
})


it('marks requests and approvals waiting for a deposit', async () => {
  stubScreen(false)
  const schedule = {
    ...DAY_SCHEDULE,
    items: [
      bookingItem({ reference: 'REQU-ESTA', status: 'pending_approval', registration: 'RE01QST' }),
      bookingItem({
        reference: 'APPR-OVED',
        status: 'awaiting_deposit',
        registration: 'AP01PRV',
        start: '2026-11-17T13:00:00+00:00',
        end: '2026-11-17T14:00:00+00:00',
      }),
    ],
  }
  stubDay({ [scheduleUrl('2026-11-17', 1)]: { status: 200, body: schedule } })
  renderAt('/staff?date=2026-11-17')
  const request = await screen.findByRole('link', { name: /RE01QST/ })
  expect(request).toHaveTextContent('Request')
  expect(request).toHaveClass('entry-pending_approval')
  const approval = screen.getByRole('link', { name: /AP01PRV/ })
  expect(approval).toHaveTextContent('Awaiting deposit')
  expect(approval).toHaveClass('entry-awaiting_deposit')
})
