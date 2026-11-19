import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import type { Reply } from '../../testing/staffApi.tsx'
import { ADMIN_ME, STAFF_ME, renderAt, stubFetch } from '../../testing/staffApi.tsx'
import type { AdminBay, AdminService, BayType } from '../types.ts'

const URL = '/api/staff/settings/services'

const MOT: AdminService = {
  id: 1,
  slug: 'mot-test',
  name: 'MOT test',
  category: 'MOT',
  description: 'The annual test.',
  duration_minutes: 60,
  price_from_pence: 5485,
  price_to_pence: null,
  bay_type_id: 1,
  bay_type: 'MOT ramp',
  approval_mode: 'instant',
  active: true,
  sort_order: 1,
}
const OIL: AdminService = {
  ...MOT,
  id: 2,
  slug: 'oil-filter-change',
  name: 'Oil & filter change',
  category: 'Servicing',
  duration_minutes: 45,
  price_from_pence: 6900,
  bay_type_id: 2,
  bay_type: 'General bay',
  sort_order: 2,
}
const DIAG: AdminService = {
  ...OIL,
  id: 3,
  slug: 'diagnostic-check',
  name: 'Diagnostic check',
  category: 'Diagnostics',
  duration_minutes: 60,
  price_from_pence: 4500,
  price_to_pence: 9000,
  active: false,
  sort_order: 3,
}
const TYPES: BayType[] = [
  { id: 1, slug: 'mot', name: 'MOT ramp' },
  { id: 2, slug: 'general', name: 'General bay' },
  { id: 3, slug: 'tyre', name: 'Tyre bay' },
]
const BAYS: AdminBay[] = [
  { id: 1, slug: 'mot-bay', name: 'MOT bay', bay_type_id: 1, bay_type: 'MOT ramp', active: true },
  { id: 2, slug: 'bay-1', name: 'Bay 1', bay_type_id: 2, bay_type: 'General bay', active: true },
]

function stub(routes: Record<string, Reply> = {}) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: ADMIN_ME },
    [`GET ${URL}`]: { status: 200, body: [MOT, OIL, DIAG] },
    'GET /api/staff/settings/bay-types': { status: 200, body: TYPES },
    'GET /api/staff/settings/bays': { status: 200, body: BAYS },
    ...routes,
  })
}

function bodyOf(mock: ReturnType<typeof stubFetch>, url: string, method: string): unknown {
  const call = mock.mock.calls.find(([u, init]) => u === url && init?.method === method)
  if (!call) throw new Error(`no ${method} ${url}`)
  return JSON.parse(String(call[1]?.body))
}

async function row(name: string): Promise<HTMLElement> {
  return screen.findByRole('listitem', { name })
}

afterEach(() => vi.unstubAllGlobals())

it('staff see the access message on settings', async () => {
  stubFetch({ 'GET /api/staff/me': { status: 200, body: STAFF_ME } })
  renderAt('/staff/settings/services')
  expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument()
})

