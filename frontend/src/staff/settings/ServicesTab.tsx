import { useCallback, useEffect, useState } from 'react'
import type { JSX } from 'react'
import { formatDuration, formatPrice } from '../../catalogue/format.ts'
import {
  addService,
  fetchAdminBays,
  fetchAdminServices,
  fetchBayTypes,
  moveService,
  updateService,
} from '../api.ts'
import type { StaffResult } from '../api.ts'
import type { AdminBay, AdminService, BayType, NewService } from '../types.ts'
import { ServiceForm } from './ServiceForm.tsx'
import { failure } from './shared.ts'

type Loaded = { kind: 'loading' } | { kind: 'failed' } | { kind: 'loaded'; services: AdminService[] }

/** What the add form needs: the bay types, and the bays, to warn when a type has none in use. */
type AddChoices = { bayTypes: BayType[]; bays: AdminBay[] }

type RowProps = {
  service: AdminService
  first: boolean
  last: boolean
  categories: string[]
  onChanged: (service: AdminService, done: string) => void
  onMove: (service: AdminService, direction: 'up' | 'down') => void
}

function ServiceRow({ service, first, last, categories, onChanged, onMove }: RowProps): JSX.Element {
  const [editing, setEditing] = useState(false)
  const [confirmingHide, setConfirmingHide] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function setActive(active: boolean): Promise<void> {
    setBusy(true)
    setError(null)
    const result = await updateService(service.id, { active })
    setBusy(false)
    setConfirmingHide(false)
    if (result.ok) onChanged(result.data, active ? `${service.name} is shown again` : `Hid ${service.name}`)
    else setError(failure(result))
  }

  async function save(changed: NewService): Promise<string | null> {
    const result = await updateService(service.id, {
      name: changed.name,
      category: changed.category,
      description: changed.description,
      duration_minutes: changed.duration_minutes,
      price_from_pence: changed.price_from_pence,
      price_to_pence: changed.price_to_pence,
    })
    if (!result.ok) return failure(result)
    setEditing(false)
    onChanged(result.data, `Saved ${result.data.name}`)
    return null
  }

  return (
    <li className="settings-row" aria-label={service.name}>
      <div className="settings-order">
        <button
          type="button"
          className="staff-button staff-button-quiet"
          aria-label={`Move ${service.name} up`}
          disabled={first}
          onClick={() => onMove(service, 'up')}
        >
          ▲
        </button>
        <button
          type="button"
          className="staff-button staff-button-quiet"
          aria-label={`Move ${service.name} down`}
          disabled={last}
          onClick={() => onMove(service, 'down')}
        >
          ▼
        </button>
      </div>
      <span className="settings-name">{service.name}</span>
      <span>{service.category}</span>
      <span>{formatDuration(service.duration_minutes)}</span>
      <span>{formatPrice(service.price_from_pence, service.price_to_pence)}</span>
      <span className={service.active ? 'settings-on' : 'settings-off'}>{service.active ? 'Shown' : 'Hidden'}</span>
      <div className="staff-buttons">
        <button type="button" className="staff-button staff-button-quiet" onClick={() => setEditing(true)}>
          Edit
        </button>
        {service.active ? (
          <button type="button" className="staff-button staff-button-quiet" onClick={() => setConfirmingHide(true)}>
            Hide
          </button>
        ) : (
          <button
            type="button"
            className="staff-button staff-button-quiet"
            disabled={busy}
            onClick={() => void setActive(true)}
          >
            Show
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="staff-alert settings-wide">
          {error}
        </p>
      )}
      {confirmingHide && (
        <div className="staff-panel settings-wide">
          <p>{`Hide ${service.name}? New customers won't be able to book it. Bookings already made carry on.`}</p>
          <div className="staff-buttons">
            <button type="button" className="staff-button" disabled={busy} onClick={() => void setActive(false)}>
              Yes, hide
            </button>
            <button type="button" className="staff-button staff-button-quiet" onClick={() => setConfirmingHide(false)}>
              Back
            </button>
          </div>
        </div>
      )}
      {editing && (
        <div className="settings-wide">
          <ServiceForm
            mode="edit"
            service={service}
            categories={categories}
            onSubmit={save}
            onCancel={() => setEditing(false)}
          />
        </div>
      )}
    </li>
  )
}

