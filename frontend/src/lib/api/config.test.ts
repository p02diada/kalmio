import { describe, expect, it } from 'vitest'

import { resolveApiBaseUrl } from '@/lib/api/config'

describe('API base URL config', () => {
  it('uses localhost only in development when no base URL is configured', () => {
    expect(resolveApiBaseUrl({ DEV: true, PROD: false }, 'localhost')).toBe('http://127.0.0.1:8000')
    expect(resolveApiBaseUrl({ DEV: true, PROD: false }, '127.0.0.1')).toBe('http://127.0.0.1:8000')
    expect(resolveApiBaseUrl({ DEV: false, PROD: true })).toBe('')
  })

  it('uses same-origin in development when served through a public tunnel', () => {
    expect(resolveApiBaseUrl({ DEV: true, PROD: false }, 'environmental-appendix-intervention-self.trycloudflare.com')).toBe(
      '',
    )
  })

  it('allows same-origin paths in production', () => {
    expect(resolveApiBaseUrl({ VITE_API_BASE_URL: 'same-origin', DEV: true, PROD: false })).toBe('')
    expect(resolveApiBaseUrl({ VITE_API_BASE_URL: 'same-origin', DEV: false, PROD: true })).toBe('')
    expect(resolveApiBaseUrl({ VITE_API_BASE_URL: '/', DEV: false, PROD: true })).toBe('')
    expect(resolveApiBaseUrl({ VITE_API_BASE_URL: '/backend/', DEV: false, PROD: true })).toBe('/backend')
  })

  it('requires HTTPS for absolute production API URLs', () => {
    expect(resolveApiBaseUrl({ VITE_API_BASE_URL: 'https://api.kalmio.example/', DEV: false, PROD: true })).toBe(
      'https://api.kalmio.example',
    )
    expect(() =>
      resolveApiBaseUrl({ VITE_API_BASE_URL: 'http://api.kalmio.example', DEV: false, PROD: true }),
    ).toThrow('VITE_API_BASE_URL must use HTTPS in production.')
  })

  it('rejects ambiguous relative base URLs', () => {
    expect(() => resolveApiBaseUrl({ VITE_API_BASE_URL: 'api.kalmio.example', DEV: false, PROD: true })).toThrow(
      'VITE_API_BASE_URL must be "same-origin", "/", a same-origin path, or an absolute HTTP(S) URL.',
    )
  })
})