it('settings opens on the services tab, with a link for admins', async () => {
  stub()
  renderAt('/staff/settings')
  expect(await screen.findByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Settings' })).toBeInTheDocument()
  const tabs = screen.getByRole('navigation', { name: 'Settings' })
  expect(within(tabs).getByRole('link', { name: 'Services' })).toHaveAttribute('aria-current', 'page')
  expect(await row('MOT test')).toBeInTheDocument()
})

it('lists services with price and shown or hidden', async () => {
  stub()
  renderAt('/staff/settings/services')
  const mot = await row('MOT test')
  expect(within(mot).getByText('MOT')).toBeInTheDocument()
  expect(within(mot).getByText('1h')).toBeInTheDocument()
  expect(within(mot).getByText('£54.85')).toBeInTheDocument()
  expect(within(mot).getByText('Shown')).toBeInTheDocument()
  expect(within(mot).getByRole('button', { name: 'Hide' })).toBeInTheDocument()
  const diag = await row('Diagnostic check')
  expect(within(diag).getByText('£45–£90')).toBeInTheDocument()
  expect(within(diag).getByText('Hidden')).toBeInTheDocument()
  expect(within(diag).getByRole('button', { name: 'Show' })).toBeInTheDocument()
})

it('adds a service', async () => {
  const added: AdminService = {
    ...OIL,
    id: 4,
    slug: 'wheel-alignment',
    name: 'Wheel alignment',
    category: 'Tyres',
    description: 'All four wheels.',
    duration_minutes: 90,
    price_from_pence: 4999,
    price_to_pence: 7500,
    approval_mode: 'needs_approval',
    sort_order: 4,
  }
  const mock = stub({ [`POST ${URL}`]: { status: 201, body: added } })
  renderAt('/staff/settings/services')
  await row('MOT test')

  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '+ Add a service' }))
  const form = screen.getByRole('form', { name: 'Add a service' })
  await user.type(within(form).getByLabelText('Name'), 'Wheel alignment')
  await user.type(within(form).getByLabelText('Category'), 'Tyres')
  await user.type(within(form).getByLabelText('Description'), 'All four wheels.')
  await user.selectOptions(within(form).getByLabelText('Duration'), '90')
  await user.type(within(form).getByLabelText('Price from (£)'), '49.99')
  await user.type(within(form).getByLabelText('Price to (£, optional)'), '75')
  await user.selectOptions(within(form).getByLabelText('Bay type'), '2')
  await user.click(within(form).getByLabelText('Needs approval'))
  await user.click(within(form).getByRole('button', { name: 'Add service' }))

  expect(await row('Wheel alignment')).toBeInTheDocument()
  expect(bodyOf(mock, URL, 'POST')).toEqual({
    name: 'Wheel alignment',
    category: 'Tyres',
    description: 'All four wheels.',
    duration_minutes: 90,
    price_from_pence: 4999,
    price_to_pence: 7500,
    bay_type_id: 2,
    approval_mode: 'needs_approval',
  })
  expect(screen.getByRole('status')).toHaveTextContent('Added Wheel alignment')
  expect(screen.queryByRole('form', { name: 'Add a service' })).not.toBeInTheDocument()
})

it('checks the form before sending', async () => {
  const mock = stub()
  renderAt('/staff/settings/services')
  await row('MOT test')
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '+ Add a service' }))
  const form = screen.getByRole('form', { name: 'Add a service' })
  await user.type(within(form).getByLabelText('Price from (£)'), '10.505')
  await user.type(within(form).getByLabelText('Price to (£, optional)'), '5')
  await user.click(within(form).getByRole('button', { name: 'Add service' }))

  expect(within(form).getByText('Please enter a name')).toBeInTheDocument()
  expect(within(form).getByText('Please choose a bay type')).toBeInTheDocument()
  expect(within(form).getByText('Enter pounds and pence, like 54.85')).toBeInTheDocument()
  expect(mock.mock.calls.some(([u, init]) => u === URL && init?.method === 'POST')).toBe(false)
})

it('duplicate name shows the message', async () => {
  stub({ [`POST ${URL}`]: { status: 409, body: { detail: 'That name is already used' } } })
  renderAt('/staff/settings/services')
  await row('MOT test')
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '+ Add a service' }))
  const form = screen.getByRole('form', { name: 'Add a service' })
  await user.type(within(form).getByLabelText('Name'), 'MOT test')
  await user.type(within(form).getByLabelText('Category'), 'MOT')
  await user.type(within(form).getByLabelText('Description'), 'Again.')
  await user.type(within(form).getByLabelText('Price from (£)'), '54.85')
  await user.selectOptions(within(form).getByLabelText('Bay type'), '1')
  await user.click(within(form).getByRole('button', { name: 'Add service' }))
  expect(await within(form).findByRole('alert')).toHaveTextContent('That name is already used')
})

