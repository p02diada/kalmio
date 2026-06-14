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
import { Component, type ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import type { A2UIBlock } from '@/lib/a2ui/types'

type RecordList = Array<Record<string, unknown>>

export function A2UIRenderer({
  blocks,
  onChipClick,
}: {
  blocks: A2UIBlock[]
  onChipClick?: (value: string) => void
}) {
  return (
    <div className="space-y-3">
      {blocks.map((block) => (
        <A2UIBoundary key={block.id} block={block} onChipClick={onChipClick} />
      ))}
    </div>
  )
}

function A2UIBoundary({ block, onChipClick }: { block: A2UIBlock; onChipClick?: (value: string) => void }) {
  return (
    <BlockErrorBoundary type={block.type}>
      <A2UIBlockView block={block} onChipClick={onChipClick} />
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

function A2UIBlockView({ block, onChipClick }: { block: A2UIBlock; onChipClick?: (value: string) => void }) {
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
            ['Distancia', `${num(block.props.distanceKm)} km`],
            ['Duración', `${num(block.props.durationMin)} min`],
            ['Energía', `${num(block.props.energyKwh)} kWh`],
            ['Llegada', `${num(block.props.arrivalBattery)}%`],
          ]}
        />
      )
    case 'RecommendedStopCard':
      return (
        <MetricCard
          icon={BatteryCharging}
          title={text(block.props.name)}
          tone="primary"
          rows={[
            ['Potencia', `${num(block.props.powerKw)} kW`],
            ['Desvío', `${num(block.props.detourMin)} min`],
            ['Confianza', text(block.props.confidence)],
          ]}
        />
      )
    case 'AlternativeRoutesList':
      return <ListCard title="Rutas alternativas" items={list(block.props.routes)} />
    case 'AlternativeStopsList':
      return <ListCard title="Cargadores alternativos" items={list(block.props.stops)} />
    case 'RiskExplanationCard':
      return (
        <Card className="border-warning/40 bg-warning/10">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="size-4 text-warning" aria-hidden="true" />
              Riesgo {text(block.props.level)}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm leading-6 text-muted-foreground">{text(block.props.text)}</CardContent>
        </Card>
      )
    case 'CostComparisonCard':
      return (
        <MetricCard
          icon={Euro}
          title={text(block.props.best)}
          tone="primary"
          rows={[
            ['Coste estimado', `${num(block.props.estimatedCostEur)} EUR`],
            ['Ahorro estimado', `${num(block.props.savingEur)} EUR`],
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
            ['Distancia', `${num(block.props.distanceKm)} km`],
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
            ['Noches', String(num(block.props.nights))],
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
        <Card className="border-assistant/30 bg-assistant/10">
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
    case 'PreferenceChips':
      return (
        <div className="flex flex-wrap gap-2">
              {strings(block.props.chips).map((chip) => (
                <Button key={chip} type="button" variant="secondary" size="sm" onClick={() => onChipClick?.(chip)}>
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
            ? 'max-w-[82%] rounded-lg border border-primary/15 bg-primary-soft px-3 py-2 text-[0.86rem] leading-5 tracking-[-0.01em] shadow-[0_2px_8px_oklch(20.5%_0_0_/_0.08)]'
            : 'max-w-[82%] rounded-lg border border-border bg-surface px-3 py-2 text-[0.86rem] leading-5 tracking-[-0.01em] shadow-[0_2px_8px_oklch(20.5%_0_0_/_0.08)]'
        }
      >
        <span className="mb-1 flex items-center gap-2 text-[0.72rem] font-medium text-muted-foreground">
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
    <Card className="border-border bg-surface shadow-[0_2px_8px_oklch(20.5%_0_0_/_0.08)]">
      <CardHeader className="pb-1">
        <CardTitle className="flex items-center gap-2 text-[0.86rem] font-semibold tracking-[-0.02em] text-route">
          <Route className="size-4" aria-hidden="true" />
          Resumen de la ruta
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2 text-[1.05rem] font-semibold tracking-[-0.03em]">
          <span>{text(block.props.origin)}</span>
          <span className="text-primary" aria-hidden="true">→</span>
          <span>{text(block.props.destination)}</span>
        </div>
        <MetricGrid
          rows={[
            ['Batería', `${num(block.props.battery)}%`],
            ['Reserva', `${num(block.props.reserve)}%`],
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
    <Card className="border-border bg-surface shadow-[0_2px_8px_oklch(20.5%_0_0_/_0.08)]">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-[0.96rem] font-semibold tracking-[-0.02em]">
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

function MetricGrid({ rows }: { rows: Array<[string, string]> }) {
  return (
    <div className="grid grid-cols-3 gap-2 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <span className="block truncate text-[0.68rem] font-medium leading-4 text-muted-foreground">{label}</span>
          <span className="block truncate text-[0.86rem] font-semibold leading-5 tracking-[-0.02em] text-foreground">{value}</span>
        </div>
      ))}
    </div>
  )
}

function ListCard({ title, items }: { title: string; items: RecordList }) {
  return (
    <Card className="border-border bg-surface shadow-[0_2px_8px_oklch(20.5%_0_0_/_0.08)]">
      <CardHeader>
        <CardTitle className="text-[0.96rem] font-semibold tracking-[-0.02em]">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map((item, index) => (
          <div key={`${text(item.name)}-${index}`} className="flex items-center gap-3 rounded-md border border-border bg-surface p-3 text-sm">
            <span className="grid size-7 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-muted-foreground">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold tracking-[-0.01em]">{text(item.name)}</div>
              <div className="text-muted-foreground">
                {item.powerKw
                  ? `${num(item.powerKw)} kW${item.distanceKm ? ` · ${num(item.distanceKm)} km` : ''}`
                  : `${num(item.deltaMin)} min de diferencia`}
              </div>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function MapPreviewCard({ block }: { block: A2UIBlock }) {
  return (
    <Card className="border-border bg-surface shadow-[0_2px_8px_oklch(20.5%_0_0_/_0.08)]">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MapPinned className="size-4 text-route" aria-hidden="true" />
          Vista de ruta
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="relative h-40 overflow-hidden rounded-md border border-border bg-[oklch(95%_0.018_225)]">
          <div className="absolute inset-0 opacity-55 [background-image:linear-gradient(30deg,transparent_45%,oklch(100%_0_0_/_0.75)_46%,transparent_48%),linear-gradient(120deg,transparent_42%,oklch(100%_0_0_/_0.75)_44%,transparent_46%)] [background-size:54px_54px,70px_70px]" />
          <div className="absolute left-8 top-24 h-1 w-64 -rotate-12 rounded-md bg-primary" />
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
        <div key={text(action.label)} className="space-y-1">
          <Button
            type="button"
            disabled={bool(action.disabled)}
            variant={index === 0 && !bool(action.disabled) ? 'default' : 'outline'}
            className={index === 0 ? 'h-11 w-full font-bold' : 'h-11 w-full'}
            onClick={() => openAction(text(action.href))}
          >
            {text(action.label)}
          </Button>
          {bool(action.disabled) && text(action.reason) ? (
            <p className="max-w-48 text-xs leading-5 text-muted-foreground">{text(action.reason)}</p>
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
        <CardTitle className="text-base">Bloque no disponible</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm text-muted-foreground">
        <p>{message}</p>
        <Separator />
        <code className="text-xs">{type}</code>
      </CardContent>
    </Card>
  )
}

function text(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function num(value: unknown) {
  return typeof value === 'number' ? value : 0
}

function percentOrUnknown(value: unknown) {
  return typeof value === 'number' ? `${value}%` : 'No indicada'
}

function bool(value: unknown) {
  return value === true
}

function list(value: unknown): RecordList {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item)) : []
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}
