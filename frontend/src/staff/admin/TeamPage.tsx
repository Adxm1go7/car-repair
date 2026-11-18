import { useCallback, useEffect, useState } from 'react'
import type { FormEvent, JSX } from 'react'
import { fetchTeam, inviteStaff, resetStaffPassword, updateStaff } from '../api.ts'
import type { StaffResult } from '../api.ts'
import { FAILED, ROLE_LABEL, STATE_LABEL } from '../labels.ts'
import { useStaff } from '../StaffContext.ts'
import type { StaffRole, TeamMember } from '../types.ts'

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

type Change = 'role' | 'remove' | 'restore' | 'reset'

/** What the confirm step says, its button, and what the page says once it's done. */
function wording(member: TeamMember, change: Change): { ask: string; yes: string; done: string } {
  const toAdmin = member.role === 'staff'
  switch (change) {
    case 'role':
      return toAdmin
        ? {
            ask: `Make ${member.name} an admin? They'll be able to manage the team and read the audit log.`,
            yes: 'Yes, make admin',
            done: `${member.name} is now an admin`,
          }
        : {
            ask: `Make ${member.name} staff? They'll lose access to Team and Audit.`,
            yes: 'Yes, make staff',
            done: `${member.name} is now staff`,
          }
    case 'remove':
      return {
        ask: `Remove ${member.name}? They'll be logged out at once and can't log in again unless restored.`,
        yes: 'Yes, remove',
        done: `${member.name} has been removed`,
      }
    case 'restore':
      return {
        ask: `Restore ${member.name}? They'll be emailed a link to set a new password.`,
        yes: 'Yes, restore',
        done: `${member.name} has been restored and emailed a link`,
      }
    case 'reset':
      return {
        ask: `Send ${member.name} a password reset? They'll be logged out until they set a new password.`,
        yes: 'Yes, send it',
        done: `Password reset sent to ${member.email}`,
      }
  }
}

function run(member: TeamMember, change: Change): Promise<StaffResult<TeamMember>> {
  switch (change) {
    case 'role':
      return updateStaff(member.id, { role: member.role === 'staff' ? 'admin' : 'staff' })
    case 'remove':
      return updateStaff(member.id, { active: false })
    case 'restore':
      return updateStaff(member.id, { active: true })
    case 'reset':
      return resetStaffPassword(member.id)
  }
}

/** The 409's detail ("The garage needs at least one admin"), or the general message. */
function failure(result: StaffResult<unknown>): string | null {
  if (result.ok || result.kind === 'unauthorised') return null
  if (result.kind === 'conflict') {
    const detail = (result.body as { detail?: unknown } | null)?.detail
    if (typeof detail === 'string') return detail
  }
  if (result.kind === 'error' && result.detail) return result.detail
  return FAILED
}

type MemberProps = {
  member: TeamMember
  isMe: boolean
  onChanged: (member: TeamMember, done: string) => void
}

function Member({ member, isMe, onChanged }: MemberProps): JSX.Element {
  const [asking, setAsking] = useState<Change | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const headingId = `member-${member.id}`
  const removed = member.state === 'removed'

  function ask(change: Change): void {
    setError(null)
    setAsking(change)
  }

  async function confirm(change: Change): Promise<void> {
    const words = wording(member, change)
    setBusy(true)
    const result = await run(member, change)
    setBusy(false)
    setAsking(null)
    if (result.ok) onChanged(result.data, words.done)
    else setError(failure(result))
  }

  const words = asking ? wording(member, asking) : null
  return (
    <li className="team-member" aria-labelledby={headingId}>
      <div className="team-who">
        <h3 id={headingId}>{member.name}</h3>
        {isMe && <span className="staff-hint">(you)</span>}
      </div>
      <p className="team-email">{member.email}</p>
      <p className="team-state">{`${ROLE_LABEL[member.role]} · ${STATE_LABEL[member.state]}`}</p>
      {error && (
        <p role="alert" className="staff-alert">
          {error}
        </p>
      )}
      {asking && words ? (
        <div className="staff-panel">
          <p>{words.ask}</p>
          <div className="staff-buttons">
            <button
              type="button"
              className={`staff-button${asking === 'remove' ? ' staff-button-danger' : ''}`}
              disabled={busy}
              onClick={() => void confirm(asking)}
            >
              {words.yes}
            </button>
            <button type="button" className="staff-button staff-button-quiet" onClick={() => setAsking(null)}>
              Back
            </button>
          </div>
        </div>
      ) : (
        <div className="staff-buttons">
          {removed ? (
            <button type="button" className="staff-button staff-button-quiet" onClick={() => ask('restore')}>
              Restore
            </button>
          ) : (
            <>
              <button type="button" className="staff-button staff-button-quiet" onClick={() => ask('role')}>
                {member.role === 'staff' ? 'Make admin' : 'Make staff'}
              </button>
              <button type="button" className="staff-button staff-button-quiet" onClick={() => ask('reset')}>
                Send password reset
              </button>
              <button type="button" className="staff-button staff-button-quiet" onClick={() => ask('remove')}>
                Remove
              </button>
            </>
          )}
        </div>
      )}
    </li>
  )
}

