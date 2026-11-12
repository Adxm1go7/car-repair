import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import { Link, Route, Routes, useSearchParams } from 'react-router'
import './App.css'
import { BookedPage } from './booking/BookedPage.tsx'
import { BookPage } from './booking/BookPage.tsx'
import { parseSelection, selectionQuery, totalMinutes } from './booking/selection.ts'
import { fetchCatalogue } from './catalogue/api.ts'
import { formatDuration, formatPrice } from './catalogue/format.ts'
import { openTodayText } from './catalogue/openToday.ts'
import type { Catalogue, Service } from './catalogue/types.ts'

type PageState =
  | { kind: 'loading' }
  | { kind: 'error'; phone: string | null }
  | { kind: 'ready'; catalogue: Catalogue }

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function telHref(phone: string): string {
  return `tel:${phone.replace(/\s+/g, '')}`
}

/** Categories in the order their first service appears (services arrive in display order). */
function groupByCategory(services: Service[]): [string, Service[]][] {
  const groups = new Map<string, Service[]>()
  for (const service of services) {
    groups.set(service.category, [...(groups.get(service.category) ?? []), service])
  }
  return [...groups.entries()]
}

type CardProps = { service: Service; chosen: boolean; onToggle: (slug: string) => void }

function ServiceCard({ service, chosen, onToggle }: CardProps): JSX.Element {
  const headingId = `service-${service.slug}`
  const instant = service.approval_mode === 'instant'
  return (
    <li className={chosen ? 'card card-chosen' : 'card'}>
      <div className="card-title">
        {instant && (
          <input
            type="checkbox"
            className="pick"
            aria-labelledby={headingId}
            checked={chosen}
            onChange={() => onToggle(service.slug)}
          />
        )}
        <h3 id={headingId}>{service.name}</h3>
        {!instant && <span className="badge">Needs approval</span>}
      </div>
      <p className="card-description">{service.description}</p>
      <p className="card-meta">
        <span>{formatDuration(service.duration_minutes)}</span>
        <span className="price">{formatPrice(service.price_from_pence, service.price_to_pence)}</span>
      </p>
      {!instant && <p className="call-us">Needs approval — call us</p>}
    </li>
  )
}

function ChooseTimeBar({ services, chosen }: { services: Service[]; chosen: string[] }): JSX.Element {
  const count = chosen.length
  const label = `Choose a time · ${count} service${count === 1 ? '' : 's'} · ${formatDuration(totalMinutes(services, chosen))}`
  return (
    <div className="choose-bar">
      <Link className="button" to={`/book${selectionQuery(chosen)}`}>
        {label}
      </Link>
    </div>
  )
}

function CataloguePage({ catalogue, now }: { catalogue: Catalogue; now: Date }): JSX.Element {
  const { services, hours, garage } = catalogue
  const [searchParams, setSearchParams] = useSearchParams()
  // The choice starts from the URL and is copied back to it, so Back from the time picker
  // keeps it. It is held here too, so a tick shows at once rather than after the URL
  // updates. Only instant services can be chosen; anything else in the URL is ignored.
  const [chosen, setChosen] = useState(() => {
    const bookable = new Set(services.filter((s) => s.approval_mode === 'instant').map((s) => s.slug))
    return parseSelection(`?${searchParams.toString()}`).filter((slug) => bookable.has(slug))
  })

  function toggle(slug: string): void {
    const next = chosen.includes(slug) ? chosen.filter((s) => s !== slug) : [...chosen, slug]
    setChosen(next)
    setSearchParams(new URLSearchParams(next.map((s) => ['services', s])), { replace: true })
  }

  return (
    <>
      <header className="site-header">
        <h1>{garage.name}</h1>
        <p className="open-today">{openTodayText(hours, now, garage.timezone)}</p>
      </header>
      <main className="page">
        {groupByCategory(services).map(([category, items]) => (
          <section key={category}>
            <h2>{category}</h2>
            <ul className="cards">
              {items.map((service) => (
                <ServiceCard
                  key={service.slug}
                  service={service}
                  chosen={chosen.includes(service.slug)}
                  onToggle={toggle}
                />
              ))}
            </ul>
          </section>
        ))}

        <section>
          <h2>Opening hours</h2>
          <dl className="hours">
            {hours.map((day) => (
              <div key={day.weekday} className="hours-row">
                <dt>{DAY_NAMES[day.weekday]}</dt>
                <dd>
                  {day.open && day.close ? `${day.open}–${day.close}` : 'Closed'}
                  {day.breaks.map((b) => (
                    <span key={b.start} className="break">{`Closed ${b.start}–${b.end}`}</span>
                  ))}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        <section>
          <h2>Contact</h2>
          <address className="contact">
            <span>{garage.address}</span>
            <a href={telHref(garage.phone)}>{garage.phone}</a>
            <a href={`mailto:${garage.email}`}>{garage.email}</a>
          </address>
        </section>
      </main>
      {chosen.length > 0 && <ChooseTimeBar services={services} chosen={chosen} />}
    </>
  )
}

export function App({ now = () => new Date() }: { now?: () => Date }): JSX.Element {
  const [state, setState] = useState<PageState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    void fetchCatalogue().then((result) => {
      if (cancelled) return
      setState(result.ok ? { kind: 'ready', catalogue: result.data } : { kind: 'error', phone: result.phone })
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (state.kind === 'loading') {
    return (
      <main className="page">
        <p>Loading…</p>
      </main>
    )
  }

  if (state.kind === 'error') {
    return (
      <main className="page">
        <div role="alert" className="error">
          <p>{"Sorry, we couldn't load our services right now."}</p>
          {state.phone && (
            <p>
              Please call us on <a href={telHref(state.phone)}>{state.phone}</a>
            </p>
          )}
        </div>
      </main>
    )
  }

  return (
    <Routes>
      <Route path="/" element={<CataloguePage catalogue={state.catalogue} now={now()} />} />
      <Route path="/book" element={<BookPage catalogue={state.catalogue} now={now} />} />
      <Route path="/booked/:reference" element={<BookedPage garage={state.catalogue.garage} />} />
    </Routes>
  )
}
