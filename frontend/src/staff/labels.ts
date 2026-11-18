import type { BookingAction, BookingStatus, DepositStatus, StaffRole, StaffState } from './types.ts'

export const STATUS_LABEL: Record<BookingStatus, string> = {
  held: 'Being booked',
  pending_approval: 'Waiting for approval',
  confirmed: 'Confirmed',
  in_progress: 'In progress',
  completed: 'Completed',
  cancelled: 'Cancelled',
  no_show: 'No show',
  expired: 'Expired',
}

export const ACTION_LABEL: Record<BookingAction, string> = {
  start: 'Start job',
  complete: 'Complete job',
  no_show: 'Mark no show',
  undo_start: 'Undo start',
  undo_complete: 'Undo complete',
  undo_no_show: 'Undo no show',
  move: 'Move',
  cancel: 'Cancel booking',
}

export const DEPOSIT_LABEL: Record<DepositStatus, string> = {
  unpaid: 'Deposit not paid',
  paid: 'Deposit paid',
  refund_pending: 'Deposit refund on its way',
  refunded: 'Deposit refunded',
  refund_failed: 'Deposit refund failed — check Stripe',
  waived: 'No deposit (booked before deposits)',
  not_required: 'Phone booking · no deposit',
}

export const ROLE_LABEL: Record<StaffRole, string> = { admin: 'Admin', staff: 'Staff' }

export const STATE_LABEL: Record<StaffState, string> = {
  invited: 'Invited',
  active: 'Active',
  reset_sent: 'Reset sent',
  removed: 'Removed',
}

export const NO_EMAIL = 'No email, phone only'
export const STALE = 'That has changed since you opened this page, so it has been reloaded.'
export const FAILED = 'Something went wrong. Please try again.'

/** "Have you called the customer?" plus what happens next, for a move or a cancel. */
export function callFirst(hasEmail: boolean, emailed: string): string {
  return `Have you called the customer? ${hasEmail ? emailed : 'They have no email, so remember to tell them.'}`
}

/** "2026-11-17" and "09:30" straight from a garage-local ISO time, such as "2026-11-17T09:30:00+00:00". */
export function localDate(iso: string): string {
  return iso.slice(0, 10)
}

export function localTime(iso: string): string {
  return iso.slice(11, 16)
}
