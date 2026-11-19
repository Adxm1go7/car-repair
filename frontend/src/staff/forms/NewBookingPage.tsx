import { useEffect, useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { todayInZone } from '../../booking/days.ts'
import type { CustomerDetails } from '../../booking/types.ts'
import { validateDetails } from '../../booking/validation.ts'
import type { FieldErrors } from '../../booking/validation.ts'
import { fetchCatalogue } from '../../catalogue/api.ts'
import type { Service } from '../../catalogue/types.ts'
import { approveEnquiry, conflictDetail, createPhoneBooking, fetchStaffAvailability } from '../api.ts'
import type { StaffResult } from '../api.ts'
import { TimePickerGrid } from '../booking/TimePickerGrid.tsx'
import type { PickedSlot } from '../booking/TimePickerGrid.tsx'
import { ENQUIRY_HANDLED, FAILED } from '../labels.ts'
import { validDate } from '../schedule/layout.ts'
import { useStaff } from '../StaffContext.ts'
import type { StaffAvailability, StaffEnquiry } from '../types.ts'
import { useBays } from '../useBays.ts'

const MIXED = "These services can't be booked together — please book them separately"
const TAKEN = 'That time has just been taken'

const EMPTY: CustomerDetails = { name: '', phone: '', email: '', registration: '', make: '', model: '', notes: '' }

type FieldName = keyof CustomerDetails
const FIELDS: { name: FieldName; label: string; type?: string; autoComplete?: string }[] = [
  { name: 'name', label: 'Name', autoComplete: 'off' },
  { name: 'phone', label: 'Phone', type: 'tel', autoComplete: 'off' },
  { name: 'email', label: 'Email (optional)', type: 'email', autoComplete: 'off' },
  { name: 'registration', label: 'Registration', autoComplete: 'off' },
  { name: 'make', label: 'Make', autoComplete: 'off' },
  { name: 'model', label: 'Model', autoComplete: 'off' },
]

type Times = { key: string; availability: StaffAvailability | null; failed: boolean }

/** The services from the public catalogue. Needs-approval ones are bookable here: staff
 * booking one is the approval. */
function useServices(): Service[] | null | 'failed' {
  const [services, setServices] = useState<Service[] | null | 'failed'>(null)
  useEffect(() => {
    let cancelled = false
    void fetchCatalogue().then((result) => {
      if (!cancelled) setServices(result.ok ? result.data.services : 'failed')
    })
    return () => {
      cancelled = true
    }
  }, [])
  return services
}

/** Each field's problem; email may be left blank, except when booking in an enquiry. */
function check(values: CustomerDetails, emailRequired: boolean): FieldErrors {
  const errors = validateDetails(values)
  if (!emailRequired && values.email.trim() === '') delete errors.email
  return errors
}

/** The form's starting details: blank, or the enquiry's, with its description as the notes. */
function startingValues(enquiry: StaffEnquiry | undefined): CustomerDetails {
  if (!enquiry) return EMPTY
  return {
    name: enquiry.customer_name,
    phone: enquiry.customer_phone,
    email: enquiry.customer_email,
    registration: enquiry.registration,
    make: enquiry.make,
    model: enquiry.model,
    notes: enquiry.description,
  }
}

function blankToNull(value: string): string | null {
  return value.trim() === '' ? null : value.trim()
}

/**
 * `/staff/bookings/new?date=`: book a customer who phoned. No deposit is taken. With
 * `enquiry`, it books that enquiry in instead: the details start from it and the email is
 * required, because the customer is emailed the booking.
 */
export function NewBookingPage({ enquiry }: { enquiry?: StaffEnquiry } = {}): JSX.Element {
  const navigate = useNavigate()
  const { garage } = useStaff()
  const [params] = useSearchParams()
  const zone = garage?.timezone ?? 'UTC'
  const [date, setDate] = useState(() => validDate(params.get('date')) ?? todayInZone(new Date(), zone))
  const services = useServices()
  const bays = useBays(date)
  const [chosen, setChosen] = useState<string[]>([])
  const [times, setTimes] = useState<Times | null>(null)
  const [reloads, setReloads] = useState(0)
  const [picked, setPicked] = useState<PickedSlot | null>(null)
  const [values, setValues] = useState<CustomerDetails>(() => startingValues(enquiry))
  const [errors, setErrors] = useState<FieldErrors>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const timesKey = chosen.length > 0 ? `${chosen.join(',')}|${date}` : null

  useEffect(() => {
    if (chosen.length === 0) return
    let cancelled = false
    const key = `${chosen.join(',')}|${date}`
    void fetchStaffAvailability(chosen, date).then((result) => {
      if (!cancelled) setTimes({ key, availability: result.ok ? result.data : null, failed: !result.ok })
    })
    return () => {
      cancelled = true
    }
  }, [chosen, date, reloads])

  const current = times && times.key === timesKey ? times : null

  function toggle(slug: string): void {
    setChosen((now) => (now.includes(slug) ? now.filter((s) => s !== slug) : [...now, slug]))
    setPicked(null)
    setFormError(null)
  }

  function changeDate(value: string): void {
    if (!validDate(value)) return
    setDate(value)
    setPicked(null)
  }

  function setField(name: FieldName, value: string): void {
    setValues((now) => ({ ...now, [name]: value }))
  }

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    setMessage(null)
    const fieldErrors = check(values, enquiry !== undefined)
    setErrors(fieldErrors)
    const missing = chosen.length === 0 ? 'Please choose at least one service' : !picked ? 'Please choose a time' : null
    setFormError(missing)
    if (missing || Object.keys(fieldErrors).length > 0 || !picked) return

    setBusy(true)
    const booking = {
      services: chosen,
      start: picked.start,
      bay_id: picked.bayId,
      name: values.name.trim(),
      phone: values.phone.trim(),
      email: blankToNull(values.email),
      registration: values.registration.trim(),
      make: values.make.trim(),
      model: values.model.trim(),
      notes: blankToNull(values.notes),
    }
    if (enquiry) {
      const result = await approveEnquiry(enquiry.id, { ...booking, email: values.email.trim() })
      setBusy(false)
      if (result.ok) {
        void navigate(`/staff/enquiries/${enquiry.id}`, { state: { notice: 'Booked — the customer has been emailed' } })
        return
      }
      if (result.kind === 'conflict' && conflictDetail(result.body) === 'not_new') {
        setMessage(ENQUIRY_HANDLED)
        return
      }
      refused(result)
      return
    }
    const result = await createPhoneBooking(booking)
    setBusy(false)
    if (result.ok) {
      void navigate(`/staff/bookings/${result.data.reference}`)
      return
    }
    refused(result)
  }

  /** A taken time reloads the times; anything else says what went wrong. */
  function refused(result: Exclude<StaffResult<unknown>, { ok: true }>): void {
    if (result.kind === 'conflict') {
      setMessage(TAKEN)
      setPicked(null)
      setReloads((n) => n + 1)
    } else if (result.kind === 'error' && result.detail) setMessage(result.detail)
    else if (result.kind !== 'unauthorised') setMessage(FAILED)
  }

  const fields = enquiry
    ? FIELDS.map((field) => (field.name === 'email' ? { ...field, label: 'Email' } : field))
    : FIELDS

  return (
    <form className="staff-form booking-form" onSubmit={(event) => void submit(event)} noValidate>
      <h1>{enquiry ? 'Book enquiry' : 'New phone booking'}</h1>

      <fieldset>
        <legend>Services</legend>
        {services === null && <p>Loading…</p>}
        {services === 'failed' && <p className="staff-alert">{"Sorry, we couldn't load the services."}</p>}
        {Array.isArray(services) && (
          <div className="service-picks">
            {services.map((service) => (
              <label key={service.slug} className="service-pick">
                <input type="checkbox" checked={chosen.includes(service.slug)} onChange={() => toggle(service.slug)} />
                <span>
                  {service.name}
                  {service.approval_mode === 'needs_approval' && <span className="staff-hint"> · needs approval</span>}
                </span>
              </label>
            ))}
          </div>
        )}
      </fieldset>

      <div className="field">
        <label htmlFor="booking-date">Date</label>
        <input id="booking-date" type="date" value={date} onChange={(event) => changeDate(event.target.value)} />
      </div>

      <fieldset>
        <legend>Time</legend>
        {chosen.length === 0 && <p className="staff-hint">Choose services to see the free times.</p>}
        {chosen.length > 0 && !current && <p>Loading…</p>}
        {current?.failed && <p className="staff-alert">{"Sorry, we couldn't load the free times."}</p>}
        {current?.availability?.unavailable_reason === 'mixed_bay_types' && <p className="staff-alert">{MIXED}</p>}
        {current?.availability && current.availability.unavailable_reason === null && (
          <TimePickerGrid
            slots={current.availability.slots}
            bays={bays}
            zone={current.availability.timezone}
            selected={picked}
            onPick={(start, bayId) => {
              setPicked({ start, bayId })
              setFormError(null)
            }}
          />
        )}
      </fieldset>

      <fieldset>
        <legend>Customer and car</legend>
        {fields.map((field) => (
          <div key={field.name} className="field">
            <label htmlFor={`phone-${field.name}`}>{field.label}</label>
            <input
              id={`phone-${field.name}`}
              type={field.type ?? 'text'}
              autoComplete={field.autoComplete}
              aria-invalid={errors[field.name] ? true : undefined}
              aria-describedby={errors[field.name] ? `phone-${field.name}-error` : undefined}
              value={values[field.name]}
              onChange={(event) => setField(field.name, event.target.value)}
            />
            {errors[field.name] && (
              <p id={`phone-${field.name}-error`} className="field-error">
                {errors[field.name]}
              </p>
            )}
          </div>
        ))}
        <div className="field">
          <label htmlFor="phone-notes">Notes (optional)</label>
          <textarea id="phone-notes" value={values.notes} onChange={(event) => setField('notes', event.target.value)} />
          {errors.notes && <p className="field-error">{errors.notes}</p>}
        </div>
      </fieldset>

      <p>{enquiry ? 'No deposit is taken. The customer is emailed the booking.' : 'No deposit is taken for phone bookings.'}</p>
      {formError && <p className="field-error">{formError}</p>}
      {message && (
        <p role="alert" className="staff-alert">
          {message}
        </p>
      )}
      <button type="submit" className="staff-button" disabled={busy}>
        Book it
      </button>
    </form>
  )
}
