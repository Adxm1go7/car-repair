import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import type { Reply } from '../../testing/staffApi.tsx'
import { ADMIN_ME, renderAt, stubFetch } from '../../testing/staffApi.tsx'
import type { AdminBay, AdminService, BayType } from '../types.ts'

const BAYS_URL = '/api/staff/settings/bays'
const TYPES_URL = '/api/staff/settings/bay-types'

const TYPES: BayType[] = [
  { id: 1, slug: 'mot', name: 'MOT ramp' },
  { id: 2, slug: 'general', name: 'General bay' },
]
const MOT_BAY: AdminBay = { id: 1, slug: 'mot-bay', name: 'MOT bay', bay_type_id: 1, bay_type: 'MOT ramp', active: true }
const BAY_1: AdminBay = { id: 2, slug: 'bay-1', name: 'Bay 1', bay_type_id: 2, bay_type: 'General bay', active: true }
const BAY_2: AdminBay = { ...BAY_1, id: 3, slug: 'bay-2', name: 'Bay 2', active: false }
const BAY_3: AdminBay = { ...BAY_1, id: 5, slug: 'bay-3', name: 'Bay 3' }
const MOT_TEST = {
  id: 1,
  slug: 'mot-test',
  name: 'MOT test',
  bay_type_id: 1,
  bay_type: 'MOT ramp',
  active: true,
} as AdminService

function stub(routes: Record<string, Reply> = {}) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: ADMIN_ME },
    [`GET ${BAYS_URL}`]: { status: 200, body: [MOT_BAY, BAY_1, BAY_2, BAY_3] },
    [`GET ${TYPES_URL}`]: { status: 200, body: TYPES },
    'GET /api/staff/settings/services': { status: 200, body: [MOT_TEST] },
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

async function row(name: string): Promise<HTMLElement> {
  return screen.findByRole('listitem', { name })
}

afterEach(() => vi.unstubAllGlobals())

it('lists bays with their type and whether they are in use', async () => {
  stub()
  renderAt('/staff/settings/bays')
  const mot = await row('MOT bay')
  expect(within(mot).getByText('MOT ramp')).toBeInTheDocument()
  expect(within(mot).getByText('In use')).toBeInTheDocument()
  expect(within(mot).getByRole('button', { name: 'Take out of use' })).toBeInTheDocument()
  const bay2 = await row('Bay 2')
  expect(within(bay2).getByText('Out of use')).toBeInTheDocument()
  expect(within(bay2).getByRole('button', { name: 'Put back in use' })).toBeInTheDocument()
})

it('adds a bay and a bay type', async () => {
  const tyre: BayType = { id: 3, slug: 'tyre-bay', name: 'Tyre bay' }
  const bay3: AdminBay = { id: 4, slug: 'tyre-1', name: 'Tyre 1', bay_type_id: 3, bay_type: 'Tyre bay', active: true }
  const mock = stub({
    [`POST ${TYPES_URL}`]: { status: 201, body: tyre },
    [`POST ${BAYS_URL}`]: { status: 201, body: bay3 },
  })
  renderAt('/staff/settings/bays')
  await row('MOT bay')
  const user = userEvent.setup()

  await user.click(screen.getByRole('button', { name: '+ Add a bay type' }))
  const typeForm = screen.getByRole('form', { name: 'Add a bay type' })
  await user.type(within(typeForm).getByLabelText('Name'), 'Tyre bay')
  await user.click(within(typeForm).getByRole('button', { name: 'Add bay type' }))
  expect(await screen.findByRole('status')).toHaveTextContent('Added bay type Tyre bay')
  expect(bodyOf(mock, TYPES_URL, 'POST')).toEqual({ name: 'Tyre bay' })

  await user.click(screen.getByRole('button', { name: '+ Add a bay' }))
  const bayForm = screen.getByRole('form', { name: 'Add a bay' })
  await user.type(within(bayForm).getByLabelText('Name'), 'Tyre 1')
  await user.selectOptions(within(bayForm).getByLabelText('Bay type'), 'Tyre bay')
  await user.click(within(bayForm).getByRole('button', { name: 'Add bay' }))
  expect(await row('Tyre 1')).toBeInTheDocument()
  expect(bodyOf(mock, BAYS_URL, 'POST')).toEqual({ name: 'Tyre 1', bay_type_id: 3 })
  expect(screen.getByRole('status')).toHaveTextContent('Added Tyre 1')
})

it('a bay needs a name and a type', async () => {
  const mock = stub()
  renderAt('/staff/settings/bays')
  await row('MOT bay')
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '+ Add a bay' }))
  const form = screen.getByRole('form', { name: 'Add a bay' })
  await user.click(within(form).getByRole('button', { name: 'Add bay' }))
  expect(within(form).getByText('Please enter a name')).toBeInTheDocument()
  expect(within(form).getByText('Please choose a bay type')).toBeInTheDocument()
  expect(sent(mock, BAYS_URL, 'POST')).toBe(false)
})

