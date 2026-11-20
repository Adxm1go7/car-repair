import type { JSX } from 'react'

/** Next to a form's submit button. Opens in a new tab, so a hold or a half-typed form is kept;
 * a plain link because the booking form is also rendered outside the router in tests. */
export function PrivacyLink(): JSX.Element {
  return (
    <p className="privacy-link">
      <a href="/privacy" target="_blank" rel="noopener">
        How we use your details (opens in a new tab)
      </a>
    </p>
  )
}
