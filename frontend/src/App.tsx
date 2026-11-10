import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import './App.css'
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

function ServiceCard({ service }: { service: Service }): JSX.Element {
  return (
    <li className="card">
      <div className="card-title">
        <h3>{service.name}</h3>
        {service.approval_mode === 'needs_approval' && <span className="badge">Needs approval</span>}
      </div>
      <p className="card-description">{service.description}</p>
      <p className="card-meta">
        <span>{formatDuration(service.duration_minutes)}</span>
        <span className="price">{formatPrice(service.price_from_pence, service.price_to_pence)}</span>
      </p>
    </li>
  )
}

function CataloguePage({ catalogue, now }: { catalogue: Catalogue; now: Date }): JSX.Element {
  const { services, hours, garage } = catalogue
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
                <ServiceCard key={service.slug} service={service} />
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

  return <CataloguePage catalogue={state.catalogue} now={now()} />
}
