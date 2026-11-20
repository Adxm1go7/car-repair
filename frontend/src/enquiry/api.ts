import { post, request } from '../booking/api.ts'
import type { Result } from '../booking/api.ts'
import type { CustomerDetails } from '../booking/types.ts'

/** What the enquiry form sends: the booking form's details, with a description instead of notes. */
export type EnquiryDetails = Omit<CustomerDetails, 'notes'> & { description: string }

/** Send an enquiry. The reply says where the "we've got it" email is going. */
export function sendEnquiry(details: EnquiryDetails, website = ''): Promise<Result<{ email: string }>> {
  return request<{ email: string }>('/api/enquiries', post({ ...details, website }))
}
