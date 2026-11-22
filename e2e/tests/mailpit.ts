import type { APIRequestContext } from '@playwright/test'

// Where the tests read the emails the worker sends:
// - Mailpit locally and in CI (http://localhost:8025), which catches every email;
// - with INBOX=demo, the live demo's Demo inbox (/api/demo-inbox on BASE_URL), since the
//   demo site never sends email.

export const MAILPIT_URL = process.env.MAILPIT_URL ?? 'http://localhost:8025'
const BASE_URL = process.env.BASE_URL ?? 'http://localhost:8080'
const USE_DEMO_INBOX = process.env.INBOX === 'demo'

type Email = { text: string; html: string }
type MailpitSummary = { ID: string; Subject: string }
type MailpitSearch = { messages: MailpitSummary[] | null }
type MailpitMessage = { Text: string; HTML: string }
type InboxSummary = { id: number; subject: string }
type InboxEmail = { text: string; html: string }

/** One look for the email: its bodies, or null if it hasn't arrived yet. */
async function findInMailpit(request: APIRequestContext, to: string, subject: RegExp): Promise<Email | null> {
  const query = new URLSearchParams({ query: `to:"${to}"` })
  const response = await request.get(`${MAILPIT_URL}/api/v1/search?${query.toString()}`)
  if (!response.ok()) return null
  const { messages } = (await response.json()) as MailpitSearch
  const found = (messages ?? []).find((m) => subject.test(m.Subject))
  if (!found) return null
  const message = (await (await request.get(`${MAILPIT_URL}/api/v1/message/${found.ID}`)).json()) as MailpitMessage
  return { text: message.Text, html: message.HTML }
}

async function findInDemoInbox(request: APIRequestContext, to: string, subject: RegExp): Promise<Email | null> {
  const query = new URLSearchParams({ to })
  const response = await request.get(`${BASE_URL}/api/demo-inbox?${query.toString()}`)
  if (!response.ok()) return null
  const found = ((await response.json()) as InboxSummary[]).find((m) => subject.test(m.subject))
  if (!found) return null
  const email = (await (await request.get(`${BASE_URL}/api/demo-inbox/${found.id}`)).json()) as InboxEmail
  return { text: email.text, html: email.html }
}

/** Wait for an email to `to` whose subject matches, and return its bodies. */
export async function waitForEmail(
  request: APIRequestContext,
  to: string,
  subject: RegExp,
  timeoutMs = 30_000,
): Promise<Email> {
  const deadline = Date.now() + timeoutMs
  const find = USE_DEMO_INBOX ? findInDemoInbox : findInMailpit
  while (Date.now() < deadline) {
    const email = await find(request, to, subject)
    if (email) return email
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  const where = USE_DEMO_INBOX ? 'the Demo inbox' : 'Mailpit'
  throw new Error(`No email to ${to} with a subject like ${subject} in ${where} within ${timeoutMs / 1000}s`)
}
