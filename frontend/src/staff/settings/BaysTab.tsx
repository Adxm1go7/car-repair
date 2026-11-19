import { useCallback, useEffect, useState } from 'react'
import type { FormEvent, JSX } from 'react'
import {
  addBay,
  addBayType,
  clashesOf,
  fetchAdminBays,
  fetchAdminServices,
  fetchBayTypes,
  updateBay,
} from '../api.ts'
import type { AdminBay, AdminService, BayType, Clash } from '../types.ts'
import { ClashList } from './ClashList.tsx'
import { failure } from './shared.ts'

type Data = { bays: AdminBay[]; types: BayType[]; services: AdminService[] }
type Loaded = { kind: 'loading' } | { kind: 'failed' } | { kind: 'loaded'; data: Data }
type Adding = 'bay' | 'type' | null

/** A form with one name field (and, for a bay, a type): adding a bay or type, or renaming. */
function NameForm({
  title,
  submitLabel,
  initialName = '',
  types,
  onSubmit,
  onCancel,
}: {
  title: string
  submitLabel: string
  initialName?: string
  types?: BayType[]
  onSubmit: (name: string, typeId: number | null) => Promise<string | null>
  onCancel: () => void
}): JSX.Element {
  const id = title.toLowerCase().replace(/[^a-z0-9]+/g, '-')
  const [name, setName] = useState(initialName)
  const [typeId, setTypeId] = useState('')
  const [errors, setErrors] = useState<{ name?: string; type?: string }>({})
  const [alert, setAlert] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    const found: { name?: string; type?: string } = {}
    if (!name.trim()) found.name = 'Please enter a name'
    if (types && !typeId) found.type = 'Please choose a bay type'
    setErrors(found)
    setAlert(null)
    if (found.name || found.type) return
    setBusy(true)
    const error = await onSubmit(name.trim(), types ? Number(typeId) : null)
    setBusy(false)
    setAlert(error)
  }

  return (
    <form className="staff-form settings-form" aria-label={title} onSubmit={(event) => void submit(event)} noValidate>
      <h3>{title}</h3>
      {alert && (
        <p role="alert" className="staff-alert">
          {alert}
        </p>
      )}
      <div className="field">
        <label htmlFor={`${id}-name`}>Name</label>
        <input
          id={`${id}-name`}
          maxLength={100}
          value={name}
          aria-invalid={errors.name ? true : undefined}
          aria-describedby={errors.name ? `${id}-name-error` : undefined}
          onChange={(event) => setName(event.target.value)}
        />
        {errors.name && (
          <span id={`${id}-name-error`} className="field-error">
            {errors.name}
          </span>
        )}
      </div>
      {types && (
        <div className="field">
          <label htmlFor={`${id}-type`}>Bay type</label>
          <select
            id={`${id}-type`}
            value={typeId}
            aria-invalid={errors.type ? true : undefined}
            aria-describedby={errors.type ? `${id}-type-error` : undefined}
            onChange={(event) => setTypeId(event.target.value)}
          >
            <option value="">Choose…</option>
            {types.map((type) => (
              <option key={type.id} value={type.id}>
                {type.name}
              </option>
            ))}
          </select>
          {errors.type && (
            <span id={`${id}-type-error`} className="field-error">
              {errors.type}
            </span>
          )}
        </div>
      )}
      <div className="staff-buttons">
        <button type="submit" className="staff-button" disabled={busy}>
          {submitLabel}
        </button>
        <button type="button" className="staff-button staff-button-quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

type RowProps = {
  bay: AdminBay
  data: Data
  onChanged: (bay: AdminBay, done: string) => void
}

function BayRow({ bay, data, onChanged }: RowProps): JSX.Element {
  const [renaming, setRenaming] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [clashes, setClashes] = useState<Clash[] | null>(null)

  // Taking the last bay of its type out of use stops its services being booked.
  const lastOfType = !data.bays.some((b) => b.id !== bay.id && b.active && b.bay_type_id === bay.bay_type_id)
  const stranded = data.services.filter((s) => s.active && s.bay_type_id === bay.bay_type_id).map((s) => s.name)

  async function rename(name: string): Promise<string | null> {
    const result = await updateBay(bay.id, { name })
    if (!result.ok) return failure(result)
    setRenaming(false)
    onChanged(result.data, `Renamed ${bay.name} to ${result.data.name}`)
    return null
  }

  async function setActive(active: boolean): Promise<void> {
    setBusy(true)
    setError(null)
    setClashes(null)
    const result = await updateBay(bay.id, { active })
    setBusy(false)
    setConfirming(false)
    if (result.ok) {
      onChanged(result.data, active ? `Put ${bay.name} back in use` : `Took ${bay.name} out of use`)
      return
    }
    const found = result.kind === 'conflict' ? clashesOf(result.body) : null
    if (found) setClashes(found)
    else setError(failure(result))
  }

  function ask(): void {
    setError(null)
    setClashes(null)
    setConfirming(true)
  }

  return (
    <li className="settings-row" aria-label={bay.name}>
      <span className="settings-name">{bay.name}</span>
      <span>{bay.bay_type}</span>
      <span className={bay.active ? 'settings-on' : 'settings-off'}>{bay.active ? 'In use' : 'Out of use'}</span>
      <div className="staff-buttons">
        <button type="button" className="staff-button staff-button-quiet" onClick={() => setRenaming(true)}>
          Rename
        </button>
        {bay.active ? (
          <button type="button" className="staff-button staff-button-quiet" onClick={ask}>
            Take out of use
          </button>
        ) : (
          <button
            type="button"
            className="staff-button staff-button-quiet"
            disabled={busy}
            onClick={() => void setActive(true)}
          >
            Put back in use
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="staff-alert settings-wide">
          {error}
        </p>
      )}
      {clashes && (
        <div className="settings-wide">
          <ClashList bookings={clashes} />
        </div>
      )}
      {confirming && (
        <div className="staff-panel settings-wide">
          <p>{`Take ${bay.name} out of use? It can't be booked until it's back in use. Its blocked time stays as it is.`}</p>
          {lastOfType && (
            <p className="settings-warning">
              {`${bay.name} is the last ${bay.bay_type} in use. `}
              {stranded.length > 0
                ? `${stranded.join(', ')} can't be booked until one is back.`
                : 'Services needing one can’t be booked until one is back.'}
            </p>
          )}
          <div className="staff-buttons">
            <button
              type="button"
              className="staff-button staff-button-danger"
              disabled={busy}
              onClick={() => void setActive(false)}
            >
              Yes, take out of use
            </button>
            <button type="button" className="staff-button staff-button-quiet" onClick={() => setConfirming(false)}>
              Back
            </button>
          </div>
        </div>
      )}
      {renaming && (
        <div className="settings-wide">
          <NameForm
            title={`Rename ${bay.name}`}
            submitLabel="Save"
            initialName={bay.name}
            onSubmit={rename}
            onCancel={() => setRenaming(false)}
          />
        </div>
      )}
    </li>
  )
}

async function loadAll(): Promise<Loaded | null> {
  const [bays, types, services] = await Promise.all([fetchAdminBays(), fetchBayTypes(), fetchAdminServices()])
  if (bays.ok && types.ok && services.ok) {
    return { kind: 'loaded', data: { bays: bays.data, types: types.data, services: services.data } }
  }
  const failed = [bays, types, services].find((result) => !result.ok)
  return failed && !failed.ok && failed.kind === 'unauthorised' ? null : { kind: 'failed' }
}

/** The Bays tab: add and rename bays, take them out of use and back, and add bay types. */
export function BaysTab(): JSX.Element {
  const [state, setState] = useState<Loaded>({ kind: 'loading' })
  const [adding, setAdding] = useState<Adding>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const show = useCallback((next: Loaded | null): void => {
    if (next) setState(next)
  }, [])

  useEffect(() => {
    let cancelled = false
    void loadAll().then((next) => {
      if (!cancelled) show(next)
    })
    return () => {
      cancelled = true
    }
  }, [show])

  async function retry(): Promise<void> {
    setState({ kind: 'loading' })
    show(await loadAll())
  }

  function update(change: (data: Data) => Data): void {
    setState((current) => (current.kind === 'loaded' ? { kind: 'loaded', data: change(current.data) } : current))
  }

  function putBay(bay: AdminBay, done: string): void {
    update((data) => {
      const known = data.bays.some((b) => b.id === bay.id)
      return { ...data, bays: known ? data.bays.map((b) => (b.id === bay.id ? bay : b)) : [...data.bays, bay] }
    })
    setNotice(done)
  }

  async function newBay(name: string, typeId: number | null): Promise<string | null> {
    const result = await addBay({ name, bay_type_id: typeId ?? 0 })
    if (!result.ok) return failure(result)
    setAdding(null)
    putBay(result.data, `Added ${result.data.name}`)
    return null
  }

  async function newType(name: string): Promise<string | null> {
    const result = await addBayType(name)
    if (!result.ok) return failure(result)
    setAdding(null)
    update((data) => ({ ...data, types: [...data.types, result.data] }))
    setNotice(`Added bay type ${result.data.name}`)
    return null
  }

  return (
    <section className="settings-tab" aria-labelledby="bays-heading">
      <div className="settings-heading">
        <h2 id="bays-heading">Bays</h2>
        {state.kind === 'loaded' && !adding && (
          <div className="staff-buttons">
            <button type="button" className="staff-button" onClick={() => setAdding('bay')}>
              + Add a bay
            </button>
            <button type="button" className="staff-button staff-button-quiet" onClick={() => setAdding('type')}>
              + Add a bay type
            </button>
          </div>
        )}
      </div>
      <p role="status" className="team-notice">
        {notice}
      </p>
      {state.kind === 'loading' && <p>Loading…</p>}
      {state.kind === 'failed' && (
        <>
          <p role="alert" className="staff-alert">
            {"Sorry, we couldn't load the bays."}
          </p>
          <button type="button" className="staff-button" onClick={() => void retry()}>
            Try again
          </button>
        </>
      )}
      {state.kind === 'loaded' && (
        <>
          {adding === 'bay' && (
            <NameForm
              title="Add a bay"
              submitLabel="Add bay"
              types={state.data.types}
              onSubmit={newBay}
              onCancel={() => setAdding(null)}
            />
          )}
          {adding === 'type' && (
            <NameForm
              title="Add a bay type"
              submitLabel="Add bay type"
              onSubmit={(name) => newType(name)}
              onCancel={() => setAdding(null)}
            />
          )}
          <ul className="settings-list" aria-label="Bays">
            {state.data.bays.map((bay) => (
              <BayRow key={bay.id} bay={bay} data={state.data} onChanged={putBay} />
            ))}
          </ul>
          <p className="staff-hint">
            {`Bay types: ${state.data.types.map((type) => type.name).join(', ')}. A bay type can't be renamed.`}
          </p>
        </>
      )}
    </section>
  )
}