type InviteErrors = { name?: string; email?: string }

function InviteForm({ onInvited }: { onInvited: (member: TeamMember) => void }): JSX.Element {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<StaffRole>('staff')
  const [errors, setErrors] = useState<InviteErrors>({})
  const [alert, setAlert] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    const found: InviteErrors = {}
    if (!name.trim()) found.name = 'Please enter their name'
    if (!EMAIL.test(email.trim())) found.email = 'Please enter a valid email'
    setErrors(found)
    setAlert(null)
    if (found.name || found.email) return

    setBusy(true)
    const result = await inviteStaff({ name: name.trim(), email: email.trim(), role })
    setBusy(false)
    if (result.ok) {
      setName('')
      setEmail('')
      setRole('staff')
      onInvited(result.data)
    } else {
      setAlert(failure(result))
    }
  }

  return (
    <form className="staff-form team-invite" onSubmit={(event) => void submit(event)} noValidate>
      <h2>Invite someone</h2>
      {alert && (
        <p role="alert" className="staff-alert">
          {alert}
        </p>
      )}
      <div className="field">
        <label htmlFor="invite-name">Name</label>
        <input
          id="invite-name"
          maxLength={100}
          value={name}
          aria-invalid={errors.name ? true : undefined}
          aria-describedby={errors.name ? 'invite-name-error' : undefined}
          onChange={(event) => setName(event.target.value)}
        />
        {errors.name && (
          <span id="invite-name-error" className="field-error">
            {errors.name}
          </span>
        )}
      </div>
      <div className="field">
        <label htmlFor="invite-email">Email</label>
        <input
          id="invite-email"
          type="email"
          maxLength={254}
          value={email}
          aria-invalid={errors.email ? true : undefined}
          aria-describedby={errors.email ? 'invite-email-error' : undefined}
          onChange={(event) => setEmail(event.target.value)}
        />
        {errors.email && (
          <span id="invite-email-error" className="field-error">
            {errors.email}
          </span>
        )}
      </div>
      <div className="field">
        <label htmlFor="invite-role">Role</label>
        <select id="invite-role" value={role} onChange={(event) => setRole(event.target.value as StaffRole)}>
          <option value="staff">Staff</option>
          <option value="admin">Admin</option>
        </select>
      </div>
      <p className="staff-hint">They'll be emailed a link to set their password.</p>
      <button type="submit" className="staff-button" disabled={busy}>
        Send invite
      </button>
    </form>
  )
}

type TeamState = { kind: 'loading' } | { kind: 'failed' } | { kind: 'loaded'; members: TeamMember[] }

/** `/staff/team` (admin only): everyone's account, and inviting someone new. */
export function TeamPage(): JSX.Element {
  const { me, refresh } = useStaff()
  const [state, setState] = useState<TeamState>({ kind: 'loading' })
  const [notice, setNotice] = useState<string | null>(null)

  const show = useCallback((result: StaffResult<TeamMember[]>): void => {
    if (result.ok) setState({ kind: 'loaded', members: result.data })
    else if (result.kind !== 'unauthorised') setState({ kind: 'failed' })
  }, [])

  useEffect(() => {
    let cancelled = false
    void fetchTeam().then((result) => {
      if (!cancelled) show(result)
    })
    return () => {
      cancelled = true
    }
  }, [show])

  async function retry(): Promise<void> {
    setState({ kind: 'loading' })
    show(await fetchTeam())
  }

  function put(member: TeamMember): void {
    setState((current) => {
      if (current.kind !== 'loaded') return current
      const known = current.members.some((m) => m.id === member.id)
      const members = known
        ? current.members.map((m) => (m.id === member.id ? member : m))
        : [...current.members, member]
      return { kind: 'loaded', members }
    })
  }

  function changed(member: TeamMember, done: string): void {
    put(member)
    setNotice(done)
    // A change to your own account (role, removed) changes what you can see, or logs you out.
    if (member.id === me.id) void refresh()
  }

  function invited(member: TeamMember): void {
    put(member)
    setNotice(`Invite sent to ${member.email}`)
  }

  return (
    <div className="team-page">
      <h1>Team</h1>
      <p role="status" className="team-notice">
        {notice}
      </p>
      {state.kind === 'loading' && <p>Loading…</p>}
      {state.kind === 'failed' && (
        <>
          <p role="alert" className="staff-alert">
            {"Sorry, we couldn't load the team."}
          </p>
          <button type="button" className="staff-button" onClick={() => void retry()}>
            Try again
          </button>
        </>
      )}
      {state.kind === 'loaded' && (
        <>
          <ul className="team-list" aria-label="Team">
            {state.members.map((member) => (
              <Member key={member.id} member={member} isMe={member.id === me.id} onChanged={changed} />
            ))}
          </ul>
          <InviteForm onInvited={invited} />
        </>
      )}
    </div>
  )
}
