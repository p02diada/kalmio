import { afterEach, describe, expect, it, vi } from 'vitest'

import { buildRoutePlanRequest, type RoutePlanFormValues } from '@/lib/api/route-plan'

const validForm: RoutePlanFormValues = {
  originLabel: 'Córdoba',
  originLat: '37.8882',
  originLon: '-4.7794',
  destinationLabel: 'Valencia',
  destinationLat: '39.4699',
  destinationLon: '-0.3763',
  corridorRadiusKm: '35',
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.resetModules()
  document.cookie = 'csrftoken=; Max-Age=0'
})

describe('buildRoutePlanRequest', () => {
  it('rejects invalid latitude before calling the API', () => {
    expect(() =>
      buildRoutePlanRequest({ ...validForm, originLat: '120' }),
    ).toThrow('latitud origen entre -90 y 90')
  })

  it('rejects invalid corridor radius before calling the API', () => {
    expect(() =>
      buildRoutePlanRequest({ ...validForm, corridorRadiusKm: '150' }),
    ).toThrow('radio de corredor entre 0.1 y 100')
  })

  it('builds a route request without vehicle fields', () => {
    const payload = buildRoutePlanRequest(validForm)

    expect(payload).toEqual({
      origin: { lat: 37.8882, lon: -4.7794 },
      destination: { lat: 39.4699, lon: -0.3763 },
      origin_label: 'Córdoba',
      destination_label: 'Valencia',
      corridor_radius_km: 35,
    })
  })

})

describe('route plan API contract', () => {
  it('rejects malformed route-plan responses', async () => {
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
        new Response(JSON.stringify({ id: 'plan-1', origin_label: 'Córdoba' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    })
    const { requestRoutePlan, buildRoutePlanRequest } = await import('@/lib/api/route-plan')

    await expect(
      requestRoutePlan(buildRoutePlanRequest(validForm)),
    ).rejects.toThrow('Route plan: created_at inválido.')
  })
})
