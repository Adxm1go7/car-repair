import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import type { Reply } from '../../testing/staffApi.tsx'
import { ADMIN_ME, renderAt, sentBody, stubFetch } from '../../testing/staffApi.tsx'
import type { TeamMember } from '../types.ts'

const ALEX: TeamMember = { id: 1, name: 'Alex Admin', email: 'alex@example.com', role: 'admin', state: 'active' }
const SAM: TeamMember = { id: 2, name: 'Sam Staff', email: 'sam@example.com', role: 'staff', state: 'active' }
const OLD: TeamMember = { id: 4, name: 'Old Hand', email: 'old@example.com', role: 'staff', state: 'removed' }

function stubTeam(routes: Record<string, Reply> = {}) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: ADMIN_ME },
    'GET /api/staff/team': { status: 200, body: [ALEX, SAM, OLD] },
    ...routes,
  })
}

function called(mock: ReturnType<typeof stubFetch>, url: string): boolean {
  return mock.mock.calls.some(([u]) => u === url)
}

async function memberRow(name: string): Promise<HTMLElement> {
  return screen.findByRole('listitem', { name })
}

afterEach(() => vi.unstubAllGlobals())

it('lists each person with their role and state', async () => {
  stubTeam()
  renderAt('/staff/team')
  expect(await screen.findByRole('heading', { level: 1, name: 'Team' })).toBeInTheDocument()
  const alex = await memberRow('Alex Admin')
  expect(within(alex).getByText('Admin · Active')).toBeInTheDocument()
  expect(within(alex).getByText('(you)')).toBeInTheDocument()
  expect(within(await memberRow('Sam Staff')).getByText('Staff · Active')).toBeInTheDocument()
  const old = await memberRow('Old Hand')
  expect(within(old).getByText('Staff · Removed')).toBeInTheDocument()
  // A removed account can only be restored.
  expect(within(old).getByRole('button', { name: 'Restore' })).toBeInTheDocument()
  expect(within(old).queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
  expect(within(old).queryByRole('button', { name: 'Send password reset' })).not.toBeInTheDocument()
})

it('invites a staff member', async () => {
  const jo: TeamMember = { id: 3, name: 'Jo Bloggs', email: 'jo@example.com', role: 'staff', state: 'invited' }
  const mock = stubTeam({ 'POST /api/staff/team': { status: 201, body: jo } })
  renderAt('/staff/team')
  await memberRow('Alex Admin')

  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Name'), 'Jo Bloggs')
  await user.type(screen.getByLabelText('Email'), 'jo@example.com')
  expect(screen.getByLabelText('Role')).toHaveValue('staff')
  await user.click(screen.getByRole('button', { name: 'Send invite' }))

  expect(within(await memberRow('Jo Bloggs')).getByText('Staff · Invited')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Invite sent to jo@example.com')
  const invite = mock.mock.calls.find(([url, init]) => url === '/api/staff/team' && init?.method === 'POST')
  expect(JSON.parse(String(invite?.[1]?.body))).toEqual({ name: 'Jo Bloggs', email: 'jo@example.com', role: 'staff' })
  expect(screen.getByLabelText('Name')).toHaveValue('')
})

it('invite checks the name and email before sending', async () => {
  const mock = stubTeam()
  renderAt('/staff/team')
  await memberRow('Alex Admin')

  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'not-an-email')
  await user.click(screen.getByRole('button', { name: 'Send invite' }))

  expect(await screen.findByText('Please enter their name')).toBeInTheDocument()
  expect(screen.getByText('Please enter a valid email')).toBeInTheDocument()
  expect(mock.mock.calls.some(([url, init]) => url === '/api/staff/team' && init?.method === 'POST')).toBe(false)
})

it('duplicate email shows the message', async () => {
  stubTeam({ 'POST /api/staff/team': { status: 409, body: { detail: 'That email already has an account' } } })
  renderAt('/staff/team')
  await memberRow('Alex Admin')

  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Name'), 'Sam Again')
  await user.type(screen.getByLabelText('Email'), 'sam@example.com')
  await user.click(screen.getByRole('button', { name: 'Send invite' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('That email already has an account')
  // The form keeps what was typed, so it can be corrected.
  expect(screen.getByLabelText('Email')).toHaveValue('sam@example.com')
})

it('last admin message on remove', async () => {
  const mock = stubTeam({
    'PATCH /api/staff/team/1': { status: 409, body: { detail: 'The garage needs at least one admin' } },
  })
  renderAt('/staff/team')
  const alex = await memberRow('Alex Admin')

  const user = userEvent.setup()
  await user.click(within(alex).getByRole('button', { name: 'Remove' }))
  await user.click(within(alex).getByRole('button', { name: 'Yes, remove' }))

  expect(await within(alex).findByRole('alert')).toHaveTextContent('The garage needs at least one admin')
  expect(sentBody(mock, '/api/staff/team/1')).toEqual({ active: false })
  expect(within(alex).getByText('Admin · Active')).toBeInTheDocument()
})

it('reset asks to confirm', async () => {
  const mock = stubTeam({
    'POST /api/staff/team/2/reset-password': { status: 202, body: { ...SAM, state: 'reset_sent' } },
  })
  renderAt('/staff/team')
  const sam = await memberRow('Sam Staff')

  const user = userEvent.setup()
  await user.click(within(sam).getByRole('button', { name: 'Send password reset' }))
  expect(within(sam).getByText(/logged out until they set a new password/)).toBeInTheDocument()
  expect(called(mock, '/api/staff/team/2/reset-password')).toBe(false)

  // Back leaves everything as it was.
  await user.click(within(sam).getByRole('button', { name: 'Back' }))
  expect(within(sam).queryByText(/logged out until/)).not.toBeInTheDocument()

  await user.click(within(sam).getByRole('button', { name: 'Send password reset' }))
  await user.click(within(sam).getByRole('button', { name: 'Yes, send it' }))
  expect(await within(sam).findByText('Staff · Reset sent')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Password reset sent to sam@example.com')
})

it('changes a role and restores a removed account', async () => {
  const mock = stubTeam({
    'PATCH /api/staff/team/2': { status: 200, body: { ...SAM, role: 'admin' } },
    'PATCH /api/staff/team/4': { status: 200, body: { ...OLD, state: 'invited' } },
  })
  renderAt('/staff/team')
  const sam = await memberRow('Sam Staff')

  const user = userEvent.setup()
  await user.click(within(sam).getByRole('button', { name: 'Make admin' }))
  await user.click(within(sam).getByRole('button', { name: 'Yes, make admin' }))
  expect(await within(sam).findByText('Admin · Active')).toBeInTheDocument()
  expect(sentBody(mock, '/api/staff/team/2')).toEqual({ role: 'admin' })

  const old = await memberRow('Old Hand')
  await user.click(within(old).getByRole('button', { name: 'Restore' }))
  await user.click(within(old).getByRole('button', { name: 'Yes, restore' }))
  expect(await within(old).findByText('Staff · Invited')).toBeInTheDocument()
  expect(sentBody(mock, '/api/staff/team/4')).toEqual({ active: true })
})

it('shows a message when the team cannot load', async () => {
  stubTeam({ 'GET /api/staff/team': { status: 500 } })
  renderAt('/staff/team')
  expect(await screen.findByRole('alert')).toHaveTextContent("Sorry, we couldn't load the team.")
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
})
