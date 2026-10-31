import { useEffect, useState } from 'react'
import type { JSX } from 'react'

type ApiStatus = 'checking' | 'ok' | 'unavailable'

const STATUS_TEXT: Record<ApiStatus, string> = {
  checking: 'API: checking…',
  ok: 'API: ok',
  unavailable: 'API: unavailable',
}

async function checkHealth(): Promise<ApiStatus> {
  try {
    const response = await fetch('/api/health')
    if (!response.ok) return 'unavailable'
    const body: unknown = await response.json()
    const isOk =
      typeof body === 'object' && body !== null && 'status' in body && body.status === 'ok'
    return isOk ? 'ok' : 'unavailable'
  } catch {
    return 'unavailable'
  }
}

export function App(): JSX.Element {
  const [status, setStatus] = useState<ApiStatus>('checking')

  useEffect(() => {
    let cancelled = false
    void checkHealth().then((result) => {
      if (!cancelled) setStatus(result)
    })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <main>
      <h1>Garage Booking</h1>
      <p>{STATUS_TEXT[status]}</p>
    </main>
  )
}
