export type StaffRole = 'admin' | 'staff'

/** The logged-in staff user, from GET /api/staff/me. */
export type StaffMe = { id: number; name: string; email: string; role: StaffRole }

export type Message = { detail: string }

export type BookingStatus =
  | 'held'
  | 'pending_approval'
  | 'confirmed'
  | 'in_progress'
  | 'completed'
  | 'cancelled'
  | 'no_show'
  | 'expired'

export type ScheduleBay = { id: number; slug: string; name: string; bay_type: string }

/** One day's opening, as garage-local "HH:MM". open/close are null on a closed day. */
export type ScheduleDay = {
  date: string
  open: string | null
  close: string | null
  breaks: { start: string; end: string }[]
}

type ItemTimes = { bay_id: number; start: string; end: string } // garage-local ISO

export type ScheduleBooking = ItemTimes & {
  kind: 'booking'
  reference: string
  status: BookingStatus
  registration: string
  services: string[]
  source: 'online' | 'phone'
  has_email: boolean
}

export type ScheduleBlock = ItemTimes & { kind: 'block'; block_id: number; note: string | null }

export type ScheduleItem = ScheduleBooking | ScheduleBlock

/** GET /api/staff/schedule */
export type Schedule = { timezone: string; bays: ScheduleBay[]; days: ScheduleDay[]; items: ScheduleItem[] }
