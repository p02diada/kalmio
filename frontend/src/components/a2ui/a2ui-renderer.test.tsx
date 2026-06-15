import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { A2UIRenderer } from './a2ui-renderer'

describe('A2UIRenderer', () => {
  it('renders a fallback for unknown blocks', () => {
    render(<A2UIRenderer blocks={[{ id: 'x', type: 'UnknownCard', version: 1, props: {} }]} />)

    expect(screen.getByText('No puedo mostrar una parte de la respuesta')).toBeInTheDocument()
    expect(screen.getByText('UnknownCard')).toBeInTheDocument()
  })

  it('normalizes object labels before rendering text', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'destination',
            type: 'DestinationChargingCard',
            version: 1,
            props: { destination: { label: 'Alcobendas' }, needsConfirmation: true },
          },
        ]}
      />,
    )

    expect(screen.getByText('Alcobendas')).toBeInTheDocument()
    expect(screen.queryByText(/label/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/\[object Object\]/i)).not.toBeInTheDocument()
  })

  it('renders resolved location details without raw object labels', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'location-detail',
            type: 'LocationDetailCard',
            version: 1,
            props: {
              label: { label: 'Córdoba' },
              lat: 37.8882,
              lon: -4.7794,
              precision: 'approximate',
              context: 'Ubicación usada para buscar una parada de carga urgente',
              needsConfirmation: true,
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Detalle de ubicación')).toBeInTheDocument()
    expect(screen.getByText('Córdoba')).toBeInTheDocument()
    expect(screen.getByText('37.88820, -4.77940')).toBeInTheDocument()
    expect(screen.queryByText(/\[object Object\]/i)).not.toBeInTheDocument()
  })

  it('renders unknown route numbers as not calculated', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'route',
            type: 'RouteSummaryCard',
            version: 1,
            props: {
              distanceKm: 520,
              durationMin: 355,
              energyKwh: 0,
              arrivalBattery: 0,
            },
          },
        ]}
      />,
    )

    expect(screen.queryByText('0 kWh')).not.toBeInTheDocument()
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
    expect(screen.getAllByText('No calculado')).toHaveLength(2)
  })

  it('marks the recommended stop as the primary decision', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'recommended',
            type: 'RecommendedStopCard',
            version: 1,
            props: { name: 'Almansa HPC', powerKw: 180, distanceKm: 1.2, detourMin: 8, confidence: 'media' },
          },
        ]}
      />,
    )

    expect(screen.getByText('Parada recomendada')).toBeInTheDocument()
    expect(screen.getByText('Almansa HPC')).toBeInTheDocument()
    expect(screen.getByText('1.2 km')).toBeInTheDocument()
  })

  it('renders place-first stop recommendations with traceable charging point detail', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'recommended',
            type: 'RecommendedStopCard',
            version: 1,
            props: {
              placeName: 'Área de servicio Almansa',
              stationName: 'Almansa HPC',
              name: 'Almansa HPC',
              powerKw: 180,
              distanceKm: 1.2,
              detourMin: 8,
              confidence: 'media',
            },
          },
          {
            id: 'alternatives',
            type: 'AlternativeStopsList',
            version: 1,
            props: {
              stops: [
                {
                  placeName: 'Parking centro',
                  stationName: 'Centro CCS',
                  name: 'Centro CCS',
                  powerKw: 90,
                  distanceKm: 0.7,
                },
              ],
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Área de servicio Almansa')).toBeInTheDocument()
    expect(screen.getByText('Punto de carga: Almansa HPC')).toBeInTheDocument()
    expect(screen.getByText('Otras paradas viables')).toBeInTheDocument()
    expect(screen.getByText('Parking centro')).toBeInTheDocument()
    expect(screen.getByText(/Punto de carga: Centro CCS/)).toBeInTheDocument()
  })

  it('labels medium uncertainty as data to confirm', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'risk',
            type: 'RiskExplanationCard',
            version: 1,
            props: {
              level: 'medio',
              text: 'Confirma acceso final, tarifa y disponibilidad antes de depender de ellos.',
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Datos a confirmar')).toBeInTheDocument()
    expect(screen.queryByText('Riesgo a confirmar')).not.toBeInTheDocument()
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

  it('allows long preference chips to wrap instead of forcing horizontal scroll', () => {
    const longChip = 'Paradas cerca del hotel con servicios para una parada larga'

    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'chips',
            type: 'PreferenceChips',
            version: 1,
            props: { chips: [longChip] },
          },
        ]}
      />,
    )

    expect(screen.getByRole('button', { name: longChip })).toHaveClass('max-w-full', 'whitespace-normal', 'break-words')
  })

  it('opens registered local function actions', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)

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
                  functionCall: {
                    call: 'openUrl',
                    args: { url: 'https://www.google.com/maps/search/?api=1&query=37.88,-4.78' },
                  },
                },
              ],
            },
          },
        ]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Abrir en Maps' }))

    expect(open).toHaveBeenCalledWith(
      'https://www.google.com/maps/search/?api=1&query=37.88,-4.78',
      '_blank',
      'noopener,noreferrer',
    )
    open.mockRestore()
  })

  it('dispatches event actions back through the host adapter', () => {
    const onActionEvent = vi.fn()

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
                  label: 'Ajustar búsqueda',
                  event: { name: 'refine_search', context: { radiusKm: 80 } },
                },
              ],
            },
          },
        ]}
        onActionEvent={onActionEvent}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Ajustar búsqueda' }))

    expect(onActionEvent).toHaveBeenCalledWith('refine_search', { radiusKm: 80 }, 'actions')
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
