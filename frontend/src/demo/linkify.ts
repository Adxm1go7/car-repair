export type TextPart = string | { href: string; label: string }

const URL_PATTERN = /https?:\/\/[^\s<>"]+/g

/** Split `text` into plain text and links, linking only URLs on this site (`origin`), so an
 * email in the Demo inbox can't send a visitor anywhere else. */
export function linkify(text: string, origin: string): TextPart[] {
  const parts: TextPart[] = []
  let last = 0
  for (const match of text.matchAll(URL_PATTERN)) {
    const url = match[0]
    if (!isOnSite(url, origin)) continue
    if (match.index > last) parts.push(text.slice(last, match.index))
    parts.push({ href: url, label: url })
    last = match.index + url.length
  }
  if (last < text.length || parts.length === 0) parts.push(text.slice(last))
  return mergeText(parts)
}

function isOnSite(url: string, origin: string): boolean {
  try {
    return new URL(url).origin === origin
  } catch {
    return false
  }
}

/** Neighbouring strings joined, so text with no site links comes back as one string. */
function mergeText(parts: TextPart[]): TextPart[] {
  const merged: TextPart[] = []
  for (const part of parts) {
    const previous = merged[merged.length - 1]
    if (typeof part === 'string' && typeof previous === 'string') merged[merged.length - 1] = previous + part
    else merged.push(part)
  }
  return merged
}
