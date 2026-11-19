import { useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { formatDuration } from '../../catalogue/format.ts'
import type { AdminBay, AdminService, ApprovalMode, BayType, NewService } from '../types.ts'
import { parsePounds, penceToPounds } from './shared.ts'

const DURATIONS = Array.from({ length: 32 }, (_, index) => (index + 1) * 15) // 15m to 8h
const BAD_PRICE = 'Enter pounds and pence, like 54.85'

type Errors = Partial<Record<'name' | 'category' | 'description' | 'from' | 'to' | 'bayType', string>>

type Props = {
  /** Bay type and approval mode are chosen only when adding: they can't change afterwards. */
  mode: 'add' | 'edit'
  service?: AdminService
  categories: string[]
  /** For adding: the bay types to choose from, and the bays, to warn about a type none is in use. */
  bayTypes?: BayType[]
  bays?: AdminBay[]
  /** Sends the service. Resolves to an error to show, or null once it's saved. */
  onSubmit: (service: NewService) => Promise<string | null>
  onCancel: () => void
}

function FieldError({ id, text }: { id: string; text: string | undefined }): JSX.Element | null {
  return text ? (
    <span id={id} className="field-error">
      {text}
    </span>
  ) : null
}

/** Adding a service, or editing one. Prices are typed in pounds and sent in pence. */
export function ServiceForm({ mode, service, categories, bayTypes = [], bays = [], onSubmit, onCancel }: Props): JSX.Element {
  const prefix = `service-${service?.id ?? 'new'}`
  const [name, setName] = useState(service?.name ?? '')
  const [category, setCategory] = useState(service?.category ?? '')
  const [description, setDescription] = useState(service?.description ?? '')
  const [duration, setDuration] = useState(service?.duration_minutes ?? 60)
  const [from, setFrom] = useState(service ? penceToPounds(service.price_from_pence) : '')
  const [to, setTo] = useState(service?.price_to_pence != null ? penceToPounds(service.price_to_pence) : '')
  const [bayTypeId, setBayTypeId] = useState('')
  const [approval, setApproval] = useState<ApprovalMode>('instant')
  const [errors, setErrors] = useState<Errors>({})
  const [alert, setAlert] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const chosenType = bayTypes.find((type) => String(type.id) === bayTypeId)
  const noBayInUse = chosenType !== undefined && !bays.some((bay) => bay.active && bay.bay_type_id === chosenType.id)

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    const found: Errors = {}
    if (!name.trim()) found.name = 'Please enter a name'
    if (!category.trim()) found.category = 'Please enter a category'
    if (!description.trim()) found.description = 'Please enter a description'
    const fromPence = parsePounds(from)
    const toPence = to.trim() ? parsePounds(to) : null
    if (fromPence === null) found.from = BAD_PRICE
    if (to.trim() && toPence === null) found.to = BAD_PRICE
    else if (fromPence !== null && toPence !== null && toPence < fromPence) {
      found.to = "The top price can't be below the lowest"
    }
    if (mode === 'add' && !chosenType) found.bayType = 'Please choose a bay type'
    setErrors(found)
    setAlert(null)
    if (Object.keys(found).length > 0 || fromPence === null) return

    setBusy(true)
    const error = await onSubmit({
      name: name.trim(),
      category: category.trim(),
      description: description.trim(),
      duration_minutes: duration,
      price_from_pence: fromPence,
      price_to_pence: toPence,
      bay_type_id: chosenType?.id ?? service?.bay_type_id ?? 0,
      approval_mode: mode === 'add' ? approval : (service?.approval_mode ?? 'instant'),
    })
    setBusy(false)
    setAlert(error)
  }

  function input(
    field: keyof Errors,
    label: string,
    value: string,
    set: (value: string) => void,
    extra: { maxLength?: number; list?: string; inputMode?: 'decimal' } = {},
  ): JSX.Element {
    const id = `${prefix}-${field}`
    return (
      <div className="field">
        <label htmlFor={id}>{label}</label>
        <input
          id={id}
          value={value}
          aria-invalid={errors[field] ? true : undefined}
          aria-describedby={errors[field] ? `${id}-error` : undefined}
          onChange={(event) => set(event.target.value)}
          {...extra}
        />
        <FieldError id={`${id}-error`} text={errors[field]} />
      </div>
    )
  }

  const title = mode === 'add' ? 'Add a service' : `Edit ${service?.name ?? ''}`
  return (
    <form className="staff-form settings-form" aria-label={title} onSubmit={(event) => void submit(event)} noValidate>
      <h2>{title}</h2>
      {alert && (
        <p role="alert" className="staff-alert">
          {alert}
        </p>
      )}
      {input('name', 'Name', name, setName, { maxLength: 100 })}
      {input('category', 'Category', category, setCategory, { maxLength: 50, list: `${prefix}-categories` })}
      <datalist id={`${prefix}-categories`}>
        {categories.map((each) => (
          <option key={each} value={each} />
        ))}
      </datalist>
      <div className="field">
        <label htmlFor={`${prefix}-description`}>Description</label>
        <textarea
          id={`${prefix}-description`}
          maxLength={500}
          rows={3}
          value={description}
          aria-invalid={errors.description ? true : undefined}
          aria-describedby={errors.description ? `${prefix}-description-error` : undefined}
          onChange={(event) => setDescription(event.target.value)}
        />
        <FieldError id={`${prefix}-description-error`} text={errors.description} />
      </div>
      <div className="field">
        <label htmlFor={`${prefix}-duration`}>Duration</label>
        <select id={`${prefix}-duration`} value={duration} onChange={(event) => setDuration(Number(event.target.value))}>
          {DURATIONS.map((minutes) => (
            <option key={minutes} value={minutes}>
              {formatDuration(minutes)}
            </option>
          ))}
        </select>
      </div>
      <div className="field-pair">
        {input('from', 'Price from (£)', from, setFrom, { inputMode: 'decimal' })}
        {input('to', 'Price to (£, optional)', to, setTo, { inputMode: 'decimal' })}
      </div>
      {mode === 'add' ? (
        <>
          <div className="field">
            <label htmlFor={`${prefix}-bay-type`}>Bay type</label>
            <select
              id={`${prefix}-bay-type`}
              value={bayTypeId}
              aria-invalid={errors.bayType ? true : undefined}
              aria-describedby={errors.bayType ? `${prefix}-bay-type-error` : undefined}
              onChange={(event) => setBayTypeId(event.target.value)}
            >
              <option value="">Choose…</option>
              {bayTypes.map((type) => (
                <option key={type.id} value={type.id}>
                  {type.name}
                </option>
              ))}
            </select>
            <FieldError id={`${prefix}-bay-type-error`} text={errors.bayType} />
            {noBayInUse && (
              <p className="staff-hint settings-warning">
                {`No ${chosenType.name} is in use, so this service can't be booked until one is added.`}
              </p>
            )}
          </div>
          <fieldset className="field settings-choice">
            <legend>Booking</legend>
            <label>
              <input
                type="radio"
                name={`${prefix}-approval`}
                checked={approval === 'instant'}
                onChange={() => setApproval('instant')}
              />
              Instant
            </label>
            <label>
              <input
                type="radio"
                name={`${prefix}-approval`}
                checked={approval === 'needs_approval'}
                onChange={() => setApproval('needs_approval')}
              />
              Needs approval
            </label>
          </fieldset>
          <p className="staff-hint">The bay type and booking choice can't be changed after the service is added.</p>
        </>
      ) : (
        service && (
          <p className="staff-hint">
            {`${service.bay_type} · ${service.approval_mode === 'instant' ? 'Instant' : 'Needs approval'} (fixed once added)`}
          </p>
        )
      )}
      <div className="staff-buttons">
        <button type="submit" className="staff-button" disabled={busy}>
          {mode === 'add' ? 'Add service' : 'Save'}
        </button>
        <button type="button" className="staff-button staff-button-quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}
