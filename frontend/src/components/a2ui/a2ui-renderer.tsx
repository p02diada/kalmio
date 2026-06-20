import {
  AlertTriangle,
  BatteryCharging,
  Bot,
  CircleHelp,
  Euro,
  Maximize2,
  MapPinned,
  MessageCircle,
  Navigation,
  Route,
} from 'lucide-react'
import { Component, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import type { Map as MapLibreMap, Marker as MapLibreMarker, StyleSpecification } from 'maplibre-gl'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import type { A2UIBlock } from '@/lib/a2ui/types'
import { cn } from '@/lib/utils'

type RecordList = Array<Record<string, unknown>>
type CoordinateTuple = [number, number]
type LineStringGeometry = { type: 'LineString'; coordinates: CoordinateTuple[] }
type RouteMapPoint = {
  id: string
  label: string
  lat: number
  lon: number
  kind: 'origin' | 'destination' | 'primary' | 'station'
}
type RouteMapData = {
  originLabel: string
  destinationLabel: string
  primaryLabel: string
  routeGeometry: LineStringGeometry | null
  points: RouteMapPoint[]
  stationPoints: RouteMapPoint[]
  corridorRadiusKm: number | null
  geometryPrecision: 'provider' | 'schematic' | 'unknown'
  source: string
}
type A2UIRendererActions = {
  onChipClick?: (value: string) => void
  onActionEvent?: (name: string, context?: Record<string, unknown>, sourceComponentId?: string) => void
  onPositionSubmit?: (value: string) => void
  onManualPositionRequest?: () => void
}

export function A2UIRenderer({
  blocks,
  onChipClick,
  onActionEvent,
  onPositionSubmit,
  onManualPositionRequest,
}: {
  blocks: A2UIBlock[]
} & A2UIRendererActions) {
  const actions = { onChipClick, onActionEvent, onPositionSubmit, onManualPositionRequest }

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-3">
      {blocks.map((block) => (
        <A2UIBoundary key={block.id} block={block} actions={actions} />
      ))}
    </div>
  )
}

function A2UIBoundary({ block, actions }: { block: A2UIBlock; actions: A2UIRendererActions }) {
  return (
    <BlockErrorBoundary type={block.type}>
      <A2UIBlockView block={block} actions={actions} />
    </BlockErrorBoundary>
  )
}

class BlockErrorBoundary extends Component<
  { children: ReactNode; type: string },
  { hasError: boolean }
> {
  state = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return <ErrorFallbackCard type={this.props.type} message="Este bloque no se pudo renderizar." />
    }

    return this.props.children
  }
}

function A2UIBlockView({ block, actions }: { block: A2UIBlock; actions: A2UIRendererActions }) {
  switch (block.type) {
    case 'AssistantMessage':
      return <MessageCard icon={Bot} tone="assistant" text={text(block.props.text)} />
    case 'UserMessage':
      return <MessageCard icon={MessageCircle} tone="route" text={text(block.props.text)} align="right" />
    case 'TripSummaryCard':
      return <TripSummaryCard block={block} />
    case 'RouteSummaryCard':
      return (
        <MetricCard
          icon={Navigation}
          title="Ruta estimada"
          tone="route"
          rows={[
            ['Distancia', metric(block.props.distanceKm, 'km')],
            ['Duración', duration(block.props.durationText, block.props.durationMin)],
            ['Energía', metric(block.props.energyKwh, 'kWh', { zeroUnknown: true })],
            ['Llegada', percent(block.props.arrivalBattery, { zeroUnknown: true })],
          ]}
        />
      )
    case 'StationDetailCard':
      return <StationDetailCard block={block} />
    case 'StationList':
      return <ListCard title={text(block.props.title, 'Estaciones cercanas')} items={list(block.props.stations)} itemKind="station" />
    case 'RiskExplanationCard':
      return <RiskBand level={text(block.props.level, 'medio')} body={text(block.props.text)} />
    case 'CostComparisonCard':
      return <CostComparisonCard block={block} />
    case 'MapPreviewCard':
      return <MapPreviewCard block={block} />
    case 'ActionButtons':
      return (
        <ActionButtons
          actions={list(block.props.actions)}
          sourceComponentId={block.id}
          onActionEvent={actions.onActionEvent ?? actions.onChipClick}
        />
      )
    case 'ClarifyingQuestionCard':
      return (
        <Card className="border-border bg-muted">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <CircleHelp className="size-4 text-assistant" aria-hidden="true" />
              Falta un dato
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm leading-6">{text(block.props.question)}</p>
            <div className="flex flex-wrap gap-2">
              {strings(block.props.fields).map((field) => (
                <Badge key={field} variant="secondary">
                  {field}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )
    case 'PositionRequestCard':
      return (
        <PositionRequestCard
          block={block}
          onPositionSubmit={actions.onPositionSubmit ?? actions.onChipClick}
          onManualPositionRequest={actions.onManualPositionRequest}
        />
      )
    case 'PlaceDetailCard':
      return <PlaceDetailCard block={block} />
    case 'PreferenceChips':
      return (
        <div className="flex min-w-0 max-w-full flex-wrap gap-2">
          {strings(block.props.chips).map((chip) => (
            <Button
              key={chip}
              type="button"
              variant="outline"
              size="sm"
              className="h-auto min-h-10 max-w-full min-w-0 whitespace-normal break-words px-3 py-2 text-left leading-5"
              onClick={() => actions.onChipClick?.(chip)}
            >
              {chip}
            </Button>
          ))}
        </div>
      )
    case 'ErrorFallbackCard':
      return <ErrorFallbackCard type={text(block.props.originalType)} message={text(block.props.message)} />
    default:
      return <ErrorFallbackCard type={block.type} message="Componente A2UI desconocido." />
  }
}

function PositionRequestCard({
  block,
  onPositionSubmit,
  onManualPositionRequest,
}: {
  block: A2UIBlock
  onPositionSubmit?: (value: string) => void
  onManualPositionRequest?: () => void
}) {
  const [status, setStatus] = useState<'idle' | 'pending' | 'unsupported' | 'failed' | 'manual'>('idle')
  const manualFields = strings(block.props.manualFields)

  const requestLocation = () => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setStatus('unsupported')
      return
    }

    setStatus('pending')
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setStatus('idle')
        onPositionSubmit?.(
          `Estoy en ${position.coords.latitude.toFixed(6)}, ${position.coords.longitude.toFixed(6)}`,
        )
      },
      () => {
        setStatus('failed')
      },
      {
        enableHighAccuracy: false,
        maximumAge: 60000,
        timeout: 10000,
      },
    )
  }

  const statusMessage = {
    idle: '',
    pending: 'Pidiendo permiso de ubicación...',
    unsupported: 'Este navegador no permite compartir ubicación aquí. Escribe ciudad o coordenadas.',
    failed: 'No pude acceder a tu ubicación. Puedes escribir ciudad o coordenadas.',
    manual: 'Escribe una ciudad o coordenadas en el mensaje para continuar.',
  }[status]

  return (
    <Card className="border-assistant bg-muted">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MapPinned className="size-4 text-assistant" aria-hidden="true" />
          {text(block.props.title)}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm leading-6 text-body">{text(block.props.body)}</p>
        {manualFields.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {manualFields.map((field) => (
              <Badge key={field} variant="secondary">
                {field}
              </Badge>
            ))}
          </div>
        ) : null}
        <div className="grid gap-2 sm:grid-cols-2">
          <Button type="button" className="h-auto min-h-11 w-full whitespace-normal font-semibold leading-5" onClick={requestLocation} disabled={status === 'pending'}>
            <Navigation className="size-4" aria-hidden="true" />
            {status === 'pending' ? 'Solicitando...' : 'Usar mi ubicación'}
          </Button>
          <Button
            type="button"
            variant="outline"
            className="h-auto min-h-11 w-full whitespace-normal leading-5"
            onClick={() => {
              setStatus('manual')
              onManualPositionRequest?.()
            }}
          >
            Escribir ubicación
          </Button>
        </div>
        {statusMessage ? <p className="text-xs leading-5 text-muted-foreground">{statusMessage}</p> : null}
      </CardContent>
    </Card>
  )
}

