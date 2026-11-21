import { useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { Link } from 'react-router'
import { Honeypot } from '../booking/Honeypot.tsx'
import { PrivacyLink } from '../PrivacyLink.tsx'
import { DemoWarning } from '../demo/DemoBanner.tsx'
import { checkDescription, validateDetails } from '../booking/validation.ts'
import type { Garage } from '../catalogue/types.ts'
import { sendEnquiry } from './api.ts'
import type { EnquiryDetails } from './api.ts'

type FieldName = keyof EnquiryDetails
type Errors = Partial<Record<FieldName, string>>

const EMPTY: EnquiryDetails = { name: '', phone: '', email: '', registration: '', make: '', model: '', description: '' }

const FIELDS: { key: Exclude<FieldName, 'description'>; label: string; type?: string; autoComplete?: string }[] = [
  { key: 'name', label: 'Name', autoComplete: 'name' },
  { key: 'phone', label: 'Phone', type: 'tel', autoComplete: 'tel' },
  { key: 'email', label: 'Email', type: 'email', autoComplete: 'email' },
  { key: 'registration', label: 'Registration', autoComplete: 'off' },
  { key: 'make', label: 'Make' },
  { key: 'model', label: 'Model' },
]
const ORDER: FieldName[] = [...FIELDS.map((field) => field.key), 'description']

function telHref(phone: string): string {
  return `tel:${phone.replace(/\s+/g, '')}`
}

/** Each field's problem, in the order the fields appear. */
function check(values: EnquiryDetails): Errors {
  const errors: Errors = { ...validateDetails({ ...values, notes: '' }) } // blank notes: never wrong
  const description = checkDescription(values.description)
  if (description !== null) errors.description = description
  return errors
}

/** "email: Please enter…" from the server, split into the field and its message. */
function fieldError(detail: string | null): Errors | null {
  const match = detail?.match(/^(\w+): (.+)$/)
  const field = ORDER.find((key) => key === match?.[1])
  return match && field ? { [field]: match[2] } : null
}

function trimmed(values: EnquiryDetails): EnquiryDetails {
  return Object.fromEntries(Object.entries(values).map(([key, value]) => [key, value.trim()])) as EnquiryDetails
}

/** `/enquiry`: a customer who doesn't know what's wrong describes the problem. */
export function EnquiryPage({ garage }: { garage: Garage }): JSX.Element {
  const [values, setValues] = useState<EnquiryDetails>(EMPTY)
  const [errors, setErrors] = useState<Errors>({})
  const [problem, setProblem] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [website, setWebsite] = useState('') // the honeypot
  const [sentTo, setSentTo] = useState<string | null>(null)
  const phone = <a href={telHref(garage.phone)}>{garage.phone}</a>

  function update(key: FieldName, value: string): void {
    setValues((now) => ({ ...now, [key]: value }))
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (sending) return
    const found = check(values)
    setErrors(found)
    setProblem(null)
    const first = ORDER.find((key) => found[key] !== undefined)
    if (first !== undefined) {
      document.getElementById(`field-${first}`)?.focus() // so a screen reader reads the error
      return
    }
    setSending(true)
    const result = await sendEnquiry(trimmed(values), website)
    setSending(false)
    if (result.ok) {
      setSentTo(result.data.email)
      return
    }
    const forField = fieldError(result.detail)
    if (forField) setErrors(forField)
    else setProblem(result.detail ?? `Sorry, we couldn't send your enquiry. Please try again, or call us on ${garage.phone}.`)
  }

  if (sentTo !== null) {
    return (
      <main className="page booked">
        <h1 className="step-title">Enquiry sent</h1>
        <p>{`Thanks — we've got your enquiry and emailed a copy to ${sentTo}.`}</p>
        <p>We&apos;ll look at it and get back to you by phone or email. If it&apos;s urgent, call us on {phone}.</p>
        <p>
          <Link to="/">Back to {garage.name}</Link>
        </p>
      </main>
    )
  }

  function describedBy(key: FieldName): string | undefined {
    return errors[key] ? `field-${key}-error` : undefined
  }

  return (
    <main className="page">
      <h1 className="step-title">Ask about a problem</h1>
      <p>
        Not sure what&apos;s wrong? Tell us what&apos;s happening and we&apos;ll get back to you, usually within a
        working day. Nothing is booked or paid yet.
      </p>
      <form
        className="details"
        aria-label="Your enquiry"
        aria-busy={sending || undefined}
        noValidate
        onSubmit={(event) => void submit(event)}
      >
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
          <label htmlFor="field-description">Describe the problem</label>
          <p id="field-description-hint" className="field-hint">
            What happens, when it happens, and any warning lights or noises.
          </p>
          <textarea
            id="field-description"
            name="description"
            rows={5}
            maxLength={1000}
            value={values.description}
            aria-invalid={errors.description ? true : undefined}
            aria-describedby={['field-description-hint', describedBy('description')].filter(Boolean).join(' ')}
            onChange={(event) => update('description', event.target.value)}
          />
          {errors.description && (
            <p id="field-description-error" className="field-error">
              {errors.description}
            </p>
          )}
        </div>

        {problem && (
          <p role="alert" className="notice">
            {problem}
          </p>
        )}

        <Honeypot value={website} onChange={setWebsite} />

        {garage.demo_site && <DemoWarning />}
        <PrivacyLink />

        <button type="submit" className="button" disabled={sending}>
          {sending ? 'Sending…' : 'Send enquiry'}
        </button>
      </form>
    </main>
  )
}
