import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { App } from './App.tsx'

afterEach(() => vi.unstubAllGlobals())

it('shows API ok when health check succeeds', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok', database: 'ok' }), { status: 200 }),
    ),
  )
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Garage Booking' })).toBeInTheDocument()
  expect(await screen.findByText('API: ok')).toBeInTheDocument()
})

it('shows API unavailable on 503', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'error', database: 'unavailable' }), { status: 503 }),
    ),
  )
  render(<App />)
  expect(await screen.findByText('API: unavailable')).toBeInTheDocument()
})

it('shows API unavailable when the request fails', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
  render(<App />)
  expect(await screen.findByText('API: unavailable')).toBeInTheDocument()
})
