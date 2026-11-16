import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { DAY_HEADING, STAFF_ME, renderAt, sentBody, stubFetch } from '../testing/staffApi.tsx'

const INVALID = "This link isn't valid any more"

afterEach(() => vi.unstubAllGlobals())

it('set password reads the token from the fragment and logs in', async () => {
  const mock = stubFetch({
    'POST /api/staff/set-password': { status: 200, body: STAFF_ME },
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
  })
  renderAt('/staff/set-password#t=tok123')

  const user = userEvent.setup()
  await user.type(screen.getByLabelText('New password'), 'long enough')
  await user.click(screen.getByRole('button', { name: 'Set password' }))

  expect(await screen.findByRole('heading', { level: 1, name: DAY_HEADING })).toBeInTheDocument()
  expect(sentBody(mock, '/api/staff/set-password')).toEqual({ token: 'tok123', password: 'long enough' })
})

it('set password with a bad link shows the invalid message', async () => {
  stubFetch({ 'POST /api/staff/set-password': { status: 400, body: { detail: INVALID } } })
  renderAt('/staff/set-password#t=used')

  const user = userEvent.setup()
  await user.type(screen.getByLabelText('New password'), 'long enough')
  await user.click(screen.getByRole('button', { name: 'Set password' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(INVALID)
  expect(screen.getByRole('link', { name: 'Forgot your password?' })).toBeInTheDocument()
})

it('shows the invalid message when the link has no token', () => {
  stubFetch({})
  renderAt('/staff/set-password')
  expect(screen.getByRole('alert')).toHaveTextContent(INVALID)
  expect(screen.queryByLabelText('New password')).not.toBeInTheDocument()
})

it('refuses a password shorter than 8 characters without sending it', async () => {
  const mock = stubFetch({})
  renderAt('/staff/set-password#t=tok123')

  const user = userEvent.setup()
  await user.type(screen.getByLabelText('New password'), 'short')
  await user.click(screen.getByRole('button', { name: 'Set password' }))

  expect(screen.getByText('Use at least 8 characters')).toBeInTheDocument()
  expect(mock.mock.calls.some(([url]) => url === '/api/staff/set-password')).toBe(false)
})
