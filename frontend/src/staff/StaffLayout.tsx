import type { JSX } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router'
import { logout } from './api.ts'
import { LOGIN_PATH, useStaff } from './StaffContext.ts'

export function StaffLayout(): JSX.Element {
  const { me, garage } = useStaff()
  const navigate = useNavigate()
  // The bar says "Staff" until the garage's name loads.
  const garageName = garage?.name ?? null
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
          {isAdmin && <NavLink to="/staff/settings">Settings</NavLink>}
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
