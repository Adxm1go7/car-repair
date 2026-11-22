import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { BANNER, DemoBanner, DemoLogins, DemoWarning, WARNING } from './DemoBanner.tsx'

it('the banner says how to pay and where the emails go', () => {
  render(<DemoBanner />)
  expect(BANNER).toBe(
    "This is a demo. Pay with Stripe's test card 4242 4242 4242 4242. Emails appear in the Demo inbox. Everything resets nightly.",
  )
  expect(screen.getByRole('note')).toHaveTextContent(BANNER)
})

it('the warning tells people not to use real details', () => {
  render(<DemoWarning />)
  expect(WARNING).toBe("Everyone can see this inbox. Don't use real names, emails or car details.")
  expect(screen.getByText(WARNING)).toBeInTheDocument()
})

it('lists both demo logins', () => {
  render(<DemoLogins />)
  for (const text of ['admin@example.test', 'demo-admin-pass', 'staff@example.test', 'demo-staff-pass']) {
    expect(screen.getByText(text)).toBeInTheDocument()
  }
})
