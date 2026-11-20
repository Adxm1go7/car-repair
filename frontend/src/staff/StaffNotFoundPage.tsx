import { useEffect, type JSX } from 'react'
import { Link } from 'react-router'

/** Any staff address we don't have a page for, shown inside the staff layout. */
export function StaffNotFoundPage(): JSX.Element {
  useEffect(() => {
    document.title = 'Page not found'
  }, [])

  return (
    <>
      <h1>Page not found</h1>
      <p>
        <Link to="/staff">{"Back to today's schedule"}</Link>
      </p>
    </>
  )
}
