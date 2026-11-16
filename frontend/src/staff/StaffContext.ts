import { createContext, useContext, useEffect, useState } from 'react'
import type { Garage } from '../catalogue/types.ts'
import type { StaffMe } from './types.ts'

/** `garage` is null until the public garage details load (its name and time zone). */
export type StaffContextValue = { me: StaffMe; refresh: () => Promise<void>; garage: Garage | null }

/** The public garage details. Best effort: stays null if they don't load. */
export function useGarage(): Garage | null {
  const [garage, setGarage] = useState<Garage | null>(null)
  useEffect(() => {
    let cancelled = false
    void fetch('/api/garage')
      .then((response) => (response.ok ? (response.json() as Promise<Garage>) : null))
      .then((loaded) => {
        if (!cancelled && loaded) setGarage(loaded)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])
  return garage
}

export const StaffContext = createContext<StaffContextValue | null>(null)

/** The logged-in user. Only for pages inside the logged-in part of StaffApp. */
export function useStaff(): StaffContextValue {
  const value = useContext(StaffContext)
  if (!value) throw new Error('useStaff outside the logged-in staff pages')
  return value
}

export const LOGIN_PATH = '/staff/login'

/** Where to go after logging in: `next` if it's a staff page, otherwise the day view. */
export function safeNext(next: string | null): string {
  return next && /^\/staff(\/|\?|$)/.test(next) && !next.startsWith(LOGIN_PATH) ? next : '/staff'
}

export function loginUrl(returnTo: string): string {
  return `${LOGIN_PATH}?next=${encodeURIComponent(returnTo)}`
}
