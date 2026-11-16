import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router'
import type { Garage } from '../catalogue/types.ts'
import { logout } from './api.ts'
import { LOGIN_PATH, useStaff } from './StaffContext.ts'

/** The garage's name for the top bar. Best effort: the bar says "Staff" until it loads. */
function useGarageName(): string | null {
  const [name, setName] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    void fetch('/api/garage')
      .then((response) => (response.ok ? (response.json() as Promise<Garage>) : null))
      .then((garage) => {
        if (!cancelled && garage) setName(garage.name)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])
  return name
}

export function StaffLayout(): JSX.Element {
  const { me } = useStaff()
  const navigate = useNavigate()
  const garageName = useGarageName()
  const isAdmin = me.role === 'admin'

  async function logOut(): Promise<void> {
    await logout()
    void navigate(LOGIN_PATH, { replace: true })
  }

  return (
    <div className="staff">
      <header className="staff-bar">
        <span className="staff-garage">{garageName ?? 'Staff'}</span>
        <nav className="staff-nav" aria-label="Staff">
          <NavLink to="/staff" end>
            Day
          </NavLink>
          <NavLink to="/staff/week">Week</NavLink>
          {isAdmin && <NavLink to="/staff/team">Team</NavLink>}
          {isAdmin && <NavLink to="/staff/audit">Audit</NavLink>}
        </nav>
        <span className="staff-user">
          <span>{me.name}</span>
          <button type="button" className="staff-button staff-button-quiet" onClick={() => void logOut()}>
            Log out
          </button>
        </span>
      </header>
      <main className="staff-page">
        <Outlet />
      </main>
    </div>
  )
}
