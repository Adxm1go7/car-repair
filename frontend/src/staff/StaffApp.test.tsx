import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { ADMIN_ME, STAFF_ME, renderAt, stubFetch } from '../testing/staffApi.tsx'
import { staffRequest } from './api.ts'

afterEach(() => vi.unstubAllGlobals())

it('staff pages do not wait for the catalogue', () => {
  stubFetch({ '/api/services': 'never', '/api/opening-hours': 'never', '/api/garage': 'never' })
  renderAt('/staff/login')
  expect(screen.getByRole('heading', { level: 1, name: 'Staff login' })).toBeInTheDocument()
})

it('goes to login with next when there is no session', async () => {
  stubFetch({ 'GET /api/staff/me': { status: 401, body: { detail: 'Please log in' } } })
  renderAt('/staff/week?x=1')
  expect(await screen.findByRole('heading', { level: 1, name: 'Staff login' })).toBeInTheDocument()
})

it('redirects to login on a 401 from any call', async () => {
  stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'POST /api/staff/login': { status: 200, body: STAFF_ME },
    'GET /api/staff/schedule': { status: 401, body: { detail: 'Please log in' } },
  })
  renderAt('/staff/week')
  expect(await screen.findByRole('heading', { level: 1, name: 'Week' })).toBeInTheDocument()

  await act(async () => {
    await staffRequest('/schedule')
  })
  expect(await screen.findByRole('heading', { level: 1, name: 'Staff login' })).toBeInTheDocument()

  // Logging in again returns to the page the 401 came from.
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'sam@example.com')
  await user.type(screen.getByLabelText('Password'), 'correct horse')
  await user.click(screen.getByRole('button', { name: 'Log in' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Week' })).toBeInTheDocument()
})

it('staff see no Team or Audit links', async () => {
  stubFetch({ 'GET /api/staff/me': { status: 200, body: STAFF_ME } })
  renderAt('/staff')
  const nav = await screen.findByRole('navigation')
  expect(within(nav).getByRole('link', { name: 'Day' })).toHaveAttribute('href', '/staff')
  expect(within(nav).getByRole('link', { name: 'Week' })).toHaveAttribute('href', '/staff/week')
  expect(within(nav).queryByRole('link', { name: 'Team' })).not.toBeInTheDocument()
  expect(within(nav).queryByRole('link', { name: 'Audit' })).not.toBeInTheDocument()
  expect(screen.getByText('Sam Staff')).toBeInTheDocument()
})

it('admins see Team and Audit links and the garage name', async () => {
  stubFetch({ 'GET /api/staff/me': { status: 200, body: ADMIN_ME } })
  renderAt('/staff')
  const nav = await screen.findByRole('navigation')
  expect(within(nav).getByRole('link', { name: 'Team' })).toHaveAttribute('href', '/staff/team')
  expect(within(nav).getByRole('link', { name: 'Audit' })).toHaveAttribute('href', '/staff/audit')
  expect(await screen.findByText('Hillside Motors')).toBeInTheDocument()
})

it('staff opening team see the access message', async () => {
  stubFetch({ 'GET /api/staff/me': { status: 200, body: STAFF_ME } })
  renderAt('/staff/team')
  expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument()
})

it('staff opening audit see the access message', async () => {
  stubFetch({ 'GET /api/staff/me': { status: 200, body: STAFF_ME } })
  renderAt('/staff/audit')
  expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument()
})

it('logs out and goes to the login page', async () => {
  const mock = stubFetch({
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
    'POST /api/staff/logout': { status: 204 },
  })
  renderAt('/staff')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Log out' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Staff login' })).toBeInTheDocument()
  expect(mock.mock.calls.some(([url, init]) => url === '/api/staff/logout' && init?.method === 'POST')).toBe(true)
})
