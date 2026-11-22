export type InboxSummary = { id: number; to: string; subject: string; sent_at: string }
export type InboxEmail = InboxSummary & { text: string; html: string }

export type Loaded<T> = { ok: true; data: T } | { ok: false }

async function load<T>(url: string): Promise<Loaded<T>> {
  try {
    const response = await fetch(url)
    if (!response.ok) return { ok: false }
    return { ok: true, data: (await response.json()) as T }
  } catch {
    return { ok: false }
  }
}

export function fetchInbox(): Promise<Loaded<InboxSummary[]>> {
  return load<InboxSummary[]>('/api/demo-inbox')
}

export function fetchInboxEmail(id: string): Promise<Loaded<InboxEmail>> {
  return load<InboxEmail>(`/api/demo-inbox/${encodeURIComponent(id)}`)
}
