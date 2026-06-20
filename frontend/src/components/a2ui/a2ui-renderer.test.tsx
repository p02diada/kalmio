import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { A2UIRenderer } from './a2ui-renderer'

describe('A2UIRenderer', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

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
            type: 'PlaceDetailCard',
            version: 1,
            props: {
              label: { label: 'Alcobendas' },
              lat: 40.5403,
              lon: -3.6358,
              precision: 'approximate',
              context: 'Lugar usado para buscar estaciones de carga',
              needsConfirmation: true,
            },
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
            id: 'place-detail',
            type: 'PlaceDetailCard',
            version: 1,
            props: {
              label: { label: 'Córdoba' },
              lat: 37.8882,
              lon: -4.7794,
              precision: 'approximate',
              context: 'Lugar usado para buscar una parada de carga urgente',
              needsConfirmation: true,
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Lugar resuelto')).toBeInTheDocument()
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

  it('uses human route duration text when the agent provides it', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'route',
            type: 'RouteSummaryCard',
            version: 1,
            props: {
              distanceKm: 356.7,
              durationMin: 240,
              durationText: '4 h 0 min',
              energyKwh: null,
              arrivalBattery: null,
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('4 h 0 min')).toBeInTheDocument()
    expect(screen.queryByText('240 min')).not.toBeInTheDocument()
  })

  it('renders a station detail as the primary charging decision', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'recommended',
            type: 'StationDetailCard',
            version: 1,
            props: {
              stationName: 'Almansa HPC',
              powerKw: 180,
              pricePerKwhEur: 0.49,
              currency: 'EUR',
              priceIsEstimated: false,
              distanceKm: 1.2,
              detourMin: 8,
              availableEvses: 2,
              connectorTypes: ['CCS2'],
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Estación de carga')).toBeInTheDocument()
    expect(screen.getByText('Almansa HPC')).toBeInTheDocument()
    expect(screen.getByText('1.2 km')).toBeInTheDocument()
    expect(screen.getByText('0.49 €/kWh')).toBeInTheDocument()
    expect(screen.getByText('2 EVSEs')).toBeInTheDocument()
    expect(screen.getByText('CCS2')).toBeInTheDocument()
  })

  it('renders urgent station data without repeating the user battery as a primary metric', () => {
    const stationName = 'BALLENOIL-ES336090-COLON'

    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'urgent',
            type: 'StationDetailCard',
            version: 1,
            props: {
              title: 'Estación cercana',
              stationName,
              distanceKm: 0.3,
              powerKw: 150,
              availableEvses: 2,
              connectorTypes: ['CCS2'],
            },
          },
          {
            id: 'risk',
            type: 'RiskExplanationCard',
            version: 1,
            props: {
              level: 'alto',
              text: 'Margen bajo: confirma acceso y disponibilidad antes de depender de esta estación.',
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Estación cercana')).toBeInTheDocument()
    expect(screen.queryByText('12%')).not.toBeInTheDocument()
    expect(screen.getByText(stationName)).toHaveClass('break-words')
    expect(screen.getByText('Margen bajo: confirma acceso y disponibilidad antes de depender de esta estación.')).toBeInTheDocument()
  })

  it('renders station recommendations with traceable station details', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'recommended',
            type: 'StationDetailCard',
            version: 1,
            props: {
              stationName: 'Almansa HPC',
              address: 'Área de servicio Almansa',
              powerKw: 180,
              distanceKm: 1.2,
              detourMin: 8,
              confidence: 'media',
              availableEvses: 2,
              connectorTypes: ['CCS2', 'TYPE2'],
            },
          },
          {
            id: 'alternatives',
            type: 'StationList',
            version: 1,
            props: {
              title: 'Otras estaciones viables',
              stations: [
                {
                  stationName: 'Centro CCS',
                  address: 'Parking centro',
                  powerKw: 90,
                  pricePerKwhEur: 0.59,
                  currency: 'EUR',
                  priceIsEstimated: false,
                  distanceKm: 0.7,
                  availableEvses: 3,
                  connectorTypes: ['CCS2'],
                },
              ],
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Almansa HPC')).toBeInTheDocument()
    expect(screen.getByText('Área de servicio Almansa')).toBeInTheDocument()
    expect(screen.getByText('Capacidad')).toBeInTheDocument()
    expect(screen.getByText('2 EVSEs')).toBeInTheDocument()
    expect(screen.getByText('Conectores trazados')).toBeInTheDocument()
    expect(screen.getByText('TYPE2')).toBeInTheDocument()
    expect(screen.getByText('Otras estaciones viables')).toBeInTheDocument()
    expect(screen.getByText('Centro CCS')).toBeInTheDocument()
    expect(screen.getByText(/Precio 0.59 €\/kWh/)).toBeInTheDocument()
    expect(screen.getByText(/Capacidad trazada: 3 EVSEs/)).toBeInTheDocument()
    expect(screen.getByText(/Conectores trazados: CCS2/)).toBeInTheDocument()
  })

  it('renders an expandable route map with traced route stations', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)

    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'route-map',
            type: 'MapPreviewCard',
            version: 1,
            props: {
              origin: { label: 'Zaragoza', lat: 41.6488, lon: -0.8891 },
              destination: { label: 'Valencia', lat: 39.4699, lon: -0.3763 },
              primaryStation: { stationName: 'Kalmio demo HPC', lat: 40.345, lon: -0.997 },
              stations: [{ stationName: 'Demo Charge 1', lat: 40.583, lon: -1.268 }],
              routeGeometry: {
                type: 'LineString',
                coordinates: [
                  [-0.8891, 41.6488],
                  [-1.105, 40.343],
                  [-0.3763, 39.4699],
                ],
              },
              corridorRadiusKm: 25,
              geometryPrecision: 'provider',
              source: 'plan_route',
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Mapa de ruta')).toBeInTheDocument()
    expect(screen.getByText('Ruta real')).toBeInTheDocument()
    expect(screen.getByText('2 estaciones')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Expandir mapa' }))

    expect(screen.getByText('Cargadores en ruta')).toBeInTheDocument()
    expect(screen.getAllByText('Kalmio demo HPC').length).toBeGreaterThan(1)
    expect(screen.getAllByText('Demo Charge 1').length).toBeGreaterThan(1)
  })

  it('hides station prices marked as estimated', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'station',
            type: 'StationDetailCard',
            version: 1,
            props: {
              stationName: 'Almansa HPC',
              powerKw: 180,
              pricePerKwhEur: 0.49,
              currency: 'EUR',
              priceIsEstimated: true,
            },
          },
        ]}
      />,
    )

    expect(screen.queryByText('0.49 €/kWh')).not.toBeInTheDocument()
    expect(screen.queryByText('Precio')).not.toBeInTheDocument()
  })

  it('renders traced tariff comparisons per kWh', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'cost',
            type: 'CostComparisonCard',
            version: 1,
            props: {
              best: 'Almansa HPC',
              pricePerKwhEur: 0.49,
              comparedWith: 'Almansa AC',
              comparedWithPricePerKwhEur: 0.59,
              savingPerKwhEur: 0.1,
              currency: 'EUR',
              priceIsEstimated: false,
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Almansa HPC')).toBeInTheDocument()
    expect(screen.getByText('0.49 €/kWh')).toBeInTheDocument()
    expect(screen.getByText('0.59 €/kWh')).toBeInTheDocument()
    expect(screen.getByText('0.1 EUR')).toBeInTheDocument()
    expect(screen.getByText('Comparado con Almansa AC.')).toBeInTheDocument()
  })

  it('does not render estimated tariffs as a cost comparison', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'cost',
            type: 'CostComparisonCard',
            version: 1,
            props: {
              best: 'Almansa HPC',
              pricePerKwhEur: 0.49,
              currency: 'EUR',
              priceIsEstimated: true,
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('No puedo mostrar una parte de la respuesta')).toBeInTheDocument()
    expect(screen.queryByText('0.49 €/kWh')).not.toBeInTheDocument()
    expect(screen.queryByText('Tarifa')).not.toBeInTheDocument()
  })

  it('renders traced amenities without claiming unverified proximity or child suitability', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'recommended',
            type: 'StationDetailCard',
            version: 1,
            props: {
              stationName: 'Moya Hub Honrubia',
              powerKw: 240,
              distanceKm: 1.23,
              detourMin: 3,
              confidence: 'media',
              amenities: ['HOTEL', 'RESTAURANT', 'PARKING_LOT', 'FUEL_STATION', 'WIFI', 'CAFE', 'SUPERMARKET'],
            },
          },
          {
            id: 'alternatives',
            type: 'StationList',
            version: 1,
            props: {
              stations: [
                {
                  stationName: 'Aparcamiento CTM',
                  powerKw: 400,
                  distanceKm: 4.77,
                  detourMin: 11,
                  amenities: ['RESTAURANT', 'CAFE'],
                },
              ],
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Servicios trazados')).toBeInTheDocument()
    expect(screen.getByText('Restaurante')).toBeInTheDocument()
    expect(screen.getByText('Cafetería')).toBeInTheDocument()
    expect(screen.getByText('+3 más')).toBeInTheDocument()
    expect(screen.getByText(/400 kW · 4.8 km · Desvío 11 min/)).toBeInTheDocument()
    expect(screen.getByText(/Servicios trazados: Restaurante, Cafetería/)).toBeInTheDocument()
    expect(screen.queryByText(/apto para niños|ideal|seguro/i)).not.toBeInTheDocument()
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

    expect(screen.getByRole('button', { name: longChip })).toHaveClass('max-w-full', 'whitespace-normal', 'break-words', 'py-2')
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
    const onPositionSubmit = vi.fn()

    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'place',
            type: 'PositionRequestCard',
            version: 1,
            props: {
              title: 'Necesito tu ubicación',
              body: 'Comparte tu ubicación o escribe una ciudad/coordenadas.',
              manualFields: ['ciudad', 'latitud', 'longitud'],
            },
          },
        ]}
        onPositionSubmit={onPositionSubmit}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Usar mi ubicación' }))

    expect(getCurrentPosition).toHaveBeenCalledWith(
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ maximumAge: 60000, timeout: 10000 }),
    )
    expect(onPositionSubmit).toHaveBeenCalledWith('Estoy en 37.880000, -4.780000')
  })
})
