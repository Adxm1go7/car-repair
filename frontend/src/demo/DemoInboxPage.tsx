import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import { Link, useParams } from 'react-router'
import { formatTime } from '../booking/format.ts'
import { fetchInbox, fetchInboxEmail } from './api.ts'
import type { InboxEmail, InboxSummary, Loaded } from './api.ts'
import { DemoWarning } from './DemoBanner.tsx'
import { linkify } from './linkify.ts'

type State<T> = { kind: 'loading' } | { kind: 'failed' } | { kind: 'ready'; data: T }

/** Loads once per `key`. Each email page is its own route, so a page never shows another's. */
function useLoaded<T>(loader: () => Promise<Loaded<T>>, key: string): State<T> {
  const [state, setState] = useState<State<T>>({ kind: 'loading' })
  useEffect(() => {
    let cancelled = false
    void loader().then((result) => {
      if (!cancelled) setState(result.ok ? { kind: 'ready', data: result.data } : { kind: 'failed' })
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` names what is loaded
  }, [key])
  return state
}

/** "Sat 21 Nov, 10:05" in the garage's zone. */
function sentAt(iso: string, zone: string): string {
  const day = new Intl.DateTimeFormat('en-GB', { timeZone: zone, weekday: 'short', day: 'numeric', month: 'short' })
  return `${day.format(new Date(iso))}, ${formatTime(iso, zone)}`
}

/** The live demo's shared inbox: the latest emails the site would have sent. */
export function DemoInboxPage({ zone }: { zone: string }): JSX.Element {
  const state = useLoaded(fetchInbox, 'inbox')
  useEffect(() => {
    document.title = 'Demo inbox'
  }, [])

  return (
    <main className="page demo-inbox">
      <h1>Demo inbox</h1>
      <p>The emails this demo would have sent, newest first. Nothing is really sent.</p>
      <DemoWarning />
      {state.kind === 'loading' && <p>Loading…</p>}
      {state.kind === 'failed' && (
        <div role="alert" className="error">
          <p>{"Sorry, we couldn't load the inbox."}</p>
        </div>
      )}
      {state.kind === 'ready' && state.data.length === 0 && (
        <p>No emails yet. Book something and its emails will appear here.</p>
      )}
      {state.kind === 'ready' && state.data.length > 0 && (
        <ul className="demo-inbox-list">
          {state.data.map((email: InboxSummary) => (
            <li key={email.id}>
              <Link to={`/demo-inbox/${email.id}`}>{email.subject}</Link>
              <span className="demo-inbox-meta">
                To {email.to} · {sentAt(email.sent_at, zone)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}

/** One email from the inbox, as plain text. Only links back to this site are clickable; the
 * HTML version is never put on the page. */
export function DemoEmailPage({ zone }: { zone: string }): JSX.Element {
  const { id = '' } = useParams()
  const state = useLoaded(() => fetchInboxEmail(id), id)

  useEffect(() => {
    document.title = state.kind === 'ready' ? state.data.subject : 'Demo inbox'
  }, [state])

  return (
    <main className="page demo-inbox">
      <p>
        <Link to="/demo-inbox">Back to the Demo inbox</Link>
      </p>
      {state.kind === 'loading' && <p>Loading…</p>}
      {state.kind === 'failed' && (
        <div role="alert" className="error">
          <p>{"Sorry, we couldn't load that email."}</p>
        </div>
      )}
      {state.kind === 'ready' && <EmailView email={state.data} zone={zone} />}
    </main>
  )
}

function EmailView({ email, zone }: { email: InboxEmail; zone: string }): JSX.Element {
  return (
    <article>
      <h1>{email.subject}</h1>
      <p className="demo-inbox-meta">
        To {email.to} · {sentAt(email.sent_at, zone)}
      </p>
      <pre className="demo-email-text">
        {linkify(email.text, window.location.origin).map((part, index) =>
          typeof part === 'string' ? (
            part
          ) : (
            <a key={index} href={part.href}>
              {part.label}
            </a>
          ),
        )}
      </pre>
    </article>
  )
}
