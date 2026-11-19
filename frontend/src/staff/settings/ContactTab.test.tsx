import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import type { Reply } from '../../testing/staffApi.tsx'
import { ADMIN_ME, renderAt, stubFetch } from '../../testing/staffApi.tsx'

const URL = '/api/staff/settings/contact'
const CONTACT = {
  name: 'Hillside Motors',
  address: '12 Station Road, Anytown, AT1 2CD',
  phone: '01632 960123',
  email: 'bookings@example.com',
}

function stub(routes: Record<string, Reply> = {}) {
  return stubFetch({
    'GET /api/staff/me': { status: 200, body: ADMIN_ME },
    [`GET ${URL}`]: { status: 200, body: CONTACT },
    ...routes,
  })
}

function sentPut(mock: ReturnType<typeof stubFetch>): unknown {
  const call = mock.mock.calls.find(([u, init]) => u === URL && init?.method === 'PUT')
  return call ? JSON.parse(String(call[1]?.body)) : undefined
}

afterEach(() => vi.unstubAllGlobals())

it('saves contact details', async () => {
  const saved = { ...CONTACT, phone: '01632 960999', email: 'hello@example.com' }
  const mock = stub({ [`PUT ${URL}`]: { status: 200, body: saved } })
  renderAt('/staff/settings/contact')
  const phone = await screen.findByLabelText('Phone')
  expect(screen.getByLabelText('Garage name')).toHaveValue('Hillside Motors')
  expect(screen.getByLabelText('Address')).toHaveValue('12 Station Road, Anytown, AT1 2CD')

  const user = userEvent.setup()
  await user.clear(phone)
  await user.type(phone, '01632 960999')
  await user.clear(screen.getByLabelText('Email'))
  await user.type(screen.getByLabelText('Email'), ' Hello@Example.com ')
  await user.click(screen.getByRole('button', { name: 'Save' }))

  expect(await screen.findByRole('status')).toHaveTextContent(
    'Contact details saved. The site and every email sent from now on use them.',
  )
  expect(sentPut(mock)).toEqual({ ...CONTACT, phone: '01632 960999', email: 'Hello@Example.com' })
  expect(screen.getByLabelText('Email')).toHaveValue('hello@example.com')
})

it('bad email shows the message', async () => {
  const mock = stub()
  renderAt('/staff/settings/contact')
  const email = await screen.findByLabelText('Email')
  const user = userEvent.setup()
  await user.clear(email)
  await user.type(email, 'not an email')
  await user.clear(screen.getByLabelText('Address'))
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(screen.getByText('Please enter a valid email address')).toBeInTheDocument()
  expect(screen.getByText('Please enter the address')).toBeInTheDocument()
  expect(sentPut(mock)).toBeUndefined()
})

it("shows the server's message when it refuses", async () => {
  stub({ [`PUT ${URL}`]: { status: 422, body: { detail: 'Please enter a phone number we can call' } } })
  renderAt('/staff/settings/contact')
  await screen.findByLabelText('Phone')
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Please enter a phone number we can call')
})
