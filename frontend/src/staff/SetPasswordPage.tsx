import { useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { setPassword } from './api.ts'

const MIN_LENGTH = 8
const INVALID = "This link isn't valid any more"
const FAILED = 'Something went wrong. Please try again.'

/** The token from "#t=…". Never in the path or query, so it isn't logged. */
function tokenFrom(hash: string): string | null {
  const token = new URLSearchParams(hash.slice(1)).get('t')
  return token ? token : null
}

function InvalidLink(): JSX.Element {
  return (
    <>
      <p role="alert" className="staff-alert">
        {INVALID}
      </p>
      <p>
        Ask the garage&apos;s admin for a new link, or{' '}
        <Link to="/staff/forgot-password">Forgot your password?</Link>
      </p>
    </>
  )
}

export function SetPasswordPage(): JSX.Element {
  const navigate = useNavigate()
  const token = tokenFrom(useLocation().hash)
  const [password, setPasswordText] = useState('')
  const [tooShort, setTooShort] = useState(false)
  const [state, setState] = useState<'idle' | 'busy' | 'invalid' | 'failed'>('idle')

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (!token) return
    if (password.length < MIN_LENGTH) {
      setTooShort(true)
      return
    }
    setTooShort(false)
    setState('busy')
    const result = await setPassword(token, password)
    if (result.ok) {
      void navigate('/staff', { replace: true })
      return
    }
    setState(result.kind === 'error' && result.detail === INVALID ? 'invalid' : 'failed')
  }

  return (
    <main className="staff-auth">
      <h1>Set your password</h1>
      {!token || state === 'invalid' ? (
        <InvalidLink />
      ) : (
        <form className="staff-form" onSubmit={(event) => void submit(event)} noValidate>
          <div className="field">
            <label htmlFor="new-password">New password</label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              aria-describedby="new-password-hint"
              aria-invalid={tooShort}
              value={password}
              onChange={(event) => setPasswordText(event.target.value)}
            />
            <p id="new-password-hint" className={tooShort ? 'field-error' : 'staff-hint'}>
              Use at least {MIN_LENGTH} characters
            </p>
          </div>
          {state === 'failed' && (
            <p role="alert" className="staff-alert">
              {FAILED}
            </p>
          )}
          <button type="submit" className="staff-button" disabled={state === 'busy'}>
            Set password
          </button>
        </form>
      )}
    </main>
  )
}
