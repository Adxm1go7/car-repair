// Shapes returned by the public catalogue API (backend/app/api/catalogue.py).

export type ApprovalMode = 'instant' | 'needs_approval'

export type Service = {
  slug: string
  name: string
  category: string
  description: string
  duration_minutes: number
  price_from_pence: number
  price_to_pence: number | null
  approval_mode: ApprovalMode
}

export type OpeningBreak = {
  start: string
  end: string
}

/** weekday: 0 = Monday … 6 = Sunday. open/close are "HH:MM" garage-local, or null when closed. */
export type OpeningDay = {
  weekday: number
  open: string | null
  close: string | null
  breaks: OpeningBreak[]
}

/** A week of hours in force from `starts_on` ("YYYY-MM-DD", garage-local) until the next one. */
export type Timetable = {
  starts_on: string
  days: OpeningDay[]
}

export type Garage = {
  name: string
  address: string
  phone: string
  email: string
  timezone: string
  /** The public live demo: banner, demo logins, the Demo inbox. */
  demo_site: boolean
}

export type Catalogue = {
  services: Service[]
  /** The timetable in force today first, then any starting within the booking window. */
  timetables: Timetable[]
  garage: Garage
}

export type CatalogueResult = { ok: true; data: Catalogue } | { ok: false; phone: string | null }
