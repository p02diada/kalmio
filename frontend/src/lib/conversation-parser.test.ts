import { describe, expect, it } from 'vitest'

import { parseConversationInput } from '@/lib/conversation-parser'

describe('parseConversationInput', () => {
  it('parses a city route', () => {
    const result = parseConversationInput('Quiero ir desde Córdoba hasta Valencia y voy al 58%.')

    expect(result.form.originLabel).toBe('Córdoba')
    expect(result.form.destinationLabel).toBe('Valencia')
    expect(result.form.originLat).toBe('37.8882')
    expect(result.form.destinationLat).toBe('39.4699')
    expect(result.missing).toEqual([])
    expect(result.summary[0]).toContain('Origen Córdoba.')
  })

  it('captures reserve policy from Spanish phrases', () => {
    const result = parseConversationInput('No quiero bajar del 20% de batería.')

    expect(result.preferences.reserve_min_percent).toBe(20)
    expect(result.summary.join(' ')).toContain('Reserva mínima 20%.')
  })

  it('captures service preference', () => {
    const result = parseConversationInput('Quiero parar a comer durante la carga.')

    expect(result.preferences.prefer_services).toBe(true)
  })
})
