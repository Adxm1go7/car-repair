import { useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { Link } from 'react-router'
import { forgotPassword } from './api.ts'
import { LOGIN_PATH } from './StaffContext.ts'

// The same words whether or not the email has an account, so the page reveals nothing.
const SENT = "If that address has an account, we've emailed a link"

export function ForgotPasswordPage(): JSX.Element {
  const [email, setEmail] = useState('')
  const [state, setState] = useState<'idle' | 'busy' | 'sent' | 'failed'>('idle')

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    setState('busy')
    const result = await forgotPassword(email)
    // Anything the server answered (a lockout too) gets the same message; only a request
    // that never got through is reported as a failure.
    setState(result.ok || result.kind !== 'error' || result.detail !== null ? 'sent' : 'failed')
  }

  return (
    <main className="staff-auth">
      <h1>Forgot your password?</h1>
      {state === 'sent' ? (
        <p role="status">{SENT}</p>
      ) : (
        <form className="staff-form" onSubmit={(event) => void submit(event)}>
          <p>{"Enter your email and we'll send you a link to set a new password."}</p>
          <div className="field">
            <label htmlFor="forgot-email">Email</label>
            <input
              id="forgot-email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          {state === 'failed' && (
            <p role="alert" className="staff-alert">
              Something went wrong. Please try again.
            </p>
          )}
          <button type="submit" className="staff-button" disabled={state === 'busy'}>
            Email me a link
          </button>
        </form>
      )}
      <p>
        <Link to={LOGIN_PATH}>Back to login</Link>
      </p>
    </main>
  )
}
