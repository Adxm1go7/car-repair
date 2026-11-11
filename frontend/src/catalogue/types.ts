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

export type Garage = {
  name: string
  address: string
  phone: string
  email: string
  timezone: string
}

export type Catalogue = {
  services: Service[]
  hours: OpeningDay[]
  garage: Garage
}

export type CatalogueResult = { ok: true; data: Catalogue } | { ok: false; phone: string | null }
