import { useCallback, useEffect, useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { checkEmail, checkPhone } from '../../booking/validation.ts'
import { fetchContact, saveContact } from '../api.ts'
import type { Contact, StaffResult } from '../api.ts'
import { failure } from './shared.ts'

type Field = keyof Contact
type Errors = Partial<Record<Field, string>>
type Loaded = { kind: 'loading' } | { kind: 'failed' } | { kind: 'loaded' }

const FIELDS: { field: Field; label: string; maxLength: number; type?: string }[] = [
  { field: 'name', label: 'Garage name', maxLength: 100 },
  { field: 'address', label: 'Address', maxLength: 200 },
  { field: 'phone', label: 'Phone', maxLength: 20, type: 'tel' },
  { field: 'email', label: 'Email', maxLength: 254, type: 'email' },
]

/** Each field's problem, checked like a customer's phone and email. The server checks again. */
function check(contact: Contact): Errors {
  const errors: Errors = {}
  if (!contact.name.trim()) errors.name = 'Please enter the garage name'
  if (!contact.address.trim()) errors.address = 'Please enter the address'
  const phone = checkPhone(contact.phone)
  if (phone) errors.phone = phone
  const email = checkEmail(contact.email)
  if (email) errors.email = email
  return errors
}

/** The Contact tab: the garage's name, address, phone and email, as the site and emails show them. */
export function ContactTab(): JSX.Element {
  const [state, setState] = useState<Loaded>({ kind: 'loading' })
  const [contact, setContact] = useState<Contact>({ name: '', address: '', phone: '', email: '' })
  const [errors, setErrors] = useState<Errors>({})
  const [alert, setAlert] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const show = useCallback((result: StaffResult<Contact>): void => {
    if (result.ok) {
      setContact(result.data)
      setState({ kind: 'loaded' })
    } else if (result.kind !== 'unauthorised') {
      setState({ kind: 'failed' })
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    void fetchContact().then((result) => {
      if (!cancelled) show(result)
    })
    return () => {
      cancelled = true
    }
  }, [show])

  async function retry(): Promise<void> {
    setState({ kind: 'loading' })
    show(await fetchContact())
  }

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    const found = check(contact)
    setErrors(found)
    setAlert(null)
    setNotice(null)
    if (Object.keys(found).length > 0) return
    setBusy(true)
    const result = await saveContact({
      name: contact.name.trim(),
      address: contact.address.trim(),
      phone: contact.phone.trim(),
      email: contact.email.trim(),
    })
    setBusy(false)
    if (result.ok) {
      setContact(result.data)
      setNotice('Contact details saved. The site and every email sent from now on use them.')
    } else {
      setAlert(failure(result))
    }
  }

  return (
    <section className="settings-tab" aria-labelledby="contact-heading">
      <h2 id="contact-heading">Contact</h2>
      <p role="status" className="team-notice">
        {notice}
      </p>
      {state.kind === 'loading' && <p>Loading…</p>}
      {state.kind === 'failed' && (
        <>
          <p role="alert" className="staff-alert">
            {"Sorry, we couldn't load the contact details."}
          </p>
          <button type="button" className="staff-button" onClick={() => void retry()}>
            Try again
          </button>
        </>
      )}
      {state.kind === 'loaded' && (
        <form className="staff-form settings-form" aria-label="Contact details" onSubmit={(e) => void submit(e)} noValidate>
          {alert && (
            <p role="alert" className="staff-alert">
              {alert}
            </p>
          )}
          {FIELDS.map(({ field, label, maxLength, type }) => {
            const id = `contact-${field}`
            return (
              <div key={field} className="field">
                <label htmlFor={id}>{label}</label>
                <input
                  id={id}
                  type={type ?? 'text'}
                  maxLength={maxLength}
                  value={contact[field]}
                  aria-invalid={errors[field] ? true : undefined}
                  aria-describedby={errors[field] ? `${id}-error` : undefined}
                  onChange={(event) => setContact((current) => ({ ...current, [field]: event.target.value }))}
                />
                {errors[field] && (
                  <span id={`${id}-error`} className="field-error">
                    {errors[field]}
                  </span>
                )}
              </div>
            )
          })}
          <p className="staff-hint">
            Changes show on the site at once, and in every email sent from now on, including ones already waiting to
            go.
          </p>
          <button type="submit" className="staff-button" disabled={busy}>
            Save
          </button>
        </form>
      )}
    </section>
  )
}
