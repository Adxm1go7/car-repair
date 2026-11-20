import type { JSX } from 'react'

/**
 * A field only bots fill in. It's off-screen rather than display: none (some bots skip
 * fields that aren't displayed), out of the tab order, hidden from screen readers, and
 * marked so password managers leave it alone. The server ignores a form that fills it.
 */
export function Honeypot({ value, onChange }: { value: string; onChange: (value: string) => void }): JSX.Element {
  return (
    <div className="visually-hidden" aria-hidden="true">
      <label htmlFor="field-website">Leave this empty</label>
      <input
        id="field-website"
        name="website"
        type="text"
        tabIndex={-1}
        autoComplete="off"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  )
}
