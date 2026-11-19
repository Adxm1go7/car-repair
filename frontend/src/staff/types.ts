import type { Timetable } from '../catalogue/types.ts'

export type StaffRole = 'admin' | 'staff'

/** The logged-in staff user, from GET /api/staff/me. */
export type StaffMe = { id: number; name: string; email: string; role: StaffRole }

export type Message = { detail: string }

export type BookingStatus =
  | 'held'
  | 'pending_approval'
  | 'awaiting_deposit'
  | 'confirmed'
  | 'in_progress'
  | 'completed'
  | 'cancelled'
  | 'no_show'
  | 'expired'

/** `active` false: out of use, listed only on days where it has bookings or blocks. */
export type ScheduleBay = { id: number; slug: string; name: string; bay_type: string; active: boolean }

/** One day's opening, as garage-local "HH:MM". open/close are null on a closed day. */
export type ScheduleDay = {
  date: string
  open: string | null
  close: string | null
  breaks: { start: string; end: string }[]
}

type ItemTimes = { bay_id: number; start: string; end: string } // garage-local ISO

export type BookingSource = 'online' | 'phone' | 'enquiry'

export type ScheduleBooking = ItemTimes & {
  kind: 'booking'
  reference: string
  status: BookingStatus
  registration: string
  services: string[]
  source: BookingSource
  has_email: boolean
}

export type ScheduleBlock = ItemTimes & { kind: 'block'; block_id: number; note: string | null }

export type ScheduleItem = ScheduleBooking | ScheduleBlock

/** GET /api/staff/schedule */
export type Schedule = { timezone: string; bays: ScheduleBay[]; days: ScheduleDay[]; items: ScheduleItem[] }

export type BookingAction =
  | 'start'
  | 'complete'
  | 'no_show'
  | 'undo_start'
  | 'undo_complete'
  | 'undo_no_show'
  | 'move'
  | 'cancel'
  | 'approve'
  | 'propose'
  | 'decline'

export type StatusAction = Exclude<BookingAction, 'move' | 'cancel' | 'approve' | 'propose' | 'decline'>

export type DepositStatus = 'unpaid' | 'paid' | 'refund_pending' | 'refunded' | 'refund_failed' | 'waived' | 'not_required'

/** GET /api/staff/bookings/:reference. start, end and history times are garage-local ISO. */
export type StaffBooking = {
  reference: string
  status: BookingStatus
  source: BookingSource
  start: string
  end: string
  bay: { id: number; name: string }
  services: string[]
  registration: string | null
  make: string | null
  model: string | null
  customer_name: string | null
  customer_phone: string | null
  customer_email: string | null
  notes: string | null
  deposit_status: DepositStatus
  /** A request: when it must be answered by. An approval: when its deposit is due by. */
  deadline?: string | null
  actions: BookingAction[]
  starts_on_another_day: boolean
  /** The enquiry this booking was made from. */
  enquiry_id?: number | null
  history: { at: string; text: string }[]
}

/** GET /api/staff/requests: an online request waiting for an answer. Times garage-local ISO. */
export type StaffRequest = {
  reference: string
  customer_name: string | null
  services: string[]
  start: string
  bay: string
  deadline: string
  created_at: string
}

export type EnquiryStatus = 'new' | 'converted' | 'declined'

/** One row of the Enquiries page. Times are garage-local ISO. */
export type StaffEnquiryRow = {
  id: number
  status: EnquiryStatus
  customer_name: string
  registration: string
  make: string
  model: string
  summary: string
  created_at: string
  handled_at: string | null
}

export type StaffEnquiry = {
  id: number
  status: EnquiryStatus
  customer_name: string
  customer_phone: string
  customer_email: string
  registration: string
  make: string
  model: string
  description: string
  created_at: string
  handled_at: string | null
  handled_by: string | null
  decline_reason: string | null
  booking_reference: string | null
  actions: ('approve' | 'decline')[]
}

export type StaffSlot = { start: string; end: string; bay_ids: number[] }

/** GET /api/staff/availability and /bookings/:reference/move-options. */
export type StaffAvailability = {
  date: string
  timezone: string
  duration_minutes: number
  unavailable_reason: 'mixed_bay_types' | null
  slots: StaffSlot[]
}

// --- admin: team and audit --------------------------------------------------------

export type StaffState = 'invited' | 'active' | 'reset_sent' | 'removed'

/** GET /api/staff/team: one account. */
export type TeamMember = { id: number; name: string; email: string; role: StaffRole; state: StaffState }

/** One row of GET /api/staff/audit. `at` is garage-local ISO; `staff_name` is "Setup" for create_admin. */
export type AuditEntry = {
  at: string
  staff_name: string
  action: string
  entity_type: string
  entity_id: number
  booking_reference: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  reason: string | null
}

export type AuditPage = { entries: AuditEntry[]; page: number; has_more: boolean }

// --- admin: settings --------------------------------------------------------------

export type ApprovalMode = 'instant' | 'needs_approval'

/** GET /api/staff/settings/services: every service, shown and hidden, in display order. */
export type AdminService = {
  id: number
  slug: string
  name: string
  category: string
  description: string
  duration_minutes: number
  price_from_pence: number
  price_to_pence: number | null
  bay_type_id: number
  bay_type: string
  approval_mode: ApprovalMode
  active: boolean
  sort_order: number
}

/** The fields an edit can change. Bay type and approval mode are fixed once added. */
export type ServiceFields = Pick<
  AdminService,
  'name' | 'category' | 'description' | 'duration_minutes' | 'price_from_pence' | 'price_to_pence'
>

export type NewService = ServiceFields & { bay_type_id: number; approval_mode: ApprovalMode }

export type BayType = { id: number; slug: string; name: string }

/** GET /api/staff/settings/bays */
export type AdminBay = { id: number; slug: string; name: string; bay_type_id: number; bay_type: string; active: boolean }

/** A booking in the way of a settings change. `start` is garage-local ISO; `held` means a
 * customer is paying for it right now, so it clears by itself in a few minutes. */
export type Clash = { reference: string; start: string; bay: string; held: boolean }

/** GET /api/staff/settings/hours: one timetable. Only future ones can be edited or deleted. */
export type AdminTimetable = Timetable & { id: number; state: 'past' | 'current' | 'future' }
