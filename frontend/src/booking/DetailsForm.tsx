import { useEffect, useRef, useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { startCheckout } from './api.ts'
import { formatLongDate, formatTimeRange } from './format.ts'
import type { Checkout, CustomerDetails, Hold } from './types.ts'
import { formatCountdown, useCountdown } from './useCountdown.ts'
import { validateDetails } from './validation.ts'
import type { FieldErrors } from './validation.ts'

/**
 * The typed details belong to the page (`values` / `onValuesChange`), so they survive the
 * form going away when the customer changes time or the hold runs out.
 */
type Props = {
  hold: Hold
  zone: string
  values: CustomerDetails
  onValuesChange: (values: CustomerDetails) => void
  onSubmittingChange: (submitting: boolean) => void
  onExpired: () => void
  onCheckout: (checkout: Checkout) => void
  /** The server says it's already paid (a double tap after paying): the page checks status. */
  onAlreadyPaid: () => void
}

type Field = {
  key: keyof CustomerDetails
  label: string
  type?: string
  autoComplete?: string
}

const FIELDS: Field[] = [
  { key: 'name', label: 'Name', autoComplete: 'name' },
  { key: 'phone', label: 'Phone', type: 'tel', autoComplete: 'tel' },
  { key: 'email', label: 'Email', type: 'email', autoComplete: 'email' },
  { key: 'registration', label: 'Registration', autoComplete: 'off' },
  { key: 'make', label: 'Make' },
  { key: 'model', label: 'Model' },
]

/** What a screen reader hears. It changes only at these moments, so it isn't read every second. */
function announcement(remaining: number): string {
  if (remaining === 0) return 'Your hold has run out'
  if (remaining <= 60) return '1 minute left to continue'
  if (remaining <= 300) return '5 minutes left to continue'
  return ''
}

/** "phone: Please enter…" from the server, split into the field and its message. */
function fieldError(detail: string | null): FieldErrors | null {
  const match = detail?.match(/^(\w+): (.+)$/)
  if (!match) return null
  const field = [...FIELDS.map((f) => f.key), 'notes'].find((key) => key === match[1])
  return field ? { [field]: match[2] } : null
}

export function DetailsForm(props: Props): JSX.Element {
  const { hold, zone, values, onValuesChange, onSubmittingChange, onExpired, onCheckout, onAlreadyPaid } = props
  const [errors, setErrors] = useState<FieldErrors>({})
  const [problem, setProblem] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // Expiry, a reply and leaving the form can race; only the first one counts.
  const finished = useRef(false)

  useEffect(() => {
    finished.current = false
    return () => {
      finished.current = true // gone: a late reply must not act
    }
  }, [])

  function expire(): void {
    if (finished.current) return
    finished.current = true
    onExpired()
  }

  // While a checkout is in flight the server decides, not this page's countdown: the
  // request may have reached the server in time even though the reply arrives after zero.
  const inFlight = useRef(false)
  const timeUp = useRef(false)

  function countdownEnded(): void {
    if (inFlight.current) timeUp.current = true
    else expire()
  }

  function setSending(sending: boolean): void {
    inFlight.current = sending
    setSubmitting(sending)
    onSubmittingChange(sending)
  }

  const remaining = useCountdown(hold.expires_in_seconds, countdownEnded)

  function update(key: keyof CustomerDetails, value: string): void {
    onValuesChange({ ...values, [key]: value })
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (submitting || finished.current) return
    const found = validateDetails(values)
    setErrors(found)
    setProblem(null)
    const first = Object.keys(found)[0] // fields are checked in the order they appear
    if (first !== undefined) {
      document.getElementById(`field-${first}`)?.focus() // so a screen reader reads the error
      return
    }

    setSending(true)
    const result = await startCheckout(hold.reference, hold.hold_token, values)
    if (finished.current) return
    if (result.ok) {
      finished.current = true
      onCheckout(result.data) // the server restarted the hold for payment
      return
    }
    if (result.kind === 'paid') {
      finished.current = true
      onAlreadyPaid()
      return
    }
    setSending(false)
    if (result.kind === 'expired' || timeUp.current) {
      expire() // the server said so, or the time ran out and the checkout didn't go through
      return
    }
    const forField = fieldError(result.detail)
    if (forField) setErrors(forField)
    else setProblem(result.detail ?? "Sorry, we couldn't start the payment. Please try again.")
  }

  function describedBy(key: keyof CustomerDetails): string | undefined {
    return errors[key] ? `field-${key}-error` : undefined
  }

  return (
    <form
      className="details"
      aria-label="Your details"
      aria-busy={submitting || undefined}
      noValidate
      onSubmit={(event) => void submit(event)}
    >
      <p className="hold-banner">
        {`We're holding ${formatLongDate(hold.start, zone)}, ${formatTimeRange(hold.start, hold.end, zone)} for `}
        <span role="timer" className="countdown">
          {formatCountdown(remaining)}
        </span>
      </p>
      <div data-testid="countdown-announcer" className="visually-hidden" aria-live="polite">
        {announcement(remaining)}
      </div>

      {FIELDS.map(({ key, label, type, autoComplete }) => (
        <div key={key} className="field">
          <label htmlFor={`field-${key}`}>{label}</label>
          <input
            id={`field-${key}`}
            name={key}
            type={type ?? 'text'}
            autoComplete={autoComplete}
            value={values[key]}
            aria-invalid={errors[key] ? true : undefined}
            aria-describedby={describedBy(key)}
            onChange={(event) => update(key, event.target.value)}
          />
          {errors[key] && (
            <p id={`field-${key}-error`} className="field-error">
              {errors[key]}
            </p>
          )}
        </div>
      ))}

      <div className="field">
        <label htmlFor="field-notes">Notes (optional)</label>
        <textarea
          id="field-notes"
          name="notes"
          rows={3}
          value={values.notes}
          aria-invalid={errors.notes ? true : undefined}
          aria-describedby={describedBy('notes')}
          onChange={(event) => update('notes', event.target.value)}
        />
        {errors.notes && (
          <p id="field-notes-error" className="field-error">
            {errors.notes}
          </p>
        )}
      </div>

      {problem && (
        <p role="alert" className="notice">
          {problem}
        </p>
      )}

      <button type="submit" className="button" disabled={submitting}>
        {submitting ? 'Starting payment…' : 'Continue to payment'}
      </button>
    </form>
  )
}
