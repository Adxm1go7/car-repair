import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { STAFF_ME, renderAt, sentBody, stubFetch } from '../testing/staffApi.tsx'

afterEach(() => vi.unstubAllGlobals())

it('logs in and returns to next', async () => {
  const mock = stubFetch({
    'POST /api/staff/login': { status: 200, body: STAFF_ME },
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
  })
  renderAt('/staff/login?next=%2Fstaff%2Fweek')

  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'sam@example.com')
  await user.type(screen.getByLabelText('Password'), 'correct horse')
  await user.click(screen.getByRole('button', { name: 'Log in' }))

  expect(await screen.findByRole('heading', { level: 1, name: 'Week' })).toBeInTheDocument()
  expect(sentBody(mock, '/api/staff/login')).toEqual({ email: 'sam@example.com', password: 'correct horse' })
})

it('goes to the day view when next is missing or points elsewhere', async () => {
  stubFetch({
    'POST /api/staff/login': { status: 200, body: STAFF_ME },
    'GET /api/staff/me': { status: 200, body: STAFF_ME },
  })
  renderAt('/staff/login?next=https%3A%2F%2Fevil.example')

  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'sam@example.com')
  await user.type(screen.getByLabelText('Password'), 'correct horse')
  await user.click(screen.getByRole('button', { name: 'Log in' }))

  expect(await screen.findByRole('heading', { level: 1, name: 'Day' })).toBeInTheDocument()
})

it('shows one error for a wrong login', async () => {
  stubFetch({ 'POST /api/staff/login': { status: 401, body: { detail: 'Email or password is wrong' } } })
  renderAt('/staff/login')

  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'sam@example.com')
  await user.type(screen.getByLabelText('Password'), 'wrong one')
  await user.click(screen.getByRole('button', { name: 'Log in' }))
  await user.click(screen.getByRole('button', { name: 'Log in' }))

  const alerts = await screen.findAllByRole('alert')
  expect(alerts).toHaveLength(1)
  expect(alerts[0]).toHaveTextContent('Email or password is wrong')
  expect(screen.getByRole('heading', { level: 1, name: 'Staff login' })).toBeInTheDocument()
})

it('links to forgotten password', () => {
  stubFetch({})
  renderAt('/staff/login')
  expect(screen.getByRole('link', { name: 'Forgot your password?' })).toHaveAttribute(
    'href',
    '/staff/forgot-password',
  )
})
