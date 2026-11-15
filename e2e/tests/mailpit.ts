import type { APIRequestContext } from '@playwright/test'

// Mailpit catches every email the worker sends locally and in CI (http://localhost:8025).

export const MAILPIT_URL = process.env.MAILPIT_URL ?? 'http://localhost:8025'

type Summary = { ID: string; Subject: string }
type Search = { messages: Summary[] | null }
type Message = { Text: string; HTML: string }

/** Wait for an email to `to` whose subject matches, and return its bodies. */
export async function waitForEmail(
  request: APIRequestContext,
  to: string,
  subject: RegExp,
  timeoutMs = 30_000,
): Promise<{ text: string; html: string }> {
  const deadline = Date.now() + timeoutMs
  const query = new URLSearchParams({ query: `to:"${to}"` })
  while (Date.now() < deadline) {
    const response = await request.get(`${MAILPIT_URL}/api/v1/search?${query.toString()}`)
    if (response.ok()) {
      const { messages } = (await response.json()) as Search
      const found = (messages ?? []).find((m) => subject.test(m.Subject))
      if (found) {
        const message = (await (await request.get(`${MAILPIT_URL}/api/v1/message/${found.ID}`)).json()) as Message
        return { text: message.Text, html: message.HTML }
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error(`No email to ${to} with a subject like ${subject} within ${timeoutMs / 1000}s`)
}
