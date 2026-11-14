import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { expect, it } from 'vitest'
import { GARAGE } from '../testing/fixtures.ts'
import { BookedPage } from './BookedPage.tsx'
import type { BookingSummary } from './types.ts'

const SUMMARY: BookingSummary = {
  reference: 'ABCD-EFGH',
  status: 'confirmed',
  start: '2026-11-16T08:00:00+00:00',
  end: '2026-11-16T09:00:00+00:00',
  services: [
    { slug: 'mot-test', name: 'MOT test', duration_minutes: 60, price_from_pence: 5485, price_to_pence: null },
  ],
  registration: 'AB12CDE',
  make: 'Ford',
  model: 'Focus',
  deposit_paid_pence: 2000,
}

function renderAt(state: unknown): void {
  render(
    <MemoryRouter initialEntries={[{ pathname: '/booked/ABCD-EFGH', state }]}>
      <Routes>
        <Route path="/booked/:reference" element={<BookedPage garage={GARAGE} />} />
      </Routes>
    </MemoryRouter>,
  )
}

it('shows the summary from navigation state', () => {
  renderAt(SUMMARY)
  expect(screen.getByRole('heading', { level: 1, name: "You're booked" })).toBeInTheDocument()
  expect(screen.getByText('Monday 16 November, 08:00 – 09:00')).toBeInTheDocument()
  expect(screen.getByText('MOT test')).toBeInTheDocument()
  expect(screen.getByText('AB12CDE · Ford Focus')).toBeInTheDocument()
  expect(screen.getByText('ABCD-EFGH')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '01632 960123' })).toHaveAttribute('href', 'tel:01632960123')
})

it('shows the deposit paid', () => {
  renderAt(SUMMARY)
  expect(screen.getByText('Deposit paid: £20')).toBeInTheDocument()
})

it('hides the deposit line for a waived deposit', () => {
  renderAt({ ...SUMMARY, deposit_paid_pence: 0 })
  expect(screen.queryByText(/Deposit paid/)).not.toBeInTheDocument()
})

it('shows the reference and phone when opened directly', () => {
  renderAt(null)
  expect(screen.queryByRole('heading', { name: "You're booked" })).not.toBeInTheDocument()
  expect(screen.getByText(/Your booking reference is ABCD-EFGH\./)).toHaveTextContent(
    'Your booking reference is ABCD-EFGH. Call us on 01632 960123 if you need to change it.',
  )
})

it('ignores a summary for a different booking', () => {
  renderAt({ ...SUMMARY, reference: 'ZZZZ-ZZZZ' })
  expect(screen.queryByRole('heading', { name: "You're booked" })).not.toBeInTheDocument()
})
