import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import { Link, useParams } from 'react-router'
import { fetchEnquiry } from '../api.ts'
import { NewBookingPage } from '../forms/NewBookingPage.tsx'
import { ENQUIRY_HANDLED } from '../labels.ts'
import type { StaffEnquiry } from '../types.ts'

type State = { kind: 'loading' } | { kind: 'failed' } | { kind: 'ready'; enquiry: StaffEnquiry }

/** `/staff/enquiries/:id/book?date=`: the phone-booking form, filled in from the enquiry. */
export function BookEnquiryPage(): JSX.Element {
  const id = Number(useParams().id)
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    void fetchEnquiry(id).then((result) => {
      if (cancelled) return
      if (result.ok) setState({ kind: 'ready', enquiry: result.data })
      else if (result.kind !== 'unauthorised') setState({ kind: 'failed' })
    })
    return () => {
      cancelled = true
    }
  }, [id])

  if (state.kind === 'loading') return <p>Loading…</p>
  if (state.kind === 'failed') {
    return (
      <p role="alert" className="staff-alert">
        {"Sorry, we couldn't load this enquiry."}
      </p>
    )
  }
  if (state.enquiry.status !== 'new') {
    return (
      <section>
        <p>{ENQUIRY_HANDLED}</p>
        <p>
          <Link to={`/staff/enquiries/${id}`}>Back to the enquiry</Link>
        </p>
      </section>
    )
  }
  return <NewBookingPage enquiry={state.enquiry} />
}