/** The Services tab: every service in display order, to add, edit, hide or show, and reorder. */
export function ServicesTab(): JSX.Element {
  const [state, setState] = useState<Loaded>({ kind: 'loading' })
  const [adding, setAdding] = useState<AddChoices | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const show = useCallback((result: StaffResult<AdminService[]>): void => {
    if (result.ok) setState({ kind: 'loaded', services: result.data })
    else if (result.kind !== 'unauthorised') setState({ kind: 'failed' })
  }, [])

  useEffect(() => {
    let cancelled = false
    void fetchAdminServices().then((result) => {
      if (!cancelled) show(result)
    })
    return () => {
      cancelled = true
    }
  }, [show])

  async function retry(): Promise<void> {
    setState({ kind: 'loading' })
    show(await fetchAdminServices())
  }

  function put(service: AdminService): void {
    setState((current) => {
      if (current.kind !== 'loaded') return current
      const known = current.services.some((s) => s.id === service.id)
      const services = known
        ? current.services.map((s) => (s.id === service.id ? service : s))
        : [...current.services, service]
      return { kind: 'loaded', services }
    })
  }

  function changed(service: AdminService, done: string): void {
    put(service)
    setNotice(done)
  }

  async function openAdd(): Promise<void> {
    setError(null)
    const [types, bays] = await Promise.all([fetchBayTypes(), fetchAdminBays()])
    if (types.ok && bays.ok) setAdding({ bayTypes: types.data, bays: bays.data })
    else setError(failure(types.ok ? bays : types))
  }

  async function add(service: NewService): Promise<string | null> {
    const result = await addService(service)
    if (!result.ok) return failure(result)
    setAdding(null)
    changed(result.data, `Added ${result.data.name}`)
    return null
  }

  async function move(service: AdminService, direction: 'up' | 'down'): Promise<void> {
    setError(null)
    const result = await moveService(service.id, direction)
    if (result.ok) setState({ kind: 'loaded', services: result.data })
    else setError(failure(result))
  }

  const services = state.kind === 'loaded' ? state.services : []
  const categories = [...new Set(services.map((s) => s.category))].sort()
  return (
    <section className="settings-tab" aria-labelledby="services-heading">
      <div className="settings-heading">
        <h2 id="services-heading">Services</h2>
        {state.kind === 'loaded' && !adding && (
          <button type="button" className="staff-button" onClick={() => void openAdd()}>
            + Add a service
          </button>
        )}
      </div>
      <p role="status" className="team-notice">
        {notice}
      </p>
      {error && (
        <p role="alert" className="staff-alert">
          {error}
        </p>
      )}
      {state.kind === 'loading' && <p>Loading…</p>}
      {state.kind === 'failed' && (
        <>
          <p role="alert" className="staff-alert">
            {"Sorry, we couldn't load the services."}
          </p>
          <button type="button" className="staff-button" onClick={() => void retry()}>
            Try again
          </button>
        </>
      )}
      {adding && (
        <ServiceForm
          mode="add"
          categories={categories}
          bayTypes={adding.bayTypes}
          bays={adding.bays}
          onSubmit={add}
          onCancel={() => setAdding(null)}
        />
      )}
      {state.kind === 'loaded' && (
        <ul className="settings-list" aria-label="Services">
          {services.map((service, index) => (
            <ServiceRow
              key={service.id}
              service={service}
              first={index === 0}
              last={index === services.length - 1}
              categories={categories}
              onChanged={changed}
              onMove={(s, direction) => void move(s, direction)}
            />
          ))}
        </ul>
      )}
    </section>
  )
}
