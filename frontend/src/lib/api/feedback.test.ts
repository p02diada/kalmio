import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.restoreAllMocks()
  vi.resetModules()
  document.cookie = 'csrftoken=; Max-Age=0'
})

describe('feedback API contract', () => {
  it('rejects malformed feedback responses', async () => {
    document.cookie = 'csrftoken=test-token'
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = input.toString()
      if (url.includes('/api/auth/csrf')) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: 'csrf cookie set', csrf_token: 'test-token' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      return Promise.resolve(
        new Response(JSON.stringify({ id: 1 }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    })
    const { sendFeedback } = await import('@/lib/api/feedback')

    await expect(sendFeedback('plan-123', 'useful')).rejects.toThrow('Feedback: status inválido.')
  })
})
