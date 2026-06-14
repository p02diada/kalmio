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
  onLocationSubmit?: (value: string) => void
  onManualLocationRequest?: () => void
}

export function A2UIRenderer({
  blocks,
  onChipClick,
  onLocationSubmit,
  onManualLocationRequest,
}: {
  blocks: A2UIBlock[]
} & A2UIRendererActions) {
  const actions = { onChipClick, onLocationSubmit, onManualLocationRequest }

  return (
    <div className="flex flex-col gap-3">
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
            ['Duración', metric(block.props.durationMin, 'min')],
            ['Energía', metric(block.props.energyKwh, 'kWh', { zeroUnknown: true })],
            ['Llegada', percent(block.props.arrivalBattery, { zeroUnknown: true })],
          ]}
        />
      )
    case 'RecommendedStopCard':
      return (
        <RecommendationCard
          icon={BatteryCharging}
          title={text(block.props.name)}
          rows={[
            ['Potencia', metric(block.props.powerKw, 'kW')],
            ['Desvío', metric(block.props.detourMin, 'min')],
            ['Confianza', text(block.props.confidence)],
          ]}
        />
      )
    case 'AlternativeRoutesList':
      return <ListCard title="Rutas alternativas" items={list(block.props.routes)} />
    case 'AlternativeStopsList':
      return <ListCard title="Cargadores alternativos" items={list(block.props.stops)} />
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
    case 'UrgentChargeCard':
      return (
        <MetricCard
          icon={BatteryCharging}
          title="Carga urgente"
          tone="warning"
          rows={[
            ['Batería', percentOrUnknown(block.props.battery)],
            ['Más cercano', text(block.props.nearest)],
            ['Distancia', metric(block.props.distanceKm, 'km')],
          ]}
        />
      )
    case 'DestinationChargingCard':
      return (
        <MetricCard
          icon={MapPinned}
          title="Carga en destino"
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
      return <ActionButtons actions={list(block.props.actions)} />
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
    case 'PreferenceChips':
      return (
        <div className="flex flex-wrap gap-2">
              {strings(block.props.chips).map((chip) => (
                <Button key={chip} type="button" variant="outline" size="sm" onClick={() => actions.onChipClick?.(chip)}>
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
          <Button type="button" className="h-11 w-full font-semibold" onClick={requestLocation} disabled={status === 'pending'}>
            <Navigation className="size-4" aria-hidden="true" />
            {status === 'pending' ? 'Solicitando...' : 'Usar mi ubicación'}
          </Button>
          <Button
            type="button"
            variant="outline"
            className="h-11 w-full"
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
}: {
  icon: typeof Route
  title: string
  rows: Array<[string, string]>
  tone: 'primary' | 'warning' | 'route' | 'assistant'
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
      <CardContent>
        <MetricGrid rows={rows} />
      </CardContent>
    </Card>
  )
}

function RecommendationCard({
  icon: Icon,
  title,
  rows,
}: {
  icon: typeof Route
  title: string
  rows: Array<[string, string]>
}) {
  return (
    <Card className="border-primary bg-primary text-primary-foreground">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-start gap-3 text-base font-semibold tracking-tight">
          <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-md bg-primary-foreground text-primary">
            <Icon className="size-4" aria-hidden="true" />
          </span>
          <span className="flex min-w-0 flex-col gap-1">
            <span className="text-caption font-medium text-primary-foreground/70">Recomendación principal</span>
            <span className="truncate">{title || 'Cargador recomendado'}</span>
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <MetricGridRows rows={rows} inverted />
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
          <span className={cn('block truncate text-compact font-semibold tracking-tight', inverted ? 'text-primary-foreground' : 'text-foreground')}>{value}</span>
        </div>
      ))}
    </div>
  )
}

function ListCard({ title, items }: { title: string; items: RecordList }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold tracking-tight">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col divide-y divide-border">
        {items.map((item, index) => (
          <div key={`${text(item.name)}-${index}`} className="flex items-center gap-3 py-2.5 text-sm first:pt-0 last:pb-0">
            <span className="grid size-7 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-muted-foreground">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold tracking-tight">{text(item.name)}</div>
              <div className="text-muted-foreground">
                {isKnownNumber(item.powerKw)
                  ? `${metric(item.powerKw, 'kW')}${isKnownNumber(item.distanceKm) ? ` · ${metric(item.distanceKm, 'km')}` : ''}`
                  : metric(item.deltaMin, 'min de diferencia')}
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
  return (
    <Alert className={cn('border-warning bg-warning-soft text-foreground', high && 'border-error bg-error-soft')}>
      <AlertTriangle aria-hidden="true" />
      <AlertTitle className="text-sm font-semibold">
        {high ? 'Riesgo alto' : 'Riesgo a confirmar'}
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

function ActionButtons({ actions }: { actions: RecordList }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {actions.map((action, index) => (
        <div key={text(action.label)} className="flex flex-col gap-1">
          <Button
            type="button"
            disabled={bool(action.disabled)}
            variant={index === 0 && !bool(action.disabled) ? 'default' : 'outline'}
            className={index === 0 ? 'h-11 w-full font-bold' : 'h-11 w-full'}
            onClick={() => openAction(text(action.href, ''))}
          >
            {text(action.label)}
          </Button>
          {bool(action.disabled) && text(action.reason, '') ? (
            <p className="max-w-48 text-xs leading-5 text-muted-foreground">{text(action.reason, '')}</p>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function openAction(href: string) {
  if (!href) {
    return
  }
  window.open(href, '_blank', 'noopener,noreferrer')
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

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => text(item, '')).filter((item) => item.length > 0)
    : []
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
