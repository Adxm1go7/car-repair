import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'

// Steps shared by the staff back office flows. The seed adds these sample logins
// everywhere except production (backend/app/demo_data.py).

const LOGINS = {
  admin: { email: 'admin@example.test', password: 'demo-admin-pass' },
  staff: { email: 'staff@example.test', password: 'demo-staff-pass' },
} as const

/** The day view's heading, e.g. "Tue 17 Nov". */
export const DAY_HEADING = /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2}$/

/** Log in from a clean start (any earlier session is dropped) and wait for the day view. */
export async function loginAs(page: Page, who: 'admin' | 'staff'): Promise<void> {
  const { email, password } = LOGINS[who]
  await page.context().clearCookies()
  await page.goto('/staff/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: DAY_HEADING })).toBeVisible()
}

/** A booking's reference from its staff page URL, /staff/bookings/ABCD-EFGH. */
export function referenceFromUrl(page: Page): string {
  const match = /\/staff\/bookings\/([A-Z2-9]{4}-[A-Z2-9]{4})$/.exec(new URL(page.url()).pathname)
  expect(match, `not a booking page: ${page.url()}`).toBeTruthy()
  return match?.[1] ?? ''
}

type StaffSlot = { start: string; bay_ids: number[] }
type ScheduleItem = { kind: 'booking' | 'block'; bay_id: number; start: string; end: string }
type Schedule = {
  bays: { id: number; name: string }[]
  days: { date: string; open: string | null; close: string | null }[]
  items: ScheduleItem[]
}

/** Free staff-side start times for these services on `day`. Needs a logged-in page. */
export async function staffSlots(page: Page, services: string[], day: string): Promise<StaffSlot[]> {
  const params = new URLSearchParams(services.map((s) => ['services', s]))
  params.set('date', day)
  const response = await page.request.get(`/api/staff/availability?${params.toString()}`)
  expect(response.ok()).toBe(true)
  return ((await response.json()) as { slots: StaffSlot[] }).slots
}

/** One day's bays, opening hours and bookings/blocks. Needs a logged-in page. */
export async function daySchedule(page: Page, day: string): Promise<Schedule> {
  const response = await page.request.get(`/api/staff/schedule?from=${day}&days=1`)
  expect(response.ok()).toBe(true)
  return (await response.json()) as Schedule
}

function minutes(hhmm: string): number {
  return Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5))
}

function hhmm(total: number): string {
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

/** The first whole hour ("HH:MM") inside opening hours with nothing booked or blocked on `bayId`. */
export function freeHour(schedule: Schedule, day: string, bayId: number): string | null {
  const opening = schedule.days.find((d) => d.date === day)
  if (!opening?.open || !opening.close) return null
  // Items' times are garage-local ISO on this day, e.g. "2026-11-17T09:30:00+00:00".
  const taken = schedule.items
    .filter((item) => item.bay_id === bayId)
    .map((item) => ({
      from: item.start.slice(0, 10) < day ? 0 : minutes(item.start.slice(11, 16)),
      to: item.end.slice(0, 10) > day ? 24 * 60 : minutes(item.end.slice(11, 16)),
    }))
  for (let from = Math.ceil(minutes(opening.open) / 60) * 60; from + 60 <= minutes(opening.close); from += 60) {
    if (taken.every((t) => t.to <= from || t.from >= from + 60)) return hhmm(from)
  }
  return null
}
