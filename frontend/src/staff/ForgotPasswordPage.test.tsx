import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { renderAt, sentBody, stubFetch } from '../testing/staffApi.tsx'

const SENT = "If that address has an account, we've emailed a link"

afterEach(() => vi.unstubAllGlobals())

it('forgot password always shows the same message', async () => {
  for (const email of ['sam@example.com', 'nobody@example.com']) {
    const mock = stubFetch({ 'POST /api/staff/forgot-password': { status: 202, body: { detail: SENT } } })
    renderAt('/staff/forgot-password')

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Email'), email)
    await user.click(screen.getByRole('button', { name: 'Email me a link' }))

    expect(await screen.findByRole('status')).toHaveTextContent(SENT)
    expect(sentBody(mock, '/api/staff/forgot-password')).toEqual({ email })
    expect(screen.getByRole('link', { name: 'Back to login' })).toHaveAttribute('href', '/staff/login')
    cleanup()
    vi.unstubAllGlobals()
  }
})

it('says so when the request could not be sent', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
  renderAt('/staff/forgot-password')

  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'sam@example.com')
  await user.click(screen.getByRole('button', { name: 'Email me a link' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
})
