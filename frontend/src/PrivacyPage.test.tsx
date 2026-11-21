import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, it } from 'vitest'
import { PrivacyPage } from './PrivacyPage.tsx'
import { GARAGE } from './testing/fixtures.ts'

it('explains what we keep, for how long, and how to reach the garage', () => {
  render(
    <MemoryRouter>
      <PrivacyPage garage={GARAGE} />
    </MemoryRouter>,
  )
  expect(screen.getByRole('heading', { level: 1, name: 'Privacy' })).toBeInTheDocument()
  expect(screen.getByText(/demo/i)).toBeInTheDocument()
  expect(
    screen.getByText(
      "We remove your personal details 12 months after your appointment, or 12 months after an enquiry we didn't book in.",
    ),
  ).toBeInTheDocument()
  expect(screen.getByText(/we never see your card details/i)).toBeInTheDocument()
  expect(screen.getByText(/we give Stripe your email address/i)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '01632 960123' })).toHaveAttribute('href', 'tel:01632960123')
  expect(screen.getByRole('link', { name: 'bookings@example.com' })).toHaveAttribute(
    'href',
    'mailto:bookings@example.com',
  )
  expect(document.title).toBe('Privacy')
})

const DEMO_NOTE =
  "On this live demo nothing is really emailed: emails are kept in a Demo inbox that everyone can see, and everything is wiped every night."

it('on the live demo says emails are public and wiped nightly', () => {
  render(
    <MemoryRouter>
      <PrivacyPage garage={{ ...GARAGE, demo_site: true }} />
    </MemoryRouter>,
  )
  expect(screen.getByText(DEMO_NOTE)).toBeInTheDocument()
})

it('says nothing about a Demo inbox elsewhere', () => {
  render(
    <MemoryRouter>
      <PrivacyPage garage={GARAGE} />
    </MemoryRouter>,
  )
  expect(screen.queryByText(DEMO_NOTE)).not.toBeInTheDocument()
})