function PlaceDetailCard({ block }: { block: A2UIBlock }) {
  const needsConfirmation = bool(block.props.needsConfirmation)
  const precision = text(block.props.precision, 'approximate') === 'exact' ? 'Precisa' : 'Aproximada'
  const coordinates = coordinatePair(block.props.lat, block.props.lon)

  return (
    <Card className="border-route-soft bg-muted">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <span className="grid size-7 place-items-center rounded-md bg-surface">
            <MapPinned className="size-4 text-route" aria-hidden="true" />
          </span>
          Lugar resuelto
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-base font-semibold tracking-tight">{text(block.props.label, 'Lugar indicado')}</span>
          <span className="text-sm leading-6 text-body">{text(block.props.context, 'Lugar usado para la búsqueda.')}</span>
        </div>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <span className="block text-caption font-medium text-muted-foreground">Precisión</span>
            <span className="block text-compact font-semibold tracking-tight">{precision}</span>
          </div>
          <div>
            <span className="block text-caption font-medium text-muted-foreground">Coordenadas</span>
            <span className="block truncate text-compact font-semibold tracking-tight">{coordinates}</span>
          </div>
        </div>
        {needsConfirmation ? (
          <Badge variant="secondary" className="w-fit">
            Confirma el lugar final
          </Badge>
        ) : null}
      </CardContent>
    </Card>
  )
}

function MessageCard({
  icon: Icon,
  tone,
  text: value,
  align = 'left',
}: {
  icon: typeof Bot
  tone: 'assistant' | 'route'
  text: string
  align?: 'left' | 'right'
}) {
  const isUser = align === 'right'

  return (
    <div className={isUser ? 'flex justify-end' : 'flex items-start gap-2'}>
      {!isUser ? (
        <span className="mt-1 grid size-7 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground">
          <Icon className="size-3.5" aria-hidden="true" />
        </span>
      ) : null}
      <div
        className={
          isUser
            ? 'a2ui-message a2ui-message-user'
            : 'a2ui-message a2ui-message-assistant'
        }
      >
        <span className={isUser ? 'mb-1 flex items-center gap-2 text-caption font-medium text-primary-foreground/70' : 'mb-1 flex items-center gap-2 text-caption font-medium text-muted-foreground'}>
          {isUser ? <Icon className={`size-3.5 ${tone === 'assistant' ? 'text-assistant' : 'text-route'}`} aria-hidden="true" /> : null}
          {isUser ? 'Usuario' : 'Kalmio'}
        </span>
        {value}
      </div>
    </div>
  )
}

function TripSummaryCard({ block }: { block: A2UIBlock }) {
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="flex items-center gap-2 text-compact font-semibold tracking-tight text-route">
          <Route className="size-4" aria-hidden="true" />
          Resumen de la ruta
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <span>{text(block.props.origin)}</span>
          <span className="text-muted-foreground" aria-hidden="true">→</span>
          <span>{text(block.props.destination)}</span>
        </div>
        <MetricGrid
          rows={[
            ['Batería', percentOrUnknown(block.props.battery)],
            ['Mínimo al llegar', percent(block.props.arrivalReservePercent)],
            ['Tipo', 'Conservadora'],
          ]}
        />
      </CardContent>
    </Card>
  )
}

