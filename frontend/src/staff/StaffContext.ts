import { createContext, useContext } from 'react'
import type { StaffMe } from './types.ts'

export type StaffContextValue = { me: StaffMe; refresh: () => Promise<void> }

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
