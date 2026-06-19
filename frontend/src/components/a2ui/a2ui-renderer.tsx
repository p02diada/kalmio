import {
  AlertTriangle,
  BatteryCharging,
  Bot,
  CircleHelp,
  Euro,
  MapPinned,
  MessageCircle,
  Navigation,
  Route,
  Utensils,
} from 'lucide-react'
import { Component, type ReactNode, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import type { A2UIBlock } from '@/lib/a2ui/types'
import { cn } from '@/lib/utils'

type RecordList = Array<Record<string, unknown>>
type A2UIRendererActions = {
  onChipClick?: (value: string) => void
  onActionEvent?: (name: string, context?: Record<string, unknown>, sourceComponentId?: string) => void
  onLocationSubmit?: (value: string) => void
  onManualLocationRequest?: () => void
}

export function A2UIRenderer({
  blocks,
  onChipClick,
  onActionEvent,
  onLocationSubmit,
  onManualLocationRequest,
}: {
  blocks: A2UIBlock[]
} & A2UIRendererActions) {
  const actions = { onChipClick, onActionEvent, onLocationSubmit, onManualLocationRequest }

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
    case 'AlternativeRoutesList':
      return <ListCard title="Rutas alternativas" items={list(block.props.routes)} />
    case 'StationList':
      return <ListCard title={text(block.props.title, 'Estaciones cercanas')} items={list(block.props.stations)} itemKind="station" />
    case 'RiskExplanationCard':
      return <RiskBand level={text(block.props.level, 'medio')} body={text(block.props.text)} />
    case 'CostComparisonCard':
      return (
        <MetricCard
          icon={Euro}
          title={text(block.props.best)}
          tone="primary"
          rows={[
            ['Coste estimado', metric(block.props.estimatedCostEur, 'EUR')],
            ['Ahorro estimado', metric(block.props.savingEur, 'EUR')],
          ]}
        />
      )
    case 'DestinationChargingCard':
      return (
        <MetricCard
          icon={MapPinned}
          title="Plan al llegar"
          tone="assistant"
          rows={[
            ['Destino', text(block.props.destination)],
            ['Confirmación', bool(block.props.needsConfirmation) ? 'Necesaria' : 'No necesaria'],
          ]}
        />
      )
    case 'StayPlanningCard':
      return (
        <MetricCard
          icon={Utensils}
          title="Plan de estancia"
          tone="assistant"
          rows={[
            ['Noches', count(block.props.nights)],
            ['Ciudad', text(block.props.city)],
            ['Plan', text(block.props.recommendation)],
          ]}
        />
      )
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
    case 'LocationRequestCard':
      return (
        <LocationRequestCard
          block={block}
          onLocationSubmit={actions.onLocationSubmit ?? actions.onChipClick}
          onManualLocationRequest={actions.onManualLocationRequest}
        />
      )
    case 'LocationDetailCard':
      return <LocationDetailCard block={block} />
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

function LocationRequestCard({
  block,
  onLocationSubmit,
  onManualLocationRequest,
}: {
  block: A2UIBlock
  onLocationSubmit?: (value: string) => void
  onManualLocationRequest?: () => void
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
        onLocationSubmit?.(
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
              onManualLocationRequest?.()
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

function LocationDetailCard({ block }: { block: A2UIBlock }) {
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
          Detalle de ubicación
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-base font-semibold tracking-tight">{text(block.props.label, 'Ubicación indicada')}</span>
          <span className="text-sm leading-6 text-body">{text(block.props.context, 'Ubicación usada para la búsqueda.')}</span>
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
            Confirma acceso y ubicación final
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
            ['Reserva', percent(block.props.reserve)],
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
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MapPinned className="size-4 text-route" aria-hidden="true" />
          Vista de ruta
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="a2ui-map-canvas">
          <div className="a2ui-map-grid" />
          <div className="a2ui-route-line" />
          <div className="absolute left-7 top-24 size-4 rounded-full border-2 border-surface bg-primary" />
          <div className="absolute left-[48%] top-[47%] size-5 -translate-x-1/2 rounded-full border-2 border-surface bg-warning" />
          <div className="absolute right-9 top-14 size-4 rounded-full border-2 border-surface bg-primary" />
          <span className="absolute bottom-4 left-7 text-xs font-bold text-foreground">{text(block.props.origin)}</span>
          <span className="absolute right-6 top-7 text-xs font-bold text-foreground">{text(block.props.destination)}</span>
        </div>
        <div className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
          <span>{text(block.props.origin)}</span>
          <span className="text-center">{text(block.props.stop)}</span>
          <span className="text-right">{text(block.props.destination)}</span>
        </div>
      </CardContent>
    </Card>
  )
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

function count(value: unknown) {
  const number = knownNumber(value)
  return number === null ? 'No disponible' : formatNumber(number)
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
