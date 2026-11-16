import { useCallback, useEffect, useState } from 'react'
import { staffRequest } from '../api.ts'
import type { Schedule } from '../types.ts'

export const REFRESH_MS = 30_000

export type ScheduleState =
  | { kind: 'loading' }
  | { kind: 'failed' }
  | { kind: 'ready'; schedule: Schedule }

type Loaded = { key: string; state: ScheduleState }

/**
 * The schedule for `days` days from `from`. Re-fetches every 30 seconds while the page is
 * visible, and as soon as it becomes visible again. A 401 goes to the login page (staffRequest).
 */
export function useSchedule(from: string, days: 1 | 7): { state: ScheduleState; reload: () => void } {
  const key = `from=${from}&days=${days}`
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    void staffRequest<Schedule>(`/schedule?${key}`).then((result) => {
      if (cancelled) return
      if (result.ok) setLoaded({ key, state: { kind: 'ready', schedule: result.data } })
      // A failed refresh keeps the schedule already on screen.
      else if (result.kind !== 'unauthorised')
        setLoaded((previous) => (previous?.key === key && previous.state.kind === 'ready' ? previous : { key, state: { kind: 'failed' } }))
    })
    return () => {
      cancelled = true
    }
  }, [key, tick])

  useEffect(() => {
    const refresh = (): void => {
      if (document.visibilityState === 'visible') setTick((n) => n + 1)
    }
    const timer = window.setInterval(refresh, REFRESH_MS)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [])

  const reload = useCallback(() => setTick((n) => n + 1), [])
  // A different day's schedule is never shown while this one loads.
  const state = loaded && loaded.key === key ? loaded.state : { kind: 'loading' as const }
  return { state, reload }
}
