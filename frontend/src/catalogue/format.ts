function pounds(pence: number): string {
  const digits = pence % 100 === 0 ? 0 : 2
  return new Intl.NumberFormat('en-GB', {
    style: 'currency',
    currency: 'GBP',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(pence / 100)
}

/** "£219", "£54.85", or a range "£450–£750". Whole pounds drop the pence. */
export function formatPrice(fromPence: number, toPence: number | null): string {
  if (toPence === null || toPence === fromPence) return pounds(fromPence)
  return `${pounds(fromPence)}–${pounds(toPence)}`
}

/** "45m", "1h", "1h 30m". */
export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours === 0) return `${rest}m`
  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`
}
