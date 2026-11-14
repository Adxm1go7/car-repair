import { EmbeddedCheckout, EmbeddedCheckoutProvider } from '@stripe/react-stripe-js'
import { loadStripe } from '@stripe/stripe-js'
import type { Stripe } from '@stripe/stripe-js'
import { useEffect, useRef } from 'react'
import type { JSX } from 'react'

// Stripe.js is loaded once per key, outside render, as Stripe requires.
const loaded = new Map<string, Promise<Stripe | null>>()

function stripeFor(publishableKey: string): Promise<Stripe | null> {
  let stripe = loaded.get(publishableKey)
  if (!stripe) {
    stripe = loadStripe(publishableKey)
    loaded.set(publishableKey, stripe)
  }
  return stripe
}

type Props = { publishableKey: string; clientSecret: string; onComplete: () => void }

/**
 * Stripe's own payment form, shown inside our page. It reports completion through
 * `onComplete`, which only tells the page to ask our server: it is never proof of payment.
 */
export function StripeCheckout({ publishableKey, clientSecret, onComplete }: Props): JSX.Element {
  // Stripe reads the options once, so the latest callback is passed through a ref.
  const latest = useRef(onComplete)
  useEffect(() => {
    latest.current = onComplete
  })

  return (
    <EmbeddedCheckoutProvider
      stripe={stripeFor(publishableKey)}
      options={{ clientSecret, onComplete: () => latest.current() }}
    >
      <EmbeddedCheckout className="stripe-checkout" />
    </EmbeddedCheckoutProvider>
  )
}