it('edit has no bay type or approval fields', async () => {
  const edited = { ...MOT, name: 'MOT', price_from_pence: 5000 }
  const mock = stub({ [`PATCH ${URL}/1`]: { status: 200, body: edited } })
  renderAt('/staff/settings/services')
  const user = userEvent.setup()
  await user.click(within(await row('MOT test')).getByRole('button', { name: 'Edit' }))
  const form = screen.getByRole('form', { name: 'Edit MOT test' })
  expect(within(form).queryByLabelText('Bay type')).not.toBeInTheDocument()
  expect(within(form).queryByLabelText('Needs approval')).not.toBeInTheDocument()
  expect(within(form).getByText(/MOT ramp/)).toBeInTheDocument()
  expect(within(form).getByLabelText('Price from (£)')).toHaveValue('54.85')

  await user.clear(within(form).getByLabelText('Name'))
  await user.type(within(form).getByLabelText('Name'), 'MOT')
  await user.clear(within(form).getByLabelText('Price from (£)'))
  await user.type(within(form).getByLabelText('Price from (£)'), '50')
  await user.click(within(form).getByRole('button', { name: 'Save' }))

  expect(await row('MOT')).toBeInTheDocument()
  expect(bodyOf(mock, `${URL}/1`, 'PATCH')).toEqual({
    name: 'MOT',
    category: 'MOT',
    description: 'The annual test.',
    duration_minutes: 60,
    price_from_pence: 5000,
    price_to_pence: null,
  })
})

it('hide asks to confirm', async () => {
  const mock = stub({ [`PATCH ${URL}/1`]: { status: 200, body: { ...MOT, active: false } } })
  renderAt('/staff/settings/services')
  const user = userEvent.setup()
  const mot = await row('MOT test')
  await user.click(within(mot).getByRole('button', { name: 'Hide' }))
  expect(within(mot).getByText(/customers won't be able to book it/)).toBeInTheDocument()
  expect(mock.mock.calls.some(([u, init]) => u === `${URL}/1` && init?.method === 'PATCH')).toBe(false)
  await user.click(within(mot).getByRole('button', { name: 'Yes, hide' }))
  expect(await within(mot).findByText('Hidden')).toBeInTheDocument()
  expect(bodyOf(mock, `${URL}/1`, 'PATCH')).toEqual({ active: false })
})

it('show needs no confirm', async () => {
  const mock = stub({ [`PATCH ${URL}/3`]: { status: 200, body: { ...DIAG, active: true } } })
  renderAt('/staff/settings/services')
  const user = userEvent.setup()
  const diag = await row('Diagnostic check')
  await user.click(within(diag).getByRole('button', { name: 'Show' }))
  expect(await within(diag).findByText('Shown')).toBeInTheDocument()
  expect(bodyOf(mock, `${URL}/3`, 'PATCH')).toEqual({ active: true })
})

it('up and down reorder', async () => {
  const mock = stub({
    [`POST ${URL}/2/move`]: { status: 200, body: [OIL, MOT, DIAG] },
  })
  renderAt('/staff/settings/services')
  await row('MOT test')
  expect(screen.getByRole('button', { name: 'Move MOT test up' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Move Diagnostic check down' })).toBeDisabled()
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Move Oil & filter change up' }))
  const list = screen.getByRole('list', { name: 'Services' })
  await vi.waitFor(() => {
    const names = within(list)
      .getAllByRole('listitem')
      .map((item) => item.getAttribute('aria-label'))
    expect(names).toEqual(['Oil & filter change', 'MOT test', 'Diagnostic check'])
  })
  expect(bodyOf(mock, `${URL}/2/move`, 'POST')).toEqual({ direction: 'up' })
})

it('warns when the bay type has no bay in use', async () => {
  stub()
  renderAt('/staff/settings/services')
  await row('MOT test')
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '+ Add a service' }))
  const form = screen.getByRole('form', { name: 'Add a service' })
  await user.selectOptions(within(form).getByLabelText('Bay type'), '3')
  expect(within(form).getByText(/No Tyre bay is in use/)).toBeInTheDocument()
  await user.selectOptions(within(form).getByLabelText('Bay type'), '2')
  expect(within(form).queryByText(/is in use/)).not.toBeInTheDocument()
})
