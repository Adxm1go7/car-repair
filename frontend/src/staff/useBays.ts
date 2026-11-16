import { useEffect, useState } from 'react'
import { fetchBays } from './api.ts'
import type { ScheduleBay } from './types.ts'

/** The active bays with their names, from `date`'s schedule (bays don't change from day to
 * day, so any date does). Empty until loaded, and if loading fails. */
export function useBays(date: string): ScheduleBay[] {
  const [bays, setBays] = useState<ScheduleBay[]>([])
  useEffect(() => {
    let cancelled = false
    void fetchBays(date).then((result) => {
      if (!cancelled && result.ok) setBays(result.data.bays)
    })
    return () => {
      cancelled = true
    }
  }, [date])
  return bays
}
