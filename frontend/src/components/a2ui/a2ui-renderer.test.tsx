import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { A2UIRenderer } from './a2ui-renderer'

describe('A2UIRenderer', () => {
  it('renders a fallback for unknown blocks', () => {
    render(<A2UIRenderer blocks={[{ id: 'x', type: 'UnknownCard', version: 1, props: {} }]} />)

    expect(screen.getByText('Bloque no disponible')).toBeInTheDocument()
    expect(screen.getByText('UnknownCard')).toBeInTheDocument()
  })

  it('explains disabled actions', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'actions',
            type: 'ActionButtons',
            version: 1,
            props: {
              actions: [
                {
                  label: 'Abrir en Maps',
                  disabled: true,
                  reason: 'Faltan coordenadas u origen confirmado.',
                },
              ],
            },
          },
        ]}
      />,
    )

    expect(screen.getByRole('button', { name: 'Abrir en Maps' })).toBeDisabled()
    expect(screen.getByText('Faltan coordenadas u origen confirmado.')).toBeInTheDocument()
  })

  it('requests browser location through an allowlisted location block', () => {
    const getCurrentPosition = vi.fn((success: PositionCallback) => {
      success({
        coords: {
          latitude: 37.88,
          longitude: -4.78,
          accuracy: 30,
          altitude: null,
          altitudeAccuracy: null,
          heading: null,
          speed: null,
          toJSON: () => ({}),
        },
        timestamp: Date.now(),
        toJSON: () => ({}),
      })
    })
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { getCurrentPosition },
    })
    const onLocationSubmit = vi.fn()

    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'location',
            type: 'LocationRequestCard',
            version: 1,
            props: {
              title: 'Necesito tu ubicación',
              body: 'Comparte tu ubicación o escribe una ciudad/coordenadas.',
              manualFields: ['ciudad', 'latitud', 'longitud'],
            },
          },
        ]}
        onLocationSubmit={onLocationSubmit}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Usar mi ubicación' }))

    expect(getCurrentPosition).toHaveBeenCalledWith(
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ maximumAge: 60000, timeout: 10000 }),
    )
    expect(onLocationSubmit).toHaveBeenCalledWith('Estoy en 37.880000, -4.780000')
  })
})
