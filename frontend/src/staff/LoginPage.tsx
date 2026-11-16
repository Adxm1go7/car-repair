import { useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { login } from './api.ts'
import { safeNext } from './StaffContext.ts'

const WRONG = 'Email or password is wrong'
const FAILED = 'Something went wrong. Please try again.'

export function LoginPage(): JSX.Element {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    setBusy(true)
    const result = await login(email, password)
    setBusy(false)
    if (result.ok) {
      void navigate(safeNext(searchParams.get('next')), { replace: true })
      return
    }
    setError(result.kind === 'unauthorised' ? WRONG : FAILED)
  }

  return (
    <main className="staff-auth">
      <h1>Staff login</h1>
      <form className="staff-form" onSubmit={(event) => void submit(event)}>
        <div className="field">
          <label htmlFor="staff-email">Email</label>
          <input
            id="staff-email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="staff-password">Password</label>
          <input
            id="staff-password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        {error && (
          <p role="alert" className="staff-alert">
            {error}
          </p>
        )}
        <button type="submit" className="staff-button" disabled={busy}>
          Log in
        </button>
      </form>
      <p>
        <Link to="/staff/forgot-password">Forgot your password?</Link>
      </p>
    </main>
  )
}