it('renames a bay', async () => {
  const mock = stub({ [`PATCH ${BAYS_URL}/2`]: { status: 200, body: { ...BAY_1, name: 'Front bay' } } })
  renderAt('/staff/settings/bays')
  const user = userEvent.setup()
  await user.click(within(await row('Bay 1')).getByRole('button', { name: 'Rename' }))
  const form = screen.getByRole('form', { name: 'Rename Bay 1' })
  const name = within(form).getByLabelText('Name')
  expect(name).toHaveValue('Bay 1')
  await user.clear(name)
  await user.type(name, 'Front bay')
  await user.click(within(form).getByRole('button', { name: 'Save' }))
  expect(await row('Front bay')).toBeInTheDocument()
  expect(bodyOf(mock, `${BAYS_URL}/2`, 'PATCH')).toEqual({ name: 'Front bay' })
})

it('a name already used shows the message', async () => {
  stub({ [`PATCH ${BAYS_URL}/2`]: { status: 409, body: { detail: 'That name is already used' } } })
  renderAt('/staff/settings/bays')
  const user = userEvent.setup()
  await user.click(within(await row('Bay 1')).getByRole('button', { name: 'Rename' }))
  const form = screen.getByRole('form', { name: 'Rename Bay 1' })
  await user.clear(within(form).getByLabelText('Name'))
  await user.type(within(form).getByLabelText('Name'), 'MOT bay')
  await user.click(within(form).getByRole('button', { name: 'Save' }))
  expect(await within(form).findByRole('alert')).toHaveTextContent('That name is already used')
})

it('out of use asks to confirm and lists bookings in the way', async () => {
  const mock = stub({
    [`PATCH ${BAYS_URL}/2`]: {
      status: 409,
      body: {
        detail: 'clashes',
        bookings: [
          { reference: 'ABCD-EFGH', start: '2026-11-17T09:30:00+00:00', bay: 'Bay 1', held: false },
          { reference: 'HELD-HELD', start: '2026-11-18T14:00:00+00:00', bay: 'Bay 1', held: true },
        ],
      },
    },
  })
  renderAt('/staff/settings/bays')
  const user = userEvent.setup()
  const bay1 = await row('Bay 1')
  await user.click(within(bay1).getByRole('button', { name: 'Take out of use' }))
  expect(within(bay1).getByText(/can't be booked until it's back in use/)).toBeInTheDocument()
  expect(within(bay1).queryByText(/the last/)).not.toBeInTheDocument()
  expect(sent(mock, `${BAYS_URL}/2`, 'PATCH')).toBe(false)
  await user.click(within(bay1).getByRole('button', { name: 'Yes, take out of use' }))

  const clashes = await within(bay1).findByRole('list', { name: 'Bookings in the way' })
  const links = within(clashes).getAllByRole('link')
  expect(links.map((link) => link.getAttribute('href'))).toEqual([
    '/staff/bookings/ABCD-EFGH',
    '/staff/bookings/HELD-HELD',
  ])
  expect(within(clashes).getByText(/Tue 17 Nov 09:30/)).toBeInTheDocument()
  expect(within(clashes).getByText(/being paid for, clears in a few minutes/)).toBeInTheDocument()
  expect(within(bay1).getByText('In use')).toBeInTheDocument()
  expect(bodyOf(mock, `${BAYS_URL}/2`, 'PATCH')).toEqual({ active: false })
})

it('last bay of its type warns before going out of use', async () => {
  stub({ [`PATCH ${BAYS_URL}/1`]: { status: 200, body: { ...MOT_BAY, active: false } } })
  renderAt('/staff/settings/bays')
  const user = userEvent.setup()
  const mot = await row('MOT bay')
  await user.click(within(mot).getByRole('button', { name: 'Take out of use' }))
  expect(within(mot).getByText(/MOT bay is the last MOT ramp in use/)).toBeInTheDocument()
  expect(within(mot).getByText(/MOT test can't be booked/)).toBeInTheDocument()
  await user.click(within(mot).getByRole('button', { name: 'Yes, take out of use' }))
  expect(await within(mot).findByText('Out of use')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Took MOT bay out of use')
})

it('puts a bay back in use', async () => {
  const mock = stub({ [`PATCH ${BAYS_URL}/3`]: { status: 200, body: { ...BAY_2, active: true } } })
  renderAt('/staff/settings/bays')
  const user = userEvent.setup()
  const bay2 = await row('Bay 2')
  await user.click(within(bay2).getByRole('button', { name: 'Put back in use' }))
  expect(await within(bay2).findByText('In use')).toBeInTheDocument()
  expect(bodyOf(mock, `${BAYS_URL}/3`, 'PATCH')).toEqual({ active: true })
  expect(screen.getByRole('status')).toHaveTextContent('Put Bay 2 back in use')
})
