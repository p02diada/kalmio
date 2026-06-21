import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { A2UIRenderer } from './a2ui-renderer'

const maplibreMock = vi.hoisted(() => {
  const instances: Array<{
    addControl: ReturnType<typeof vi.fn>
    once: ReturnType<typeof vi.fn>
    addSource: ReturnType<typeof vi.fn>
    addLayer: ReturnType<typeof vi.fn>
    fitBounds: ReturnType<typeof vi.fn>
    resize: ReturnType<typeof vi.fn>
    on: ReturnType<typeof vi.fn>
    remove: ReturnType<typeof vi.fn>
  }> = []
  const markerElements: HTMLElement[] = []

  return {
    instances,
    Map: vi.fn(function Map(options: Record<string, unknown>) {
      const instance = {
        addControl: vi.fn(),
        once: vi.fn((_event: string, callback: () => void) => callback()),
        addSource: vi.fn(),
        addLayer: vi.fn(),
        fitBounds: vi.fn(),
        resize: vi.fn(),
        on: vi.fn(),
        remove: vi.fn(),
      }
      instances.push(instance)
      void options
      return instance
    }),
    markerElements,
    Marker: vi.fn(function Marker(options?: { element?: HTMLElement }) {
      if (options?.element) {
        markerElements.push(options.element)
      }
      const marker = {
        setLngLat: vi.fn(() => marker),
        addTo: vi.fn(() => marker),
        remove: vi.fn(),
      }
      return marker
    }),
    NavigationControl: vi.fn(function NavigationControl() {
      return {}
    }),
  }
})

vi.mock('maplibre-gl', () => maplibreMock)

