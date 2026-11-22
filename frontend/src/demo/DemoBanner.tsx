import type { JSX } from 'react'

// Shown only on the public live demo (`demo_site` from /api/garage).

export const BANNER =
  "This is a demo. Pay with Stripe's test card 4242 4242 4242 4242. Emails appear in the Demo inbox. Everything resets nightly."

export const WARNING = "Everyone can see this inbox. Don't use real names, emails or car details."

// The seed's shared demo logins (backend/app/demo_data.py DEMO_STAFF), public on purpose.
const LOGINS = [
  { role: 'Admin', email: 'admin@example.test', password: 'demo-admin-pass' },
  { role: 'Staff', email: 'staff@example.test', password: 'demo-staff-pass' },
]

/** A strip at the top of every page of the demo. */
export function DemoBanner(): JSX.Element {
  return (
    <p role="note" className="demo-banner">
      {BANNER}
    </p>
  )
}

/** Next to any form whose emails go to the shared inbox, and on the inbox itself. */
export function DemoWarning(): JSX.Element {
  return <p className="demo-warning">{WARNING}</p>
}

/** On the staff login page of the demo. */
export function DemoLogins(): JSX.Element {
  return (
    <section className="demo-logins" aria-labelledby="demo-logins-heading">
      <h2 id="demo-logins-heading">Demo logins</h2>
      <dl>
        {LOGINS.map((login) => (
          <div key={login.email}>
            <dt>{login.role}</dt>
            <dd>
              <code>{login.email}</code> / <code>{login.password}</code>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
