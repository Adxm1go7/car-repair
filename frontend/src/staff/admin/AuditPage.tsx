import { useEffect, useMemo, useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { Link, useSearchParams } from 'react-router'
import { calendarNoon } from '../../booking/days.ts'
import { shortDate } from '../../catalogue/hours.ts'
import { fetchAudit, fetchTeam } from '../api.ts'
import type { AuditFilters } from '../api.ts'
import { STATUS_LABEL, localDate, localTime } from '../labels.ts'
import type { AuditEntry, AuditPage as AuditPageData, BookingStatus, TeamMember } from '../types.ts'

const FILTER_KEYS = ['from', 'to', 'staff', 'reference'] as const

function filtersFrom(params: URLSearchParams): AuditFilters {
  const page = Number(params.get('page'))
  return {
    from: params.get('from') ?? '',
    to: params.get('to') ?? '',
    staff: params.get('staff') ?? '',
    reference: params.get('reference') ?? '',
    page: Number.isInteger(page) && page > 1 ? page : 1,
  }
}

function paramsFrom(filters: AuditFilters): URLSearchParams {
  const params = new URLSearchParams()
  for (const key of FILTER_KEYS) if (filters[key]) params.set(key, filters[key])
  if (filters.page > 1) params.set('page', String(filters.page))
  return params
}

/** "17 Nov 2026, 09:30", straight from the garage-local ISO time. */
function auditTime(iso: string): string {
  const day = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(calendarNoon(localDate(iso)))
  return `${day}, ${localTime(iso)}`
}

function text(snapshot: Record<string, unknown> | null, key: string): string | null {
  const value = snapshot?.[key]
  return typeof value === 'string' ? value : null
}

/** The action in words, e.g. "Status changed to In progress" or "Invited Jo Bloggs". */
function describe(entry: AuditEntry): string {
  const account = text(entry.after, 'name') ?? text(entry.before, 'name') ?? 'an account'
  switch (entry.action) {
    case 'booking.create':
      return 'Phone booking'
    case 'booking.move':
      return 'Moved booking'
    case 'booking.cancel':
      return 'Cancelled booking'
    case 'booking.approve':
      return 'Approved request'
    case 'booking.propose':
      return 'Proposed a new time'
    case 'booking.decline':
      return 'Declined request'
    case 'booking.status': {
      const status = text(entry.after, 'status')
      const label = status ? STATUS_LABEL[status as BookingStatus] : undefined
      return label ? `Status changed to ${label}` : 'Changed status'
    }
    case 'block.create': {
      const note = text(entry.after, 'note')
      return note ? `Blocked time: ${note}` : 'Blocked time'
    }
    case 'block.remove': {
      const note = text(entry.before, 'note')
      return note ? `Removed block: ${note}` : 'Removed block'
    }
    case 'staff.invite':
      return `Invited ${account}`
    case 'staff.role':
      return text(entry.after, 'role') === 'admin' ? `Made ${account} an admin` : `Made ${account} staff`
    case 'staff.remove':
      return `Removed ${account}`
    case 'staff.restore':
      return `Restored ${account}`
    case 'staff.reset_password':
      return `Sent ${account} a password reset`
    default:
      return describeSettings(entry)
  }
}

/** Settings changes: services, bays, bay types, opening hours and contact details. */
function describeSettings(entry: AuditEntry): string {
  const name = text(entry.after, 'name') ?? text(entry.before, 'name') ?? ''
  const oldName = text(entry.before, 'name')
  const startsOn = text(entry.after, 'starts_on') ?? text(entry.before, 'starts_on')
  const from = startsOn ? shortDate(startsOn) : ''
  switch (entry.action) {
    case 'service.create':
      return `Added service ${name}`
    case 'service.update':
      return oldName && oldName !== name ? `Renamed service ${oldName} to ${name}` : `Changed service ${name}`
    case 'service.hide':
      return `Hid service ${name}`
    case 'service.show':
      return `Showed service ${name}`
    case 'service.move': {
      const before = entry.before?.position
      const after = entry.after?.position
      const up = typeof before === 'number' && typeof after === 'number' && after < before
      return `Moved service ${name} ${up ? 'up' : 'down'}`
    }
    case 'bay.create':
      return `Added bay ${name}`
    case 'bay.rename':
      return `Renamed bay ${oldName ?? ''} to ${name}`
    case 'bay.out_of_use':
      return `Took ${name} out of use`
    case 'bay.back_in_use':
      return `Put ${name} back in use`
    case 'bay_type.create':
      return `Added bay type ${name}`
    case 'hours.create':
      return `New hours from ${from}`
    case 'hours.update':
      return `Changed hours from ${from}`
    case 'hours.delete':
      return `Deleted hours from ${from}`
    case 'contact.update':
      return 'Changed contact details'
    default:
      return entry.action
  }
}

function FilterForm({ filters, team }: { filters: AuditFilters; team: TeamMember[] }): JSX.Element {
  const [, setParams] = useSearchParams()
  const [draft, setDraft] = useState(filters)

  function set(key: (typeof FILTER_KEYS)[number], value: string): void {
    setDraft((current) => ({ ...current, [key]: value }))
  }

  function submit(event: FormEvent): void {
    event.preventDefault()
    setParams(paramsFrom({ ...draft, reference: draft.reference.trim().toUpperCase(), page: 1 }))
  }

  return (
    <form className="audit-filters" onSubmit={submit}>
      <div className="field">
        <label htmlFor="audit-from">From</label>
        <input id="audit-from" type="date" value={draft.from} onChange={(event) => set('from', event.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="audit-to">To</label>
        <input id="audit-to" type="date" value={draft.to} onChange={(event) => set('to', event.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="audit-staff">Staff member</label>
        <select id="audit-staff" value={draft.staff} onChange={(event) => set('staff', event.target.value)}>
          <option value="">Everyone</option>
          {team.map((member) => (
            <option key={member.id} value={String(member.id)}>
              {member.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="audit-reference">Booking reference</label>
        <input
          id="audit-reference"
          maxLength={9}
          value={draft.reference}
          onChange={(event) => set('reference', event.target.value)}
        />
      </div>
      <button type="submit" className="staff-button">
        Show
      </button>
    </form>
  )
}

function Entry({ entry }: { entry: AuditEntry }): JSX.Element {
  return (
    <li className="audit-entry">
      <time dateTime={entry.at}>{auditTime(entry.at)}</time>
      <span className="audit-who">{entry.staff_name}</span>
      <span>{describe(entry)}</span>
      {entry.booking_reference && (
        <Link to={`/staff/bookings/${encodeURIComponent(entry.booking_reference)}`}>{entry.booking_reference}</Link>
      )}
      {entry.reason && <span className="audit-reason">{`“${entry.reason}”`}</span>}
    </li>
  )
}

/** The answer for one URL's filters; anything for another URL means it's still loading. */
type Loaded = { forKey: string; data: AuditPageData | 'failed' }

/** `/staff/audit` (admin only): every staff change, newest first, with filters and pages. */
export function AuditPage(): JSX.Element {
  const [params, setParams] = useSearchParams()
  const key = params.toString()
  const filters = useMemo(() => filtersFrom(new URLSearchParams(key)), [key])
  const [team, setTeam] = useState<TeamMember[]>([])
  const [loaded, setLoaded] = useState<Loaded | null>(null)

  useEffect(() => {
    let cancelled = false
    // Best effort: without it the staff filter just offers "Everyone".
    void fetchTeam().then((result) => {
      if (!cancelled && result.ok) setTeam(result.data)
    })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    void fetchAudit(filters).then((result) => {
      if (cancelled) return
      if (result.ok) setLoaded({ forKey: key, data: result.data })
      else if (result.kind !== 'unauthorised') setLoaded({ forKey: key, data: 'failed' })
    })
    return () => {
      cancelled = true
    }
  }, [filters, key])

  const data = loaded?.forKey === key ? loaded.data : null

  function goTo(page: number): void {
    setParams(paramsFrom({ ...filters, page }))
  }

  return (
    <div className="audit-page">
      <h1>Audit log</h1>
      {/* Keyed by the URL, so the fields start again from it after paging or the back button. */}
      <FilterForm key={key} filters={filters} team={team} />
      {data === null && <p>Loading…</p>}
      {data === 'failed' && (
        <p role="alert" className="staff-alert">
          {"Sorry, we couldn't load the audit log."}
        </p>
      )}
      {data !== null && data !== 'failed' && (
        <>
          {data.entries.length === 0 ? (
            <p>No changes match these filters.</p>
          ) : (
            <ol className="audit-list" aria-label="Changes">
              {data.entries.map((entry, i) => (
                <Entry key={`${entry.at}-${i}`} entry={entry} />
              ))}
            </ol>
          )}
          <nav className="audit-pages" aria-label="Pages">
            {data.page > 1 && (
              <button type="button" className="staff-button staff-button-quiet" onClick={() => goTo(data.page - 1)}>
                Newer
              </button>
            )}
            <span>{`Page ${data.page}`}</span>
            {data.has_more && (
              <button type="button" className="staff-button staff-button-quiet" onClick={() => goTo(data.page + 1)}>
                Older
              </button>
            )}
          </nav>
        </>
      )}
    </div>
  )
}
