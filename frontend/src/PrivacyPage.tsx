import { useEffect, type JSX } from 'react'
import { Link } from 'react-router'
import type { Garage } from './catalogue/types.ts'

function telHref(phone: string): string {
  return `tel:${phone.replace(/\s+/g, '')}`
}

/** The short privacy note: what we keep, why, who sees it, and for how long. */
export function PrivacyPage({ garage }: { garage: Garage }): JSX.Element {
  useEffect(() => {
    document.title = 'Privacy'
  }, [])

  return (
    <main className="page privacy">
      <p>
        <Link to="/">← {garage.name}</Link>
      </p>
      <h1>Privacy</h1>
      <p className="note">This is a demo garage. Every name, car and booking in it is made up.</p>

      <h2>What we collect</h2>
      <p>
        When you book or send an enquiry: your name, phone number, email address, your car&apos;s
        registration, make and model, and any notes or description you add.
      </p>

      <h2>Why</h2>
      <p>To book your car in, and to contact you about that booking or enquiry. Nothing else.</p>

      <h2>Who sees it</h2>
      <p>Only the garage&apos;s staff.</p>

      <h2>Other services we use</h2>
      <ul>
        <li>An email provider, to send your booking emails.</li>
        <li>
          Stripe, to take deposits. Stripe handles your card, so we never see your card details. We
          give Stripe your email address for the payment, and Stripe keeps its own record of the
          payment under its own privacy policy.
        </li>
      </ul>

      <h2>How long we keep it</h2>
      <p>
        We remove your personal details 12 months after your appointment, or 12 months after an
        enquiry we didn&apos;t book in.
      </p>

      <h2>Questions</h2>
      <p>
        Call us on <a href={telHref(garage.phone)}>{garage.phone}</a> or email{' '}
        <a href={`mailto:${garage.email}`}>{garage.email}</a>.
      </p>
    </main>
  )
}
