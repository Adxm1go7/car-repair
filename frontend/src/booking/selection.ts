import type { Service } from '../catalogue/types.ts'

/** The chosen services from a URL search like "?services=a&services=b", without repeats or blanks. */
export function parseSelection(search: string): string[] {
  const slugs = new URLSearchParams(search).getAll('services').filter((slug) => slug !== '')
  return [...new Set(slugs)]
}

/** "?services=a&services=b", or "" when nothing is chosen. */
export function selectionQuery(slugs: string[]): string {
  if (slugs.length === 0) return ''
  return `?${new URLSearchParams(slugs.map((slug) => ['services', slug])).toString()}`
}

/** Total minutes of the chosen services. Slugs not in `services` count for nothing. */
export function totalMinutes(services: Service[], slugs: string[]): number {
  return services
    .filter((service) => slugs.includes(service.slug))
    .reduce((sum, service) => sum + service.duration_minutes, 0)
}
