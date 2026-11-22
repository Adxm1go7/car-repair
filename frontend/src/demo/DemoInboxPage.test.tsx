import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { WARNING } from './DemoBanner.tsx'
import { DemoEmailPage, DemoInboxPage } from './DemoInboxPage.tsx'

const SUMMARY = {
  id: 7,
  to: 'sam@example.com',
  subject: 'Your booking is confirmed — ABCD-EFGH',
  sent_at: '2026-11-21T10:05:00+00:00',
}
const LINK = `${window.location.origin}/booking/ABCD-EFGH#t=tok`
const EMAIL = { ...SUMMARY, text: `Manage it: ${LINK}`, html: '<p>html body</p>' }

function stub(routes: Record<string, { status: number; body: unknown }>): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const reply = routes[url] ?? { status: 404, body: {} }
      return Promise.resolve(new Response(JSON.stringify(reply.body), { status: reply.status }))
    }),
  )
}

function renderAt(entry: string): void {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/demo-inbox" element={<DemoInboxPage zone="Europe/London" />} />
        <Route path="/demo-inbox/:id" element={<DemoEmailPage zone="Europe/London" />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

it('lists the emails under the warning, and opens one', async () => {
  stub({ '/api/demo-inbox': { status: 200, body: [SUMMARY] }, '/api/demo-inbox/7': { status: 200, body: EMAIL } })
  renderAt('/demo-inbox')

  expect(await screen.findByRole('heading', { level: 1, name: 'Demo inbox' })).toBeInTheDocument()
  expect(screen.getByText(WARNING)).toBeInTheDocument()
  expect(screen.getByText(/sam@example\.com/)).toBeInTheDocument()
  expect(screen.getByText(/Sat 21 Nov, 10:05/)).toBeInTheDocument()

  await userEvent.setup().click(screen.getByRole('link', { name: SUMMARY.subject }))

  expect(await screen.findByRole('heading', { level: 1, name: SUMMARY.subject })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: LINK })).toHaveAttribute('href', LINK)
  expect(screen.queryByText('html body')).not.toBeInTheDocument() // the HTML body is never put on the page
})

it('says so when there are no emails yet', async () => {
  stub({ '/api/demo-inbox': { status: 200, body: [] } })
  renderAt('/demo-inbox')
  expect(
    await screen.findByText('No emails yet. Book something and its emails will appear here.'),
  ).toBeInTheDocument()
})

it('shows an alert when the inbox does not load', async () => {
  stub({ '/api/demo-inbox': { status: 500, body: {} } })
  renderAt('/demo-inbox')
  expect(await screen.findByRole('alert')).toHaveTextContent("Sorry, we couldn't load the inbox.")
})

it('shows an alert for an email that is not there', async () => {
  stub({})
  renderAt('/demo-inbox/99')
  expect(await screen.findByRole('alert')).toHaveTextContent("Sorry, we couldn't load that email.")
})
