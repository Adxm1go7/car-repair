import { useEffect, type JSX } from 'react'
import { Link } from 'react-router'

/** Any customer address we don't have a page for. */
export function NotFoundPage(): JSX.Element {
  useEffect(() => {
    document.title = 'Page not found'
  }, [])

  return (
    <main className="page">
      <h1>Page not found</h1>
      <p>{"We couldn't find that page."}</p>
      <p className="not-found-links">
        <Link to="/">Home</Link>
        <Link to="/book">Book a service</Link>
      </p>
    </main>
  )
}