function MetricCard({
  icon: Icon,
  title,
  rows,
  tone,
  note,
}: {
  icon: typeof Route
  title: string
  rows: Array<[string, string]>
  tone: 'primary' | 'warning' | 'route' | 'assistant'
  note?: string
}) {
  const toneClass = {
    primary: 'text-primary',
    warning: 'text-warning',
    route: 'text-route',
    assistant: 'text-assistant',
  }[tone]

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <span className="grid size-7 place-items-center rounded-md bg-muted">
            <Icon className={`size-4 ${toneClass}`} aria-hidden="true" />
          </span>
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <MetricGrid rows={rows} />
        {note ? (
          <p className="border-t border-border pt-3 text-sm leading-6 text-body">
            {note}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function StationDetailCard({ block }: { block: A2UIBlock }) {
  const station = stationLabel(block.props) || stationTitle(block.props)
  const address = text(block.props.address, '')
  const capacity = stationCapacity(block.props)
  const connectors = connectorLabels(block.props.connectorTypes)
  const amenities = amenityLabels(block.props.amenities)
  const title = text(block.props.title, 'Estación de carga')

  return (
    <Card className="border-primary bg-primary text-primary-foreground">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-start gap-3 text-base font-semibold tracking-tight">
          <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-md bg-primary-foreground text-primary">
            <BatteryCharging className="size-4" aria-hidden="true" />
          </span>
          <span className="flex min-w-0 flex-col gap-1">
            <span className="text-caption font-medium text-primary-foreground/70">{title}</span>
            <span className="break-words">{station || 'Estación por confirmar'}</span>
            {address ? (
              <span className="truncate text-caption font-medium text-primary-foreground/70">
                {address}
              </span>
            ) : null}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <MetricGridRows
          rows={compactRows([
            ['Distancia', metric(block.props.distanceKm, 'km')],
            ['Potencia', metric(block.props.powerKw, 'kW')],
            stationPriceRow(block.props),
            capacity ? ['Capacidad', capacity] : ['Confianza', text(block.props.confidence)],
            ['Desvío', metric(block.props.detourMin, 'min')],
          ])}
          inverted
        />
        {connectors.length > 0 ? (
          <div className="border-t border-primary-foreground/20 pt-3">
            <span className="block text-caption font-medium text-primary-foreground/70">
              Conectores trazados
            </span>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {connectors.map((connector) => (
                <span
                  key={connector}
                  className="rounded-full bg-primary-foreground/10 px-2 py-1 text-caption font-semibold leading-none text-primary-foreground"
                >
                  {connector}
                </span>
              ))}
            </div>
          </div>
        ) : null}
        {amenities && amenities.length > 0 ? (
          <div className="border-t border-primary-foreground/20 pt-3">
            <span className="block text-caption font-medium text-primary-foreground/70">
              Servicios trazados
            </span>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {amenities.map((amenity) => (
                <span
                  key={amenity}
                  className="rounded-full bg-primary-foreground/10 px-2 py-1 text-caption font-semibold leading-none text-primary-foreground"
                >
                  {amenity}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function CostComparisonCard({ block }: { block: A2UIBlock }) {
  const tariff = pricePerKwhValue(block.props.pricePerKwhEur, block.props.currency)
  if (bool(block.props.priceIsEstimated) || !tariff) {
    return <ErrorFallbackCard type={block.type} message="No hay tarifas trazadas para comparar." />
  }

  return (
    <MetricCard
      icon={Euro}
      title={text(block.props.best)}
      tone="primary"
      rows={compactRows([
        ['Tarifa', tariff],
        pricePerKwhValue(block.props.comparedWithPricePerKwhEur, block.props.currency)
          ? ['Comparada con', pricePerKwh(block.props.comparedWithPricePerKwhEur, block.props.currency)]
          : null,
        isKnownNumber(block.props.savingPerKwhEur) ? ['Ahorro/kWh', metric(block.props.savingPerKwhEur, 'EUR')] : null,
      ])}
      note={priceNote(block.props)}
    />
  )
}

function MetricGrid({ rows }: { rows: Array<[string, string]> }) {
  return <MetricGridRows rows={rows} />
}

function MetricGridRows({ rows, inverted = false }: { rows: Array<[string, string]>; inverted?: boolean }) {
  return (
    <div className="grid grid-cols-3 gap-2 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <span className={cn('block truncate text-caption font-medium', inverted ? 'text-primary-foreground/70' : 'text-muted-foreground')}>{label}</span>
          <span className={cn('block break-words text-compact font-semibold tracking-tight', inverted ? 'text-primary-foreground' : 'text-foreground')}>{value}</span>
        </div>
      ))}
    </div>
  )
}

function ListCard({
  title,
  items,
  itemKind = 'default',
}: {
  title: string
  items: RecordList
  itemKind?: 'default' | 'station'
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold tracking-tight">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col divide-y divide-border">
        {items.map((item, index) => (
          <div key={`${itemKind === 'station' ? stationTitle(item, 'Estación') : text(item.name)}-${index}`} className="flex items-center gap-3 py-2.5 text-sm first:pt-0 last:pb-0">
            <span className="grid size-7 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-muted-foreground">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold tracking-tight">
                {itemKind === 'station' ? stationTitle(item, 'Estación') : text(item.name)}
              </div>
              <div className="text-muted-foreground">
                {itemKind === 'station' ? stationDetails(item) : routeDetails(item)}
              </div>
            </div>
          </div>
        ))}
        </div>
      </CardContent>
    </Card>
  )
}

function RiskBand({ level, body }: { level: string; body: string }) {
  const severity = level.toLowerCase()
  const high = severity.includes('alto') || severity.includes('alta')
  const low = severity.includes('bajo') || severity.includes('baja') || severity.includes('info')
  return (
    <Alert className={cn('border-warning bg-warning-soft text-foreground', high && 'border-error bg-error-soft')}>
      <AlertTriangle aria-hidden="true" />
      <AlertTitle className="text-sm font-semibold">
        {high ? 'Riesgo alto' : low ? 'Aviso de datos' : 'Datos a confirmar'}
      </AlertTitle>
      <AlertDescription className="text-sm leading-6 text-body">
        {body || 'Hay incertidumbre que debes confirmar antes de depender de este resultado.'}
      </AlertDescription>
    </Alert>
  )
}

function MapPreviewCard({ block }: { block: A2UIBlock }) {
  const mapData = useMemo(() => routeMapData(block.props), [block.props])
  const stationCount = mapData.stationPoints.length
  const geometryLabel = mapData.geometryPrecision === 'provider' ? 'Ruta real' : 'Vista esquemática'

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="flex min-w-0 items-center gap-2 text-base">
            <MapPinned className="size-4 shrink-0 text-route" aria-hidden="true" />
            <span className="min-w-0 truncate">Mapa de ruta</span>
          </CardTitle>
          <Dialog>
            <DialogTrigger asChild>
              <Button type="button" variant="outline" size="sm" className="h-8 shrink-0 px-2" aria-label="Expandir mapa">
                <Maximize2 className="size-4" aria-hidden="true" />
              </Button>
            </DialogTrigger>
            <DialogContent className="max-h-[92svh] max-w-[min(68rem,calc(100%-1rem))] overflow-hidden p-0">
              <DialogHeader className="border-b border-border px-4 pb-3 pt-4 sm:px-5">
                <DialogTitle>Mapa de ruta</DialogTitle>
                <DialogDescription>
                  {compactParts([
                    `${mapData.originLabel} → ${mapData.destinationLabel}`,
                    stationCount > 0 ? `${stationCount} estaciones en el corredor` : '',
                  ]).join(' · ')}
                </DialogDescription>
              </DialogHeader>
              <div className="grid max-h-[calc(92svh-5rem)] min-h-0 gap-0 overflow-auto md:grid-cols-[minmax(0,1fr)_18rem]">
                <RouteMapCanvas data={mapData} variant="expanded" />
                <RouteMapStationPanel data={mapData} />
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <RouteMapCanvas data={mapData} variant="compact" />
        <div className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
          <span className="truncate">{mapData.originLabel}</span>
          <span className="truncate text-center">{mapData.primaryLabel || geometryLabel}</span>
          <span className="truncate text-right">{mapData.destinationLabel}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Badge variant="secondary">{geometryLabel}</Badge>
          {stationCount > 0 ? <Badge variant="secondary">{stationCount} estaciones</Badge> : null}
          {mapData.corridorRadiusKm !== null ? <Badge variant="secondary">Corredor {formatNumber(mapData.corridorRadiusKm)} km</Badge> : null}
        </div>
      </CardContent>
    </Card>
  )
}

function RouteMapCanvas({ data, variant }: { data: RouteMapData; variant: 'compact' | 'expanded' }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const [status, setStatus] = useState<'idle' | 'static' | 'failed'>('idle')
  const dataKey = useMemo(() => JSON.stringify({
    routeGeometry: data.routeGeometry,
    points: data.points.map((point) => [point.id, point.lat, point.lon, point.kind]),
  }), [data])

  useEffect(() => {
    const container = containerRef.current
    if (!container || !data.routeGeometry || !canUseWebGl()) {
      setStatus('static')
      return
    }

    let disposed = false
    const markers: MapLibreMarker[] = []

    async function setupMap() {
      try {
        const maplibregl = await import('maplibre-gl')
        if (disposed || !containerRef.current) {
          return
        }
        const map = new maplibregl.Map({
          container: containerRef.current,
          style: mapLibreStyle(),
          center: routeCenter(data),
          zoom: 6,
          attributionControl: Boolean(mapStyleUrl()),
          interactive: true,
        })
        mapRef.current = map
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
        map.once('load', () => {
          if (disposed) {
            return
          }
          map.addSource('route', {
            type: 'geojson',
            data: {
              type: 'Feature',
              properties: {},
              geometry: data.routeGeometry,
            },
          })
          map.addLayer({
            id: 'route-shadow',
            type: 'line',
            source: 'route',
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': '#ffffff', 'line-width': 8, 'line-opacity': 0.92 },
          })
          map.addLayer({
            id: 'route-line',
            type: 'line',
            source: 'route',
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': '#146c5f', 'line-width': 4 },
          })
          for (const point of data.points) {
            const marker = new maplibregl.Marker({ element: mapMarkerElement(point), anchor: 'center' })
              .setLngLat([point.lon, point.lat])
              .addTo(map)
            markers.push(marker)
          }
          const bounds = routeBounds(data)
          if (bounds) {
            map.fitBounds(bounds, {
              padding: variant === 'expanded' ? 72 : 34,
              maxZoom: variant === 'expanded' ? 11 : 8,
              duration: 0,
            })
          }
          map.resize()
        })
        map.on('error', () => setStatus('failed'))
      } catch {
        if (!disposed) {
          setStatus('failed')
        }
      }
    }

    setStatus('idle')
    void setupMap()

    return () => {
      disposed = true
      markers.forEach((marker) => marker.remove())
      mapRef.current?.remove()
      mapRef.current = null
    }
  }, [data, dataKey, variant])

  return (
    <div className={cn('a2ui-map-shell', variant === 'expanded' && 'a2ui-map-shell-expanded')}>
      <div ref={containerRef} className={cn('a2ui-maplibre-canvas', status !== 'idle' && 'opacity-0')} aria-label="Mapa interactivo de ruta" />
      {status !== 'idle' ? <StaticRouteMap data={data} /> : null}
      {status === 'failed' ? (
        <span className="absolute left-3 top-3 rounded-md bg-surface px-2 py-1 text-xs font-medium text-muted-foreground shadow-sm">
          Vista estática
        </span>
      ) : null}
    </div>
  )
}

function StaticRouteMap({ data }: { data: RouteMapData }) {
  const geometry = data.routeGeometry ?? schematicGeometry(data)
  const projected = projectedRoute(geometry, data.points)
  return (
    <svg className="a2ui-static-map" viewBox="0 0 640 280" role="img" aria-label="Vista de ruta">
      <rect width="640" height="280" rx="14" className="fill-[color-mix(in_oklch,var(--color-route-soft)_32%,var(--color-muted))]" />
      <path d={projected.path} className="fill-none stroke-white/90 stroke-[12] [stroke-linecap:round] [stroke-linejoin:round]" />
      <path d={projected.path} className="fill-none stroke-route stroke-[5] [stroke-linecap:round] [stroke-linejoin:round]" />
      {projected.points.map((point) => (
        <g key={point.id} transform={`translate(${point.x} ${point.y})`}>
          <circle r={point.kind === 'primary' ? 9 : 7} className={point.kind === 'primary' ? 'fill-warning stroke-surface stroke-[3]' : 'fill-primary stroke-surface stroke-[3]'} />
          <text x={point.kind === 'destination' ? -10 : 10} y="-10" textAnchor={point.kind === 'destination' ? 'end' : 'start'} className="fill-foreground text-[18px] font-bold">
            {point.label}
          </text>
        </g>
      ))}
    </svg>
  )
}

function RouteMapStationPanel({ data }: { data: RouteMapData }) {
  const stations = data.stationPoints
  return (
    <aside className="flex min-h-0 flex-col gap-3 border-t border-border p-4 md:border-l md:border-t-0">
      <div className="flex flex-col gap-1">
        <span className="text-sm font-semibold tracking-tight">Cargadores en ruta</span>
        <span className="text-xs leading-5 text-muted-foreground">
          {stations.length > 0 ? `${stations.length} estaciones trazadas cerca del corredor.` : 'Sin estaciones trazadas para este mapa.'}
        </span>
      </div>
      <div className="flex min-h-0 flex-col divide-y divide-border overflow-auto">
        {stations.map((station, index) => (
          <div key={station.id} className="flex gap-3 py-3 text-sm first:pt-0 last:pb-0">
            <span className={cn(
              'grid size-7 shrink-0 place-items-center rounded-full text-xs font-bold',
              station.kind === 'primary' ? 'bg-warning text-foreground' : 'bg-muted text-muted-foreground',
            )}>
              {index + 1}
            </span>
            <div className="min-w-0">
              <div className="truncate font-semibold tracking-tight">{station.label}</div>
              <div className="text-xs leading-5 text-muted-foreground">
                {station.kind === 'primary' ? 'Parada principal' : 'Alternativa del corredor'}
              </div>
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}

function routeMapData(props: Record<string, unknown>): RouteMapData {
  const routeGeometry = lineStringGeometry(props.routeGeometry)
  const primaryStation = record(props.primaryStation)
  const stations = list(props.stations)
  const origin = mapPoint(props.origin, 'origin', 'Origen')
    ?? pointFromGeometry(routeGeometry, 0, 'origin', text(props.origin, 'Origen'))
  const destination = mapPoint(props.destination, 'destination', 'Destino')
    ?? pointFromGeometry(routeGeometry, -1, 'destination', text(props.destination, 'Destino'))
  const primary = primaryStation ? stationMapPoint(primaryStation, 'primary', 0) : null
  const alternativePoints = stations
    .map((station, index) => stationMapPoint(station, 'station', index + 1))
    .filter((point): point is RouteMapPoint => point !== null)
  const stationPoints = uniqueMapPoints(compactMapPoints([primary, ...alternativePoints]))
  const points = uniqueMapPoints(compactMapPoints([origin, destination, ...stationPoints]))

  return {
    originLabel: origin?.label ?? text(props.origin, 'Origen'),
    destinationLabel: destination?.label ?? text(props.destination, 'Destino'),
    primaryLabel: primary?.label ?? text(primaryStation, ''),
    routeGeometry,
    points,
    stationPoints,
    corridorRadiusKm: knownNumber(props.corridorRadiusKm),
    geometryPrecision: routeGeometry ? geometryPrecision(props.geometryPrecision) : 'schematic',
    source: text(props.source, ''),
  }
}

function lineStringGeometry(value: unknown): LineStringGeometry | null {
  const geometry = record(value)
  if (geometry?.type !== 'LineString' || !Array.isArray(geometry.coordinates)) {
    return null
  }
  const coordinates = geometry.coordinates
    .map((coordinate) => coordinateTuple(coordinate))
    .filter((coordinate): coordinate is CoordinateTuple => coordinate !== null)
  return coordinates.length >= 2 ? { type: 'LineString', coordinates } : null
}

function coordinateTuple(value: unknown): CoordinateTuple | null {
  if (!Array.isArray(value) || value.length < 2) {
    return null
  }
  const lon = knownNumber(value[0])
  const lat = knownNumber(value[1])
  if (lat === null || lon === null || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    return null
  }
  return [lon, lat]
}

function mapPoint(value: unknown, kind: RouteMapPoint['kind'], fallback: string): RouteMapPoint | null {
  const item = record(value)
  if (!item) {
    return null
  }
  const lat = knownNumber(item.lat)
  const lon = knownNumber(item.lon)
  if (lat === null || lon === null) {
    return null
  }
  return {
    id: kind,
    label: text(item, fallback),
    lat,
    lon,
    kind,
  }
}

function stationMapPoint(item: Record<string, unknown>, kind: 'primary' | 'station', index: number): RouteMapPoint | null {
  const lat = knownNumber(item.lat)
  const lon = knownNumber(item.lon)
  const label = stationTitle(item, '')
  if (lat === null || lon === null || !label) {
    return null
  }
  return {
    id: `${kind}-${stationKey(label)}-${index}`,
    label,
    lat,
    lon,
    kind,
  }
}

function pointFromGeometry(
  geometry: LineStringGeometry | null,
  index: number,
  kind: 'origin' | 'destination',
  label: string,
): RouteMapPoint | null {
  if (!geometry) {
    return null
  }
  const coordinate = index < 0
    ? geometry.coordinates[geometry.coordinates.length + index]
    : geometry.coordinates[index]
  if (!coordinate) {
    return null
  }
  return { id: kind, label, lon: coordinate[0], lat: coordinate[1], kind }
}

function compactMapPoints(points: Array<RouteMapPoint | null>): RouteMapPoint[] {
  return points.filter((point): point is RouteMapPoint => point !== null)
}

function uniqueMapPoints(points: RouteMapPoint[]) {
  const seen = new Set<string>()
  return points.filter((point) => {
    const key = `${stationKey(point.label)}:${point.lat.toFixed(5)}:${point.lon.toFixed(5)}`
    if (seen.has(key)) {
      return false
    }
    seen.add(key)
    return true
  })
}

function geometryPrecision(value: unknown): RouteMapData['geometryPrecision'] {
  return value === 'provider' || value === 'unknown' || value === 'schematic' ? value : 'unknown'
}

function mapStyleUrl() {
  return text(import.meta.env.VITE_KALMIO_MAP_STYLE_URL, '').trim()
}

function mapLibreStyle(): string | StyleSpecification {
  const styleUrl = mapStyleUrl()
  if (styleUrl) {
    return styleUrl
  }
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: 'background',
        type: 'background',
        paint: { 'background-color': '#eef4f1' },
      },
    ],
  }
}

function routeCenter(data: RouteMapData): CoordinateTuple {
  const coordinates = allRouteCoordinates(data)
  if (coordinates.length === 0) {
    return [-3.7, 40.4]
  }
  const totals = coordinates.reduce(
    (sum, coordinate) => ({ lon: sum.lon + coordinate[0], lat: sum.lat + coordinate[1] }),
    { lon: 0, lat: 0 },
  )
  return [totals.lon / coordinates.length, totals.lat / coordinates.length]
}

function routeBounds(data: RouteMapData): [CoordinateTuple, CoordinateTuple] | null {
  const coordinates = allRouteCoordinates(data)
  if (coordinates.length === 0) {
    return null
  }
  const bounds = coordinates.reduce(
    (current, coordinate) => ({
      minLon: Math.min(current.minLon, coordinate[0]),
      minLat: Math.min(current.minLat, coordinate[1]),
      maxLon: Math.max(current.maxLon, coordinate[0]),
      maxLat: Math.max(current.maxLat, coordinate[1]),
    }),
    { minLon: coordinates[0][0], minLat: coordinates[0][1], maxLon: coordinates[0][0], maxLat: coordinates[0][1] },
  )
  return [[bounds.minLon, bounds.minLat], [bounds.maxLon, bounds.maxLat]]
}

function allRouteCoordinates(data: RouteMapData): CoordinateTuple[] {
  return [
    ...(data.routeGeometry?.coordinates ?? []),
    ...data.points.map((point): CoordinateTuple => [point.lon, point.lat]),
  ]
}

function canUseWebGl() {
  if (typeof document === 'undefined') {
    return false
  }
  try {
    const canvas = document.createElement('canvas')
    return Boolean(canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
  } catch {
    return false
  }
}

function mapMarkerElement(point: RouteMapPoint) {
  const element = document.createElement('div')
  element.className = `a2ui-map-marker a2ui-map-marker-${point.kind}`
  element.title = point.label
  const dot = document.createElement('span')
  dot.className = 'a2ui-map-marker-dot'
  const label = document.createElement('span')
  label.className = 'a2ui-map-marker-label'
  label.textContent = point.label
  element.append(dot, label)
  return element
}

function schematicGeometry(data: RouteMapData): LineStringGeometry {
  const coordinates = data.points.map((point): CoordinateTuple => [point.lon, point.lat])
  if (coordinates.length >= 2) {
    return { type: 'LineString', coordinates }
  }
  return { type: 'LineString', coordinates: [[-4.8, 37.9], [-0.4, 39.5]] }
}

function projectedRoute(geometry: LineStringGeometry, points: RouteMapPoint[]) {
  const width = 640
  const height = 280
  const padding = 38
  const coordinates = [...geometry.coordinates, ...points.map((point): CoordinateTuple => [point.lon, point.lat])]
  const lons = coordinates.map((coordinate) => coordinate[0])
  const lats = coordinates.map((coordinate) => coordinate[1])
  const minLon = Math.min(...lons)
  const maxLon = Math.max(...lons)
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const lonRange = Math.max(maxLon - minLon, 0.001)
  const latRange = Math.max(maxLat - minLat, 0.001)
  const project = ([lon, lat]: CoordinateTuple) => ({
    x: padding + ((lon - minLon) / lonRange) * (width - padding * 2),
    y: height - padding - ((lat - minLat) / latRange) * (height - padding * 2),
  })
  const routePoints = geometry.coordinates.map(project)
  return {
    path: routePoints.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' '),
    points: points.map((point) => ({ ...point, ...project([point.lon, point.lat]) })),
  }
}

function stationKey(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-')
}

function ActionButtons({
  actions,
  sourceComponentId,
  onActionEvent,
}: {
  actions: RecordList
  sourceComponentId: string
  onActionEvent?: (name: string, context?: Record<string, unknown>, sourceComponentId?: string) => void
}) {
  return (
    <div className="grid min-w-0 max-w-full gap-2 sm:grid-cols-2">
      {actions.map((action, index) => {
        const target = actionTarget(action)
        const isDisabled = bool(action.disabled) || target === null
        const isPrimary = text(action.priority, '') === 'primary' || (index === 0 && !isDisabled && !text(action.priority, ''))

        return (
          <div key={`${text(action.label)}-${index}`} className="flex min-w-0 flex-col gap-1">
            <Button
              type="button"
              disabled={isDisabled}
              variant={isPrimary ? 'default' : 'outline'}
              className={cn(
                'h-auto min-h-11 w-full min-w-0 whitespace-normal break-words px-3 py-2 text-left leading-5',
                isPrimary && 'font-bold',
              )}
              onClick={() => handleAction(target, onActionEvent, sourceComponentId)}
            >
              {text(action.label)}
            </Button>
            {(isDisabled && text(action.reason, '')) || (!bool(action.disabled) && target === null) ? (
              <p className="max-w-full text-xs leading-5 text-muted-foreground">
                {text(action.reason, '') || 'Esta acción no está disponible en este contexto.'}
              </p>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

type ActionTarget =
  | { kind: 'functionCall'; url: string }
  | { kind: 'event'; name: string; context?: Record<string, unknown> }

function actionTarget(action: Record<string, unknown>): ActionTarget | null {
  const functionCall = record(action.functionCall)
  const functionArgs = record(functionCall?.args)
  const functionUrl = text(functionArgs?.url, '').trim()
  if (functionCall?.call === 'openUrl' && safeHttpUrl(functionUrl)) {
    return { kind: 'functionCall', url: functionUrl }
  }

  const event = record(action.event)
  const eventName = text(event?.name, '')
  if (eventName) {
    return { kind: 'event', name: eventName, context: record(event?.context) ?? undefined }
  }

  return null
}

function handleAction(
  target: ActionTarget | null,
  onActionEvent?: (name: string, context?: Record<string, unknown>, sourceComponentId?: string) => void,
  sourceComponentId?: string,
) {
  if (!target) {
    return
  }
  if (target.kind === 'functionCall') {
    openAction(target.url)
    return
  }
  onActionEvent?.(target.name, target.context, sourceComponentId)
}

function openAction(url: string) {
  if (!url) {
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

function safeHttpUrl(value: string) {
  const normalized = value.trim().toLowerCase()
  return normalized.startsWith('https://') || normalized.startsWith('http://')
}

function ErrorFallbackCard({ type, message }: { type: string; message: string }) {
  return (
    <Card className="border-border bg-muted">
      <CardHeader>
        <CardTitle className="text-base">No puedo mostrar una parte de la respuesta</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm text-muted-foreground">
        <p>{safeFallbackMessage(message)}</p>
        <details className="text-xs">
          <summary className="cursor-pointer font-medium text-body">Detalle para soporte</summary>
          <code className="mt-1 block break-words">{type}</code>
        </details>
      </CardContent>
    </Card>
  )
}

function text(value: unknown, fallback = 'No disponible') {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) {
      return fallback
    }
    const labelMatch = trimmed.match(/['"]label['"]\s*:\s*['"]([^'"]+)/)
    return labelMatch?.[1] ?? trimmed
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return formatNumber(value)
  }
  if (typeof value === 'boolean') {
    return value ? 'Sí' : 'No'
  }
  if (isRecord(value)) {
    return text(value.label ?? value.name ?? value.title ?? value.text ?? value.value, fallback)
  }
  return fallback
}

function stationTitle(value: Record<string, unknown>, fallback = 'Estación de carga') {
  return text(
    value.stationName ?? value.name,
    fallback,
  )
}

function stationLabel(value: Record<string, unknown>) {
  return text(value.stationName ?? value.name, '')
}

function stationDetails(item: Record<string, unknown>) {
  const title = stationTitle(item, 'Estación')
  const station = stationLabel(item)
  const stationDetail = station && station !== title ? `Estación: ${station}` : ''
  const amenities = amenitySummary(item.amenities)
  const capacity = stationCapacity(item)
  const connectors = connectorLabels(item.connectorTypes)
  const metricParts = [
    isKnownNumber(item.powerKw) ? metric(item.powerKw, 'kW') : '',
    stationPriceDetail(item),
    isKnownNumber(item.distanceKm) ? metric(item.distanceKm, 'km') : '',
    isKnownNumber(item.detourMin) ? `Desvío ${metric(item.detourMin, 'min')}` : '',
    capacity ? `Capacidad trazada: ${capacity}` : '',
    connectors.length > 0 ? `Conectores trazados: ${connectors.join(', ')}` : '',
  ].filter(Boolean)
  const metrics = isKnownNumber(item.powerKw)
    ? metricParts.join(' · ')
    : metric(item.deltaMin, 'min de diferencia')

  return compactParts([stationDetail, metrics, amenities]).join(' · ')
}

function stationCapacity(item: Record<string, unknown>) {
  const evses = knownNumber(item.availableEvses)
  if (evses !== null) {
    return `${formatNumber(evses)} EVSEs`
  }
  const connectors = knownNumber(item.connectorCount)
  if (connectors !== null) {
    return `${formatNumber(connectors)} conectores`
  }
  return ''
}

function connectorLabels(value: unknown) {
  return strings(value).map((item) => item.toUpperCase())
}

function routeDetails(item: Record<string, unknown>) {
  return isKnownNumber(item.powerKw)
    ? `${metric(item.powerKw, 'kW')}${isKnownNumber(item.distanceKm) ? ` · ${metric(item.distanceKm, 'km')}` : ''}`
    : metric(item.deltaMin, 'min de diferencia')
}

function pricePerKwh(value: unknown, currency: unknown = 'EUR') {
  return pricePerKwhValue(value, currency) ?? 'No disponible'
}

function pricePerKwhValue(value: unknown, currency: unknown = 'EUR') {
  const number = knownNumber(value)
  if (number === null) {
    return null
  }
  const symbol = text(currency, 'EUR').toUpperCase() === 'EUR' ? '€' : text(currency, 'EUR')
  return `${formatPrice(number)} ${symbol}/kWh`
}

function stationPrice(item: Record<string, unknown>) {
  if (bool(item.priceIsEstimated)) {
    return 'No disponible'
  }
  const value = pricePerKwh(item.pricePerKwhEur, item.currency)
  return value
}

function stationPriceRow(item: Record<string, unknown>): [string, string] | null {
  const value = stationPrice(item)
  return value === 'No disponible' ? null : ['Precio', value]
}

function stationPriceDetail(item: Record<string, unknown>) {
  const value = stationPrice(item)
  return value === 'No disponible' ? '' : `Precio ${value}`
}

function priceNote(props: Record<string, unknown>) {
  const comparedWith = text(props.comparedWith, '')
  return compactParts([
    comparedWith ? `Comparado con ${comparedWith}.` : '',
  ]).join(' ')
}

function compactRows(rows: Array<[string, string] | null>): Array<[string, string]> {
  return rows.filter((row): row is [string, string] => row !== null && row[1].trim().length > 0)
}

function compactParts(parts: string[]) {
  return parts.map((part) => part.trim()).filter(Boolean)
}

function percentOrUnknown(value: unknown) {
  const number = knownNumber(value)
  return number === null ? 'No indicada' : `${formatNumber(number)}%`
}

function bool(value: unknown) {
  return value === true
}

function list(value: unknown): RecordList {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item)) : []
}

function record(value: unknown): Record<string, unknown> | null {
  return isRecord(value) ? value : null
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => text(item, '')).filter((item) => item.length > 0)
    : []
}

const AMENITY_LABELS: Record<string, string> = {
  BATHROOM: 'Baños',
  BUS_STOP: 'Bus',
  CAFE: 'Cafetería',
  CARPOOL_PARKING: 'Parking compartido',
  FUEL_STATION: 'Gasolinera',
  HOTEL: 'Hotel',
  MALL: 'Centro comercial',
  NATURE: 'Zona verde',
  PARKING_LOT: 'Parking',
  RECREATION_AREA: 'Zona de descanso',
  RESTAURANT: 'Restaurante',
  SPORT: 'Zona deportiva',
  SUPERMARKET: 'Supermercado',
  TAXI_STAND: 'Taxi',
  TOILETS: 'Baños',
  WIFI: 'Wifi',
}

const AMENITY_PRIORITY = [
  'RESTAURANT',
  'CAFE',
  'BATHROOM',
  'TOILETS',
  'SUPERMARKET',
  'MALL',
  'RECREATION_AREA',
  'HOTEL',
  'PARKING_LOT',
  'FUEL_STATION',
  'WIFI',
  'NATURE',
]

function amenityLabels(value: unknown, limit = 4) {
  const unique = Array.from(new Set(strings(value).map(normalizeAmenityCode).filter(Boolean)))
  unique.sort((left, right) => amenityPriority(left) - amenityPriority(right))
  const labels = unique.slice(0, limit).map((code) => AMENITY_LABELS[code] ?? humanizeAmenity(code))
  const hidden = unique.length - labels.length
  return hidden > 0 ? [...labels, `+${hidden} más`] : labels
}

function amenitySummary(value: unknown) {
  const labels = amenityLabels(value, 3)
  return labels.length > 0 ? `Servicios trazados: ${labels.join(', ')}` : ''
}

function normalizeAmenityCode(value: string) {
  return value.trim().toUpperCase().replace(/[\s-]+/g, '_')
}

function amenityPriority(code: string) {
  const index = AMENITY_PRIORITY.indexOf(code)
  return index === -1 ? AMENITY_PRIORITY.length : index
}

function humanizeAmenity(code: string) {
  return code
    .toLowerCase()
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function metric(value: unknown, unit: string, options: { zeroUnknown?: boolean } = {}) {
  const number = knownNumber(value, options)
  if (number === null) {
    return 'No calculado'
  }
  return `${formatNumber(number)} ${unit}`
}

function percent(value: unknown, options: { zeroUnknown?: boolean } = {}) {
  const number = knownNumber(value, options)
  if (number === null) {
    return 'No calculado'
  }
  return `${formatNumber(number)}%`
}

function duration(durationText: unknown, durationMin: unknown) {
  const provided = text(durationText, '')
  if (provided) {
    return provided
  }
  const minutes = knownNumber(durationMin)
  if (minutes === null) {
    return 'No calculado'
  }
  if (minutes < 60) {
    return `${formatNumber(minutes)} min`
  }
  const rounded = Math.round(minutes)
  const hours = Math.floor(rounded / 60)
  const remaining = rounded % 60
  return remaining > 0 ? `${hours} h ${remaining} min` : `${hours} h`
}

function coordinatePair(lat: unknown, lon: unknown) {
  const latitude = knownNumber(lat)
  const longitude = knownNumber(lon)
  if (latitude === null || longitude === null) {
    return 'No disponible'
  }
  return `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`
}

function isKnownNumber(value: unknown, options: { zeroUnknown?: boolean } = {}) {
  return knownNumber(value, options) !== null
}

function knownNumber(value: unknown, options: { zeroUnknown?: boolean } = {}) {
  if (typeof value !== 'number' || !Number.isFinite(value) || (options.zeroUnknown && value === 0)) {
    return null
  }
  return value
}

function formatNumber(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, '')
}

function formatPrice(value: number) {
  return value.toFixed(2).replace(/0$/, '').replace(/\.0$/, '')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function safeFallbackMessage(message: string) {
  const normalized = message.toLowerCase()
  if (normalized.includes('a2ui') || normalized.includes('codex') || normalized.includes('json')) {
    return 'He ocultado un bloque que no venía en un formato seguro. Puedes continuar corrigiendo la petición o reintentarla.'
  }
  return message || 'He ocultado un bloque que no venía en un formato seguro.'
}
