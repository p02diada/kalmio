import { csrfHeaders, ensureCsrfCookie } from '@/lib/api/auth'
import { API_BASE_URL } from '@/lib/api/config'
import { assertRecord, errorDetail, readNumber, readString } from '@/lib/api/validation'

export type FeedbackKind = 'useful' | 'not_useful' | 'charger_busy' | 'wrong_data' | 'wrong_price'
export type FeedbackResponse = {
  id: number
  status: string
}

export async function sendFeedback(routePlanId: string, kind: FeedbackKind, comment = ''): Promise<FeedbackResponse> {
  await ensureCsrfCookie()
  const response = await fetch(`${API_BASE_URL}/api/feedback`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...csrfHeaders(),
    },
    body: JSON.stringify({
      route_plan_id: routePlanId,
      kind,
      comment,
    }),
  })

  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(errorDetail(body, `Feedback request failed with ${response.status}`))
  }

  const value = assertRecord(body, 'Feedback')
  return {
    id: readNumber(value, 'id', 'Feedback'),
    status: readString(value, 'status', 'Feedback'),
  }
}
