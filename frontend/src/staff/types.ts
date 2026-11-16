export type StaffRole = 'admin' | 'staff'

/** The logged-in staff user, from GET /api/staff/me. */
export type StaffMe = { id: number; name: string; email: string; role: StaffRole }

export type Message = { detail: string }
