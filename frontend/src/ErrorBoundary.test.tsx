import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ErrorBoundary } from './ErrorBoundary.tsx'

function Broken(): never {
  throw new Error('secret stack detail')
}

afterEach(() => vi.restoreAllMocks())

it('shows the something-went-wrong screen without the error text when a child crashes', () => {
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
  render(
    <ErrorBoundary>
      <Broken />
    </ErrorBoundary>,
  )
  expect(screen.getByRole('heading', { level: 1, name: 'Something went wrong' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Go to home page' })).toHaveAttribute('href', '/')
  expect(screen.queryByText(/secret stack detail/)).not.toBeInTheDocument()
  expect(consoleError).toHaveBeenCalled()
})

it('renders its children when nothing goes wrong', () => {
  render(
    <ErrorBoundary>
      <p>All fine</p>
    </ErrorBoundary>,
  )
  expect(screen.getByText('All fine')).toBeInTheDocument()
})
