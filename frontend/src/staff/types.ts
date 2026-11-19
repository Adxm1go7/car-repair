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

export type BookingAction =
  | 'start'
  | 'complete'
  | 'no_show'
  | 'undo_start'
  | 'undo_complete'
  | 'undo_no_show'
  | 'move'
  | 'cancel'

export type StatusAction = Exclude<BookingAction, 'move' | 'cancel'>

export type DepositStatus = 'unpaid' | 'paid' | 'refund_pending' | 'refunded' | 'refund_failed' | 'waived' | 'not_required'

/** GET /api/staff/bookings/:reference. start, end and history times are garage-local ISO. */
export type StaffBooking = {
  reference: string
  status: BookingStatus
  source: 'online' | 'phone'
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
  actions: BookingAction[]
  starts_on_another_day: boolean
  history: { at: string; text: string }[]
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
