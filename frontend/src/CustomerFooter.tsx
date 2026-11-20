import type { JSX } from 'react'
import { Link } from 'react-router'

/** Shown once under every customer page, outside the page's own <main>. */
export function CustomerFooter(): JSX.Element {
  return (
    <footer className="site-footer">
      <Link to="/privacy">Privacy</Link>
    </footer>
  )
}
