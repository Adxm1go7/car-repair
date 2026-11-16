import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { MOVE_OPTIONS } from '../../testing/schedule.ts'
import { TimePickerGrid } from './TimePickerGrid.tsx'

const BAYS = [
  { id: 1, name: 'MOT bay' },
  { id: 2, name: 'Bay 1' },
]

it('picks the first bay with the time, and another bay when tapped', async () => {
  const onPick = vi.fn()
  const { rerender } = render(
    <TimePickerGrid slots={MOVE_OPTIONS.slots} bays={BAYS} zone="Europe/London" selected={null} onPick={onPick} />,
  )
  expect(screen.queryByRole('button', { name: 'MOT bay' })).not.toBeInTheDocument()

  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '11:00' }))
  expect(onPick).toHaveBeenLastCalledWith('2026-11-17T11:00:00+00:00', 1)

  rerender(
    <TimePickerGrid
      slots={MOVE_OPTIONS.slots}
      bays={BAYS}
      zone="Europe/London"
      selected={{ start: '2026-11-17T11:00:00+00:00', bayId: 1 }}
      onPick={onPick}
    />,
  )
  await user.click(screen.getByRole('button', { name: 'Bay 1' }))
  expect(onPick).toHaveBeenLastCalledWith('2026-11-17T11:00:00+00:00', 2)
})

it('shows times in the garage zone and a bay with no name by number', () => {
  render(
    <TimePickerGrid
      slots={[{ start: '2026-06-17T08:00:00+00:00', end: '2026-06-17T09:00:00+00:00', bay_ids: [9] }]}
      bays={BAYS}
      zone="Europe/London"
      selected={{ start: '2026-06-17T08:00:00+00:00', bayId: 9 }}
      onPick={() => undefined}
    />,
  )
  expect(screen.getByRole('button', { name: '09:00' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('button', { name: 'Bay 9' })).toBeInTheDocument()
})

it('says when there are no times', () => {
  render(<TimePickerGrid slots={[]} bays={BAYS} zone="Europe/London" selected={null} onPick={() => undefined} />)
  expect(screen.getByText('No free times that day')).toBeInTheDocument()
})
