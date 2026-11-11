import type { CatalogueResult, Garage, OpeningDay, Service } from './types.ts'

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`${url} returned ${response.status}`)
  return (await response.json()) as T
}

/**
 * Loads services, opening hours and garage details in parallel. Never throws:
 * any failure gives { ok: false }, with the phone number if the garage details loaded.
 */
export async function fetchCatalogue(): Promise<CatalogueResult> {
  const [services, hours, garage] = await Promise.allSettled([
    getJson<Service[]>('/api/services'),
    getJson<OpeningDay[]>('/api/opening-hours'),
    getJson<Garage>('/api/garage'),
  ])
  if (services.status === 'fulfilled' && hours.status === 'fulfilled' && garage.status === 'fulfilled') {
    return { ok: true, data: { services: services.value, hours: hours.value, garage: garage.value } }
  }
  return { ok: false, phone: garage.status === 'fulfilled' ? garage.value.phone : null }
}
