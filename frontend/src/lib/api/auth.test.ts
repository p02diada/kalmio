import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.restoreAllMocks()
  vi.resetModules()
  document.cookie = 'csrftoken=; Max-Age=0'
})

describe('auth API CSRF handling', () => {
  it('updates the cached CSRF token after register rotates it', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = input.toString()
      if (url.includes('/api/auth/csrf')) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: 'csrf cookie set', csrf_token: 'old-token' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      if (url.includes('/api/auth/register')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              id: 1,
              email: 'driver@example.com',
              authenticated: true,
              csrf_token: 'rotated-token',
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }

      return Promise.reject(new Error(`Unexpected request: ${url}`))
    })
    const { csrfHeaders, register } = await import('@/lib/api/auth')

    await register({ email: 'driver@example.com', password: 'safe-password-123' })

    expect(csrfHeaders()).toEqual({ 'X-CSRFToken': 'rotated-token' })
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/api/auth/register'),
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-CSRFToken': 'old-token' }),
      }),
    )
  })
})
