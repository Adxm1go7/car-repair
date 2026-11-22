import type { JSX } from 'react'
import { Link } from 'react-router'

/** Shown once under every customer page, outside the page's own <main>. On the live demo it
 * also links to the Demo inbox. */
export function CustomerFooter({ demoSite = false }: { demoSite?: boolean }): JSX.Element {
  return (
    <footer className="site-footer">
      <Link to="/privacy">Privacy</Link>
      {demoSite && <Link to="/demo-inbox">Demo inbox</Link>}
    </footer>
  )
}