describe('A2UIRenderer', () => {
  afterEach(() => {
    maplibreMock.instances.length = 0
    maplibreMock.markerElements.length = 0
    vi.clearAllMocks()
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
    expect(screen.getByText('Ubicación por confirmar.')).toBeInTheDocument()
    expect(screen.getByText(/la búsqueda depende de esta zona/i)).toBeInTheDocument()
    expect(screen.queryByText('37.88820, -4.77940')).not.toBeInTheDocument()
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

  it('renders trip summary arrival threshold without internal plan type copy', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'trip',
            type: 'TripSummaryCard',
            version: 1,
            props: {
              origin: { label: 'Zaragoza' },
              destination: { label: 'Valencia' },
              battery: 24,
              arrivalReservePercent: 12,
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Batería actual')).toBeInTheDocument()
    expect(screen.getByText('Llegar con al menos')).toBeInTheDocument()
    expect(screen.getByText('12%')).toBeInTheDocument()
    expect(screen.queryByText('Margen al llegar')).not.toBeInTheDocument()
    expect(screen.queryByText('Reserva mínima')).not.toBeInTheDocument()
    expect(screen.queryByText('Tipo')).not.toBeInTheDocument()
    expect(screen.queryByText('Conservadora')).not.toBeInTheDocument()
  })

  it('renders a station preview as the primary charging decision', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'recommended',
            type: 'StationPreviewCard',
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
    expect(screen.getByText('2 disponibles')).toBeInTheDocument()
    expect(screen.getByText('CCS2')).toBeInTheDocument()
  })

  it('opens the full station detail from a station preview card', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'recommended',
            type: 'StationPreviewCard',
            version: 1,
            props: {
              stationName: 'Almansa HPC',
              address: 'Área de servicio Almansa',
              powerKw: 180,
              pricePerKwhEur: 0.49,
              currency: 'EUR',
              priceIsEstimated: false,
              distanceKm: 1.2,
              detourMin: 8,
              availableEvses: 2,
              totalEvses: 6,
              connectorTypes: ['CCS2'],
              amenities: ['RESTAURANT', 'CAFE'],
              uncertainty: {
                level: 'medium',
                text: 'Confirma acceso antes de desviarte.',
                source: 'authorized_chargers',
              },
            },
          },
        ]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Ver detalle completo de Almansa HPC' }))

    expect(screen.getByRole('dialog', { name: 'Detalle de estación' })).toBeInTheDocument()
    expect(screen.getByText('Puestos de carga')).toBeInTheDocument()
    expect(screen.getByText('Carga y tarifa')).toBeInTheDocument()
    expect(screen.getAllByText('Servicios indicados').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Confirma acceso antes de desviarte. Fuente: datos autorizados de carga.').length).toBeGreaterThan(0)
  })

  it('renders a full station detail card inline', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'station-detail',
            type: 'StationDetailCard',
            version: 1,
            props: {
              stationName: 'Almansa HPC',
              address: 'Área de servicio Almansa',
              powerKw: 180,
              distanceKm: 1.2,
              detourMin: 8,
              availableEvses: 2,
              totalEvses: 6,
              connectorTypes: ['CCS2', 'TYPE2'],
              amenities: ['RESTAURANT'],
            },
          },
        ]}
      />,
    )

    expect(screen.getByLabelText('Detalle de estación')).toHaveClass('a2ui-station-detail-card')
    expect(screen.getByText('Almansa HPC')).toBeInTheDocument()
    expect(screen.getByText('Puestos de carga')).toBeInTheDocument()
    expect(screen.getByText('Carga y tarifa')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ver detalle completo de Almansa HPC' })).not.toBeInTheDocument()
  })

  it('renders urgent station data without repeating the user battery as a primary metric', () => {
    const stationName = 'BALLENOIL-ES336090-COLON'

    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'urgent',
            type: 'StationPreviewCard',
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

  it('keeps station detail text readable with long labels and compact mobile widths', () => {
    const stationName = 'Punto-de-carga-ultrarrapida-Zaragoza-salida-245-sin-espacios'

    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'urgent-long',
            type: 'StationPreviewCard',
            version: 1,
            props: {
              title: 'Estación cercana con confirmación pendiente',
              stationName,
              address: 'Salida 245, entorno urbano, acceso por via de servicio con descripcion larga',
              distanceKm: 1234567.8,
              powerKw: 350,
              availableEvses: 123456,
              connectorTypes: ['CCS2', 'TYPE2-SUPER-LONG-LABEL'],
            },
          },
        ]}
      />,
    )

    expect(screen.getByText(stationName)).toHaveClass('[overflow-wrap:anywhere]')
    expect(screen.getByText('Potencia máx.').closest('.grid')).toHaveClass('grid-cols-[repeat(auto-fit,minmax(min(7rem,100%),1fr))]')
    expect(screen.getByText('Potencia máx.')).toHaveClass('whitespace-normal')
    expect(screen.getByText('Potencia máx.')).not.toHaveClass('truncate')
    expect(screen.getByText('1234567.8 km')).toHaveClass('[overflow-wrap:anywhere]')
    expect(screen.getByText('TYPE2-SUPER-LONG-LABEL')).toHaveClass('[overflow-wrap:anywhere]')
  })

  it('renders station recommendations with traceable station details', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'recommended',
            type: 'StationPreviewCard',
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
    expect(screen.getByText(/Área de servicio Almansa/)).toBeInTheDocument()
    expect(screen.getAllByText('Puestos').length).toBeGreaterThan(0)
    expect(screen.getByText('2 disponibles')).toBeInTheDocument()
    expect(screen.getAllByText('Conectores').length).toBeGreaterThan(0)
    expect(screen.getByText('TYPE2')).toBeInTheDocument()
    expect(screen.getByText('Otras estaciones viables')).toBeInTheDocument()
    expect(screen.getByText('1 alternativa')).toBeInTheDocument()
    expect(screen.getByText('Centro CCS')).toBeInTheDocument()
    expect(screen.getAllByText('Precio').length).toBeGreaterThan(0)
    expect(screen.getAllByText('0.59€/kWh').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Puestos').length).toBeGreaterThan(0)
    expect(screen.getByText('3 puestos libres')).toBeInTheDocument()
    expect(screen.getAllByText('Conectores').length).toBeGreaterThan(1)
    expect(screen.getAllByText('CCS2').length).toBeGreaterThan(0)
  })

  it('renders an expandable route map preview', () => {
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
              primaryStation: { stationName: 'Punto de muestra La Plana', lat: 40.345, lon: -0.997 },
              stations: [{ stationName: 'Punto de muestra Mudéjar', lat: 40.583, lon: -1.268 }],
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
    expect(screen.getByText('Ruta calculada')).toBeInTheDocument()
    expect(screen.getByText('2 estaciones')).toBeInTheDocument()

    expect(screen.getByRole('button', { name: 'Expandir mapa' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Abrir mapa de ruta' }))

    expect(screen.getByLabelText('Mapa de ruta ampliado')).toHaveClass('a2ui-map-fullscreen')
  })

  it('initializes route maps with a default vector base map', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)

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
              routeGeometry: {
                type: 'LineString',
                coordinates: [
                  [-0.8891, 41.6488],
                  [-0.3763, 39.4699],
                ],
              },
              geometryPrecision: 'provider',
              source: 'plan_route',
            },
          },
        ]}
      />,
    )

    await waitFor(() => expect(maplibreMock.Map).toHaveBeenCalled())

    const options = maplibreMock.Map.mock.calls[0]?.[0] as { attributionControl?: unknown; interactive?: unknown; style: string }
    expect(options.attributionControl).toBe(false)
    expect(options.interactive).toBe(false)
    expect(options.style).toBe('https://tiles.openfreemap.org/styles/positron')
    expect(screen.getByRole('link', { name: 'Atribución de OpenStreetMap' })).toHaveTextContent('© OSM')
    expect(maplibreMock.NavigationControl).not.toHaveBeenCalled()
  })

  it('enables map controls and attribution only in the expanded route map', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)

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
              primaryStation: {
                stationName: 'Punto de muestra La Plana',
                lat: 40.345,
                lon: -0.997,
                powerKw: 180,
                distanceKm: 2.4,
                detourMin: 6,
                availableEvses: 2,
                totalEvses: 5,
                connectorTypes: ['ccs2'],
              },
              routeGeometry: {
                type: 'LineString',
                coordinates: [
                  [-0.8891, 41.6488],
                  [-0.3763, 39.4699],
                ],
              },
              geometryPrecision: 'provider',
              source: 'plan_route',
            },
          },
        ]}
      />,
    )

    await waitFor(() => expect(maplibreMock.Map).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByRole('button', { name: 'Expandir mapa' }))

    await waitFor(() => expect(maplibreMock.Map).toHaveBeenCalledTimes(2))

    expect(screen.getByLabelText('Mapa de ruta ampliado')).toHaveClass('a2ui-map-fullscreen')

    const compactOptions = maplibreMock.Map.mock.calls[0]?.[0] as { attributionControl?: unknown; interactive?: unknown }
    const expandedOptions = maplibreMock.Map.mock.calls[1]?.[0] as { attributionControl?: unknown; interactive?: unknown }
    expect(compactOptions).toMatchObject({ attributionControl: false, interactive: false })
    expect(expandedOptions).toMatchObject({ attributionControl: {}, interactive: true })
    expect(maplibreMock.NavigationControl).toHaveBeenCalledTimes(1)
    expect(maplibreMock.instances[1]?.on).not.toHaveBeenCalled()

    const expandedPrimaryMarker = maplibreMock.markerElements.findLast((element) => (
      element.getAttribute('aria-label') === 'Ver Punto de muestra La Plana'
    ))
    expect(expandedPrimaryMarker?.textContent).toContain('2/5')
    expect(expandedPrimaryMarker?.querySelector('.a2ui-map-marker-label')).toHaveTextContent('2/5')
    expect(expandedPrimaryMarker?.querySelector('.a2ui-map-marker-label')).not.toHaveTextContent('puestos')

    fireEvent.click(expandedPrimaryMarker as HTMLElement)

    expect(screen.getByLabelText('Detalle de estación')).toBeInTheDocument()
    expect(screen.getAllByText('Punto de muestra La Plana').length).toBeGreaterThan(1)
    expect(screen.getByText('Parada principal')).toBeInTheDocument()
    expect(screen.getByText('180 kW')).toBeInTheDocument()
    expect(screen.getByText('2/5 disponibles')).toBeInTheDocument()
    expect(screen.getAllByText('CCS2').length).toBeGreaterThan(0)
  })

  it('hides station prices marked as estimated', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'station',
            type: 'StationPreviewCard',
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
    expect(screen.getByText('0.1 €/kWh')).toBeInTheDocument()
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
            type: 'StationPreviewCard',
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

    expect(screen.getByText('Servicios indicados')).toBeInTheDocument()
    expect(screen.getAllByText('Restaurante').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Cafetería').length).toBeGreaterThan(0)
    expect(screen.getByText('+3 más')).toBeInTheDocument()
    expect(screen.getByText('400 kW')).toBeInTheDocument()
    expect(screen.getByText('4.8 km')).toBeInTheDocument()
    expect(screen.getByText('11 min')).toBeInTheDocument()
    expect(screen.getByText('Servicios')).toBeInTheDocument()
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
    expect(screen.queryByText('Nivel: medio')).not.toBeInTheDocument()
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
            props: { title: 'Ajusta la búsqueda', chips: [longChip] },
          },
        ]}
      />,
    )

    expect(screen.getByText('Ajusta la búsqueda')).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Ajusta la búsqueda' })).toBeInTheDocument()
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

  it('keeps secondary action buttons compact under a primary decision', () => {
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
                  label: 'Confirmar esta parada',
                  priority: 'primary',
                  event: { name: 'confirm_stop' },
                },
                {
                  label: 'Buscar otra cercana',
                  event: { name: 'find_alternative_stop' },
                },
              ],
            },
          },
        ]}
      />,
    )

    expect(screen.getByRole('button', { name: 'Confirmar esta parada' })).toHaveClass('w-full', 'font-bold')
    expect(screen.getByRole('button', { name: 'Buscar otra cercana' })).toHaveClass('w-auto', 'text-body')
    expect(screen.getByRole('button', { name: 'Buscar otra cercana' })).not.toHaveClass('border')
    expect(screen.getByRole('button', { name: 'Buscar otra cercana' })).not.toHaveClass('w-full')
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

    expect(screen.getByText(/también puedes escribir ciudad/i)).toBeInTheDocument()
    expect(screen.getByText(/las coordenadas sirven si ya las tienes/i)).toBeInTheDocument()
    expect(screen.queryByText('latitud')).not.toBeInTheDocument()
    expect(screen.queryByText('longitud')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Usar mi ubicación' })).toHaveClass('w-full', 'font-semibold')
    expect(screen.getByRole('button', { name: 'Escribir ubicación' })).toHaveClass('w-auto', 'text-body')
    expect(screen.getByRole('button', { name: 'Escribir ubicación' })).not.toHaveClass('border')

    fireEvent.click(screen.getByRole('button', { name: 'Usar mi ubicación' }))

    expect(getCurrentPosition).toHaveBeenCalledWith(
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ maximumAge: 60000, timeout: 10000 }),
    )
    expect(onPositionSubmit).toHaveBeenCalledWith('Estoy en 37.880000, -4.780000')
  })
})
