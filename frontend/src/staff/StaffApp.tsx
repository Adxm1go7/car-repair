import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { JSX, ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router'
import { fetchMe, setUnauthorisedHandler } from './api.ts'
import type { StaffResult } from './api.ts'
import { ForgotPasswordPage } from './ForgotPasswordPage.tsx'
import { LoginPage } from './LoginPage.tsx'
import { SetPasswordPage } from './SetPasswordPage.tsx'
import { AuditPage } from './admin/AuditPage.tsx'
import { TeamPage } from './admin/TeamPage.tsx'
import { BookingDetailPage } from './booking/BookingDetailPage.tsx'
import { EnquiriesPage } from './enquiries/EnquiriesPage.tsx'
import { EnquiryPage } from './enquiries/EnquiryPage.tsx'
import { NewBlockPage } from './forms/NewBlockPage.tsx'
import { NewBookingPage } from './forms/NewBookingPage.tsx'
import { RequestsPage } from './requests/RequestsPage.tsx'
import { DayView } from './schedule/DayView.tsx'
import { WeekView } from './schedule/WeekView.tsx'
import { SettingsPage } from './settings/SettingsPage.tsx'
import { LOGIN_PATH, StaffContext, loginUrl, useGarage, useStaff } from './StaffContext.ts'
import { StaffLayout } from './StaffLayout.tsx'
import type { StaffMe } from './types.ts'
import './staff.css'

const PUBLIC_PATHS = [LOGIN_PATH, '/staff/forgot-password', '/staff/set-password']

type MeState = { kind: 'loading' } | { kind: 'out' } | { kind: 'failed' } | { kind: 'in'; me: StaffMe }

function meState(result: StaffResult<StaffMe>): MeState {
  if (result.ok) return { kind: 'in', me: result.data }
  return result.kind === 'unauthorised' ? { kind: 'out' } : { kind: 'failed' }
}

/** Loads the user once, then shows the staff pages; without a session, the login page. */
function LoggedIn(): JSX.Element {
  const location = useLocation()
  const [state, setState] = useState<MeState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    void fetchMe().then((result) => {
      if (!cancelled) setState(meState(result))
    })
    return () => {
      cancelled = true
    }
  }, [])

  const refresh = useCallback(async (): Promise<void> => {
    setState(meState(await fetchMe()))
  }, [])
  const garage = useGarage()
  const me = state.kind === 'in' ? state.me : null
  const value = useMemo(() => (me ? { me, refresh, garage } : null), [me, refresh, garage])

  if (state.kind === 'out') return <Navigate to={loginUrl(location.pathname + location.search)} replace />
  if (state.kind === 'failed') {
    return (
      <main className="staff-auth">
        <p role="alert" className="staff-alert">
          {"Sorry, we couldn't reach the server."}
        </p>
        <button type="button" className="staff-button" onClick={() => void refresh()}>
          Try again
        </button>
      </main>
    )
  }
  if (!value) return <p className="staff-auth">Loading…</p>
  return (
    <StaffContext.Provider value={value}>
      <StaffLayout />
    </StaffContext.Provider>
  )
}

function AdminOnly({ children }: { children: ReactNode }): JSX.Element {
  const { me } = useStaff()
  return me.role === 'admin' ? <>{children}</> : <p role="alert">{"You don't have access to this page"}</p>
}

/** Everything under /staff. Doesn't wait for the public catalogue the customer pages load. */
export function StaffApp(): JSX.Element {
  const navigate = useNavigate()
  const location = useLocation()
  const here = useRef('/staff')

  useEffect(() => {
    here.current = location.pathname + location.search
  }, [location])

  useEffect(() => {
    setUnauthorisedHandler(() => {
      const path = here.current
      if (PUBLIC_PATHS.some((p) => path.startsWith(p))) return
      void navigate(loginUrl(path), { replace: true })
    })
    return () => setUnauthorisedHandler(null)
  }, [navigate])

  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route path="forgot-password" element={<ForgotPasswordPage />} />
      <Route path="set-password" element={<SetPasswordPage />} />
      <Route element={<LoggedIn />}>
        <Route index element={<DayView />} />
        <Route path="week" element={<WeekView />} />
        <Route path="bookings/new" element={<NewBookingPage />} />
        <Route path="blocks/new" element={<NewBlockPage />} />
        <Route path="bookings/:reference" element={<BookingDetailPage />} />
        <Route path="requests" element={<RequestsPage />} />
        <Route path="enquiries" element={<EnquiriesPage />} />
        <Route path="enquiries/:id" element={<EnquiryPage />} />
        <Route
          path="team"
          element={
            <AdminOnly>
              <TeamPage />
            </AdminOnly>
          }
        />
        <Route
          path="audit"
          element={
            <AdminOnly>
              <AuditPage />
            </AdminOnly>
          }
        />
        <Route path="settings" element={<Navigate to="/staff/settings/services" replace />} />
        <Route
          path="settings/:tab"
          element={
            <AdminOnly>
              <SettingsPage />
            </AdminOnly>
          }
        />
        <Route path="*" element={<p>Page not found</p>} />
      </Route>
    </Routes>
  )
}
