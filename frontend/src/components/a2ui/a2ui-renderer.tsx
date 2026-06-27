import {
  ArrowLeft,
  AlertTriangle,
  BatteryCharging,
  Maximize2,
  MapPinned,
  MessageCircle,
  Navigation,
  X,
  type LucideIcon,
} from 'lucide-react'
import {
  Component,
  type PointerEvent,
  type ReactNode,
  type WheelEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { createPortal } from 'react-dom'
import type { Map as MapLibreMap, Marker as MapLibreMarker } from 'maplibre-gl'

import { StationConnectorBadge } from '@/components/a2ui/station-connector-badge'
import { KalmioBrandMark } from '@/components/brand/kalmio-brand-mark'
import { Bubble, BubbleContent } from '@/components/ui/bubble'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Message, MessageAvatar, MessageContent } from '@/components/ui/message'
import { MessageScrollerItem } from '@/components/ui/message-scroller'
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
  markerLabel?: string
  capacityLabel?: string
  evseRatioLabel?: string
  powerLabel?: string
  distanceLabel?: string
  detourLabel?: string
  priceLabel?: string
  connectorLabels?: string[]
  roleLabel?: string
  station?: Record<string, unknown>
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
const DEFAULT_MAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'
type A2UIRendererActions = {
  onChipClick?: (value: string) => void
  onActionEvent?: (name: string, context?: Record<string, unknown>, sourceComponentId?: string) => void
  onPositionSubmit?: (value: string) => void
  onManualPositionRequest?: () => void
}
type A2UICardTone = 'neutral' | 'primary' | 'route' | 'assistant' | 'warning' | 'error'
const STATION_POWER_LABEL = 'Potencia máx.'

export function A2UIRenderer({
  blocks,
  useMessageScrollerItems = false,
  onChipClick,
  onActionEvent,
  onPositionSubmit,
  onManualPositionRequest,
}: {
  blocks: A2UIBlock[]
  useMessageScrollerItems?: boolean
} & A2UIRendererActions) {
  const actions = { onChipClick, onActionEvent, onPositionSubmit, onManualPositionRequest }
  const renderedBlocks: ReactNode[] = []

  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index]
    const nextBlock = blocks[index + 1]

    if (nextBlock?.type === 'ActionButtons' && canHostActionFooter(block)) {
      renderedBlocks.push(
        <A2UIItem
          key={`${block.id}-${nextBlock.id}`}
          block={block}
          useMessageScrollerItems={useMessageScrollerItems}
          className="flex min-w-0 max-w-full flex-col gap-2"
          data-a2ui-decision-unit="true"
          data-a2ui-action-footer-for={block.id}
        >
          <div data-a2ui-block-id={block.id} data-a2ui-block-type={block.type}>
            <A2UIBoundary block={block} actions={actions} />
          </div>
          <div className="-mt-1 px-1" data-a2ui-block-id={nextBlock.id} data-a2ui-block-type={nextBlock.type}>
            <A2UIBoundary block={nextBlock} actions={actions} />
          </div>
        </A2UIItem>,
      )
      index += 1
      continue
    }

    renderedBlocks.push(
      <A2UIItem
        key={block.id}
        block={block}
        useMessageScrollerItems={useMessageScrollerItems}
        data-a2ui-block-id={block.id}
        data-a2ui-block-type={block.type}
      >
        <A2UIBoundary block={block} actions={actions} />
      </A2UIItem>,
    )
  }

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-3">
      {renderedBlocks}
    </div>
  )
}

function A2UIItem({
  block,
  children,
  useMessageScrollerItems,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  block: A2UIBlock
  children: ReactNode
  useMessageScrollerItems: boolean
}) {
  if (useMessageScrollerItems) {
    return (
      <MessageScrollerItem
        messageId={block.id}
        scrollAnchor={block.type === 'UserMessage'}
        {...props}
      >
        {children}
      </MessageScrollerItem>
    )
  }

  return <div {...props}>{children}</div>
}

function canHostActionFooter(block: A2UIBlock) {
  return (
    block.type === 'StationPreviewCard' ||
    block.type === 'StationDetailCard' ||
    block.type === 'RouteCorridorCard'
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

const A2UI_CARD_TONES: Record<A2UICardTone, { icon: string; iconShell: string }> = {
  neutral: {
    icon: 'text-muted-foreground',
    iconShell: 'bg-muted',
  },
  primary: {
    icon: 'text-primary',
    iconShell: 'bg-muted',
  },
  route: {
    icon: 'text-route',
    iconShell: 'bg-route-soft',
  },
  assistant: {
    icon: 'text-assistant',
    iconShell: 'bg-assistant-soft',
  },
  warning: {
    icon: 'text-foreground',
    iconShell: 'bg-warning-soft',
  },
  error: {
    icon: 'text-error',
    iconShell: 'bg-error-soft',
  },
}

function A2UICard({
  icon: Icon,
  title,
  subtitle,
  tone = 'neutral',
  children,
  className,
  contentClassName,
  titleClassName,
  headerAction,
}: {
  icon?: LucideIcon
  title: ReactNode
  subtitle?: ReactNode
  tone?: A2UICardTone
  children: ReactNode
  className?: string
  contentClassName?: string
  titleClassName?: string
  headerAction?: ReactNode
}) {
  const toneClasses = A2UI_CARD_TONES[tone]

  return (
    <Card className={cn('overflow-hidden', className)}>
      <CardHeader className="pb-2">
        <div className={cn('flex min-w-0 justify-between gap-3', subtitle ? 'items-start' : 'items-center')}>
          <div className={cn('flex min-w-0 gap-3', subtitle ? 'items-start' : 'items-center')}>
            {Icon ? (
              <span className={cn('grid size-8 shrink-0 place-items-center rounded-md', subtitle && 'mt-0.5', toneClasses.iconShell)}>
                <Icon className={cn('size-4', toneClasses.icon)} aria-hidden="true" />
              </span>
            ) : null}
            <div className="min-w-0">
              <CardTitle className={cn('break-words text-sm font-semibold leading-5 tracking-tight text-foreground [overflow-wrap:anywhere]', titleClassName)}>
                {title}
              </CardTitle>
              {subtitle ? (
                <p className="mt-0.5 break-words text-caption font-medium leading-4 text-muted-foreground [overflow-wrap:anywhere]">
                  {subtitle}
                </p>
              ) : null}
            </div>
          </div>
          {headerAction ? <div className="shrink-0">{headerAction}</div> : null}
        </div>
      </CardHeader>
      <CardContent className={cn('space-y-3 pt-1', contentClassName)}>
        {children}
      </CardContent>
    </Card>
  )
}

function A2UIBlockView({ block, actions }: { block: A2UIBlock; actions: A2UIRendererActions }) {
  switch (block.type) {
    case 'AssistantMessage':
      return <MessageCard text={text(block.props.text)} />
    case 'UserMessage':
      return <MessageCard text={text(block.props.text)} align="right" />
    case 'RouteCorridorCard':
      return <RouteCorridorCard block={block} />
    case 'StationPreviewCard':
      return <StationPreviewCard block={block} />
    case 'StationDetailCard':
      return <StationDetailCard block={block} />
    case 'StationList':
      return <StationListCard title={text(block.props.title, 'Estaciones cercanas')} stations={list(block.props.stations)} />
    case 'ActionButtons':
      return (
        <ActionButtons
          actions={list(block.props.actions)}
          sourceComponentId={block.id}
          onActionEvent={actions.onActionEvent ?? actions.onChipClick}
        />
      )
    case 'PositionRequestCard':
      return (
        <PositionRequestCard
          block={block}
          onPositionSubmit={actions.onPositionSubmit ?? actions.onChipClick}
          onManualPositionRequest={actions.onManualPositionRequest}
        />
      )
    case 'PreferenceChips':
      return <PreferenceChips block={block} onChipClick={actions.onChipClick} />
    case 'ErrorFallbackCard':
      return <ErrorFallbackCard type={text(block.props.originalType)} message={text(block.props.message)} />
    default:
      return <ErrorFallbackCard type={block.type} message="No reconozco esta parte de la respuesta." />
  }
}

function PreferenceChips({
  block,
  onChipClick,
}: {
  block: A2UIBlock
  onChipClick?: (value: string) => void
}) {
  const title = text(block.props.title, 'Ajusta el plan')
  const chips = strings(block.props.chips)

  if (!chips.length) {
    return null
  }

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-2" role="group" aria-label={title}>
      <p className="break-words text-caption font-semibold leading-4 text-muted-foreground [overflow-wrap:anywhere]">
        {title}
      </p>
      <div className="flex min-w-0 max-w-full flex-wrap gap-2">
        {chips.map((chip) => (
          <Button
            key={chip}
            type="button"
            variant="outline"
            size="sm"
            className="h-auto min-h-10 max-w-full min-w-0 whitespace-normal break-words px-3 py-2 text-left leading-5"
            onClick={() => onChipClick?.(chip)}
          >
            {chip}
          </Button>
        ))}
      </div>
    </div>
  )
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
  const [status, setStatus] = useState<'idle' | 'pending' | 'unsupported' | 'failed'>('idle')
  const manualFields = strings(block.props.manualFields)
  const manualFallbackHint = manualLocationHint(manualFields, { includeCoordinates: true })

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
    unsupported: `Este navegador no permite compartir ubicación aquí. ${manualFallbackHint}`,
    failed: `No pude acceder a tu ubicación. ${manualFallbackHint}`,
  }[status]

  return (
    <A2UICard icon={MapPinned} tone="assistant" title={text(block.props.title)} subtitle="Tu posición se usa solo para resolver esta búsqueda.">
      <p className="text-sm leading-6 text-body">{text(block.props.body)}</p>
      <div className="grid min-w-0 max-w-full grid-cols-1 gap-2 sm:grid-cols-2">
        <Button
          type="button"
          variant="outline"
          className="h-auto min-h-11 w-full whitespace-normal px-3 font-semibold leading-5"
          onClick={requestLocation}
          disabled={status === 'pending'}
        >
          <Navigation className="size-4" aria-hidden="true" />
          {status === 'pending' ? 'Solicitando...' : 'Usar mi ubicación'}
        </Button>
        <Button
          type="button"
          variant="outline"
          className="h-auto min-h-11 w-full max-w-full whitespace-normal px-3 font-semibold leading-5"
          onClick={() => {
            setStatus('idle')
            onManualPositionRequest?.()
          }}
        >
          <MessageCircle className="size-4" aria-hidden="true" />
          Escribir ubicación
        </Button>
      </div>
      {statusMessage ? <p className="text-xs leading-5 text-muted-foreground">{statusMessage}</p> : null}
    </A2UICard>
  )
}

function MessageCard({
  text: value,
  align = 'left',
}: {
  text: string
  align?: 'left' | 'right'
}) {
  const isUser = align === 'right'

  if (isUser) {
    return (
      <Message align="end">
        <MessageContent>
          <Bubble variant="muted" align="end" className="a2ui-message a2ui-message-user">
            <BubbleContent>
              <span className="sr-only">Usuario: </span>
              {value}
            </BubbleContent>
          </Bubble>
        </MessageContent>
      </Message>
    )
  }

  return (
    <Message align="start">
      <MessageAvatar className="mt-1 bg-assistant-soft text-assistant">
        <KalmioBrandMark className="size-5" />
      </MessageAvatar>
      <MessageContent>
        <Bubble variant="default" className="a2ui-message a2ui-message-assistant">
          <BubbleContent>{value}</BubbleContent>
        </Bubble>
      </MessageContent>
    </Message>
  )
}

function StationPreviewCard({ block }: { block: A2UIBlock }) {
  const [isDetailOpen, setIsDetailOpen] = useState(false)
  const station = stationLabel(block.props) || stationTitle(block.props)

  return (
    <>
      <button
        type="button"
        className="group block w-full rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        aria-label={`Ver detalle completo de ${station || 'la estación'}`}
        aria-haspopup="dialog"
        onClick={() => setIsDetailOpen(true)}
      >
        <StationDetailSummary station={block.props} />
      </button>
      <StationDetailSheet
        open={isDetailOpen}
        station={block.props}
        onOpenChange={setIsDetailOpen}
      />
    </>
  )
}

function StationDetailCard({ block }: { block: A2UIBlock }) {
  return <StationDetailPanel station={block.props} mode="inline" />
}

function StationDetailSummary({ station }: { station: Record<string, unknown> }) {
  const stationName = stationLabel(station) || stationTitle(station)
  const address = text(station.address, '')
  const capacity = stationCapacity(station)
  const connectors = connectorLabels(station.connectorTypes)
  const amenities = amenityLabels(station.amenities)
  const title = text(station.title, 'Estación de carga')

  return (
    <A2UICard
      icon={BatteryCharging}
      tone="primary"
      title={<span className="break-words [overflow-wrap:anywhere]">{stationName || 'Estación por confirmar'}</span>}
      subtitle={compactParts([title, address]).join(' · ')}
      className="transition-colors group-hover:border-border-strong group-hover:bg-muted/30"
      titleClassName="text-base"
      headerAction={<span className="rounded-full bg-muted px-2 py-1 text-caption font-semibold text-body">Detalle</span>}
    >
      <DecisionNarrative props={station} />
      <MetricGridRows
        rows={compactRows([
          isKnownNumber(station.distanceKm) ? ['Distancia', metric(station.distanceKm, 'km')] : null,
          isKnownNumber(station.powerKw) ? [STATION_POWER_LABEL, metric(station.powerKw, 'kW')] : null,
          stationPriceRow(station),
          capacity ? ['Puestos', capacity] : ['Confianza', text(station.confidence)],
          isKnownNumber(station.detourMin) ? ['Desvío', metric(station.detourMin, 'min')] : null,
        ])}
      />
      {connectors.length > 0 ? (
        <div className="border-t border-border pt-3">
          <span className="block text-caption font-medium text-muted-foreground">
            Conectores
          </span>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {connectors.map((connector) => (
              <StationConnectorBadge key={connector} connector={connector} />
            ))}
          </div>
        </div>
      ) : null}
      {amenities && amenities.length > 0 ? (
        <div className="border-t border-border pt-3">
          <span className="block text-caption font-medium text-muted-foreground">
            Servicios indicados
          </span>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {amenities.map((amenity) => (
              <span
                key={amenity}
                className="max-w-full rounded-full bg-muted px-2 py-1 text-caption font-semibold leading-4 text-foreground [overflow-wrap:anywhere]"
              >
                {amenity}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </A2UICard>
  )
}

function StationDetailSheet({
  open,
  station,
  onOpenChange,
}: {
  open: boolean
  station: Record<string, unknown>
  onOpenChange: (open: boolean) => void
}) {
  useEffect(() => {
    if (!open || typeof document === 'undefined') {
      return
    }

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onOpenChange(false)
      }
    }

    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [onOpenChange, open])

  if (!open || typeof document === 'undefined') {
    return null
  }

  return createPortal(
    <div className="a2ui-station-sheet-backdrop" onClick={() => onOpenChange(false)}>
      <StationDetailPanel
        station={station}
        onClose={() => onOpenChange(false)}
      />
    </div>,
    document.body,
  )
}

function StationDetailPanel({
  station,
  titleOverride,
  mode = 'sheet',
  onClose,
}: {
  station: Record<string, unknown>
  titleOverride?: string
  mode?: 'sheet' | 'inline'
  onClose?: () => void
}) {
  const stationName = stationLabel(station) || stationTitle(station)
  const address = text(station.address, '')
  const title = titleOverride || text(station.title, 'Estación de carga')
  const connectors = connectorLabels(station.connectorTypes)
  const amenities = amenityLabels(station.amenities, 12)
  const availabilityRows = stationAvailabilityRows(station)
  const chargingRows = compactRows([
    isKnownNumber(station.powerKw) ? [STATION_POWER_LABEL, metric(station.powerKw, 'kW')] : null,
    stationPriceDetailRow(station),
  ])
  const routeRows = compactRows([
    isKnownNumber(station.distanceKm) ? ['Distancia', metric(station.distanceKm, 'km')] : null,
    isKnownNumber(station.detourMin) ? ['Desvío', metric(station.detourMin, 'min')] : null,
  ])
  const notes = stationDetailNotes(station)
  const isSheet = mode === 'sheet'

  return (
    <section
      className={isSheet ? 'a2ui-station-bottom-sheet' : 'a2ui-station-detail-card'}
      role={isSheet ? 'dialog' : undefined}
      aria-modal={isSheet ? true : undefined}
      aria-label="Detalle de estación"
      onClick={(event) => event.stopPropagation()}
    >
      {isSheet ? <div className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-border-strong/70" aria-hidden="true" /> : null}
      <div className="flex min-w-0 items-start justify-between gap-3 border-b border-border px-4 pb-3 pt-2">
        <div className="min-w-0">
          <p className="text-caption font-semibold leading-4 text-muted-foreground">{title}</p>
          <h2 className="mt-1 break-words text-lg font-semibold leading-6 tracking-tight text-foreground [overflow-wrap:anywhere]">
            {stationName || 'Estación por confirmar'}
          </h2>
          {address ? (
            <p className="mt-1 break-words text-sm leading-5 text-body [overflow-wrap:anywhere]">{address}</p>
          ) : null}
        </div>
        {onClose ? (
          <button
            type="button"
            className="grid size-9 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={onClose}
          >
            <X className="size-4" aria-hidden="true" />
            <span className="sr-only">Cerrar detalle</span>
          </button>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
        <div className="flex flex-col gap-4">
          <DecisionNarrative props={station} />
          {routeRows.length > 0 ? <MetricGridRows rows={routeRows} /> : null}
          {availabilityRows.length > 0 ? (
            <StationDetailSection title="Puestos de carga">
              <MetricGridRows rows={availabilityRows} />
            </StationDetailSection>
          ) : null}
          {chargingRows.length > 0 ? (
            <StationDetailSection title="Carga y tarifa">
              <MetricGridRows rows={chargingRows} />
            </StationDetailSection>
          ) : null}
          {connectors.length > 0 ? (
            <StationDetailSection title="Conectores">
              <div className="flex flex-wrap gap-1.5">
                {connectors.map((connector) => (
                  <StationConnectorBadge key={connector} connector={connector} />
                ))}
              </div>
            </StationDetailSection>
          ) : null}
          {amenities.length > 0 ? (
            <StationDetailSection title="Servicios indicados">
              <div className="flex flex-wrap gap-1.5">
                {amenities.map((amenity) => (
                  <span
                    key={amenity}
                    className="max-w-full rounded-full bg-muted px-2 py-1 text-caption font-semibold leading-4 text-foreground [overflow-wrap:anywhere]"
                  >
                    {amenity}
                  </span>
                ))}
              </div>
            </StationDetailSection>
          ) : null}
          {notes.length > 0 ? (
            <StationDetailSection title="Datos y cautelas">
              <ul className="flex flex-col gap-2 text-sm leading-5 text-body">
                {notes.map((note) => (
                  <li key={note} className="rounded-md bg-muted px-3 py-2">{note}</li>
                ))}
              </ul>
            </StationDetailSection>
          ) : null}
        </div>
      </div>
    </section>
  )
}

function StationDetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-caption font-semibold leading-4 text-muted-foreground">{title}</h3>
      {children}
    </section>
  )
}

function RouteCorridorCard({ block }: { block: A2UIBlock }) {
  const mapData = useMemo(() => routeMapData(block.props), [block.props])
  const [isExpanded, setIsExpanded] = useState(false)
  const [selectedStationId, setSelectedStationId] = useState<string | null>(null)
  const stations = routeCorridorStations(block.props)
  const stationCount = stations.length
  const arrivalBattery = knownNumber(block.props.arrivalBattery, { zeroUnknown: true })
  const arrivalValue = arrivalBattery === null ? null : `${formatNumber(arrivalBattery)}%`
  const routeMeta = compactParts([
    `${formatNumber(stationCount)} estaciones cerca de la ruta`,
    metric(block.props.distanceKm, 'km'),
    compactDuration(block.props.durationText, block.props.durationMin),
  ]).join(' · ')
  const expandedMap = isExpanded && typeof document !== 'undefined'
    ? createPortal(
      <section className="a2ui-map-fullscreen" aria-label="Detalle de ruta">
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="a2ui-map-floating-back"
          aria-label="Volver"
          onClick={() => {
            setIsExpanded(false)
            setSelectedStationId(null)
          }}
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
        </Button>
        <div className="a2ui-map-fullscreen-body">
          <RouteCorridorExpandedDetail
            props={block.props}
            mapData={mapData}
            selectedStationId={selectedStationId}
            onStationSelect={setSelectedStationId}
          />
        </div>
      </section>,
      document.body,
    )
    : null

  useEffect(() => {
    if (!isExpanded || typeof document === 'undefined') {
      return
    }
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [isExpanded])

  return (
    <>
      <Card className="overflow-hidden">
        <CardHeader className="p-3 pb-2">
          <div className="flex min-w-0 items-start justify-between gap-3">
            <div className="flex min-w-0 items-start gap-2.5">
              <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-md bg-route-soft text-route">
                <Navigation className="size-4" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <CardTitle className="break-words text-sm font-semibold leading-5 tracking-tight text-foreground [overflow-wrap:anywhere]">
                  Ruta y carga
                </CardTitle>
                <p className="mt-0.5 truncate text-caption font-medium leading-4 text-muted-foreground">
                  {mapData.originLabel} → {mapData.destinationLabel}
                </p>
              </div>
            </div>
            <Button type="button" variant="outline" size="sm" className="h-8 shrink-0 px-2" aria-label="Abrir detalle de ruta" onClick={() => setIsExpanded(true)}>
              <Maximize2 className="size-4" aria-hidden="true" />
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-2 px-3 pb-3 pt-0">
          <button type="button" className="block w-full rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" aria-label="Abrir detalle de ruta" onClick={() => setIsExpanded(true)}>
            <RouteMapCanvas data={mapData} variant="compact" density="mini" />
          </button>
          {arrivalValue ? (
            <div className="flex min-w-0 items-center justify-between gap-3 rounded-md border border-border bg-muted/45 px-2.5 py-2">
              <div className="min-w-0">
                <span className="block text-[0.6875rem] font-medium leading-3 text-muted-foreground">Llegada directa</span>
                <span className={cn(
                  'mt-0.5 block text-base font-semibold leading-5 tracking-tight',
                  arrivalBattery !== null && arrivalBattery <= 20 ? 'text-warning' : 'text-foreground',
                )}>{arrivalValue}</span>
              </div>
              <p className="min-w-0 truncate text-right text-[0.8125rem] font-medium leading-4 text-body">
                {routeMeta}
              </p>
            </div>
          ) : (
            <div className="rounded-md border border-border bg-muted/45 px-2.5 py-2">
              <p className="truncate text-sm font-semibold leading-5 text-foreground">
                {routeCorridorStationCountLabel(stationCount)}
              </p>
              <p className="mt-0.5 truncate text-[0.8125rem] font-medium leading-4 text-body">
                {metric(block.props.distanceKm, 'km')} · {compactDuration(block.props.durationText, block.props.durationMin)}
              </p>
              <p className="mt-1 text-[0.6875rem] font-medium leading-3 text-muted-foreground">
                Batería de llegada no validada
              </p>
            </div>
          )}
        </CardContent>
      </Card>
      {expandedMap}
    </>
  )
}

function RouteCorridorDetailSummary({
  props,
}: {
  props: Record<string, unknown>
}) {
  const origin = text(record(props.origin)?.label ?? props.origin, 'Origen')
  const destination = text(record(props.destination)?.label ?? props.destination, 'Destino')

  return (
    <div className="a2ui-route-corridor-detail-summary">
      <div className="a2ui-route-corridor-route">
        <div className="min-w-0">
          <span className="block text-[0.625rem] font-medium leading-3 text-muted-foreground">Origen</span>
          <span className="block truncate text-xs font-semibold leading-4 text-foreground">{origin}</span>
        </div>
        <span className="a2ui-route-corridor-route-line" aria-hidden="true" />
        <div className="min-w-0 text-right">
          <span className="block text-[0.625rem] font-medium leading-3 text-muted-foreground">Destino</span>
          <span className="block truncate text-xs font-semibold leading-4 text-foreground">{destination}</span>
        </div>
      </div>
    </div>
  )
}

function RouteCorridorExpandedDetail({
  props,
  mapData,
  selectedStationId,
  onStationSelect,
}: {
  props: Record<string, unknown>
  mapData: RouteMapData
  selectedStationId: string | null
  onStationSelect: (stationId: string | null) => void
}) {
  const stationCardRefs = useRef<Record<string, HTMLElement | null>>({})
  const selectStation = useCallback((stationId: string | null) => {
    onStationSelect(stationId)
    if (!stationId) {
      return
    }
    window.requestAnimationFrame(() => {
      scrollStationCardIntoView(stationCardRefs.current[stationId] ?? null)
    })
  }, [onStationSelect])

  return (
    <div className="a2ui-route-corridor-detail">
      <div className="a2ui-route-corridor-workspace">
        <RouteMapCanvas
          data={mapData}
          variant="expanded"
          selectedStationId={selectedStationId}
          onStationSelect={selectStation}
        />
        <RouteCorridorDetailSummary props={props} />
        <RouteCorridorStationCarousel
          stations={mapData.stationPoints}
          selectedStationId={selectedStationId}
          onStationSelect={selectStation}
          registerStationCard={(stationId, element) => {
            stationCardRefs.current[stationId] = element
          }}
        />
      </div>
    </div>
  )
}

function RouteCorridorStationCarousel({
  stations,
  selectedStationId,
  onStationSelect,
  registerStationCard,
}: {
  stations: RouteMapPoint[]
  selectedStationId: string | null
  onStationSelect: (stationId: string | null) => void
  registerStationCard: (stationId: string, element: HTMLElement | null) => void
}) {
  const dragStateRef = useRef<StationStripDragState | null>(null)
  const suppressClickUntilRef = useRef(0)

  const startDrag = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== 'mouse' || event.button !== 0) {
      return
    }
    dragStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startScrollLeft: event.currentTarget.scrollLeft,
      hasDragged: false,
    }
  }, [])

  const moveDrag = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return
    }

    const deltaX = event.clientX - dragState.startX
    if (Math.abs(deltaX) > 8) {
      dragState.hasDragged = true
      event.currentTarget.classList.add('a2ui-route-station-strip-dragging')
      if (!event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.setPointerCapture(event.pointerId)
      }
    }
    if (!dragState.hasDragged) {
      return
    }

    event.preventDefault()
    event.currentTarget.scrollLeft = dragState.startScrollLeft - deltaX
  }, [])

  const endDrag = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return
    }
    dragStateRef.current = null
    event.currentTarget.classList.remove('a2ui-route-station-strip-dragging')
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    suppressClickUntilRef.current = dragState.hasDragged ? window.performance.now() + 250 : 0
  }, [])

  if (stations.length === 0) {
    return (
      <aside className="a2ui-route-station-carousel" aria-label="Estaciones del corredor">
        <div className="a2ui-route-station-empty">
          <p className="text-sm font-semibold leading-5 text-foreground">Sin estaciones trazadas</p>
          <p className="mt-1 text-xs leading-5 text-body">El mapa conserva origen, destino y ruta cuando esos datos son válidos.</p>
        </div>
      </aside>
    )
  }

  return (
    <aside className="a2ui-route-station-carousel" aria-label="Estaciones del corredor">
      <div
        className="a2ui-route-station-strip"
        role="list"
        onClickCapture={(event) => {
          if (window.performance.now() > suppressClickUntilRef.current) {
            return
          }
          suppressClickUntilRef.current = 0
          event.preventDefault()
          event.stopPropagation()
        }}
        onPointerDown={startDrag}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onPointerLeave={endDrag}
        onWheel={handleStationStripWheel}
      >
        {stations.map((station) => (
          <RouteCorridorStationCard
            key={station.id}
            station={station}
            selected={station.id === selectedStationId}
            onSelect={() => onStationSelect(station.id)}
            cardRef={(element) => registerStationCard(station.id, element)}
          />
        ))}
      </div>
    </aside>
  )
}

type StationStripDragState = {
  pointerId: number
  startX: number
  startScrollLeft: number
  hasDragged: boolean
}

function RouteCorridorStationCard({
  station,
  selected,
  onSelect,
  cardRef,
}: {
  station: RouteMapPoint
  selected: boolean
  onSelect: () => void
  cardRef: (element: HTMLElement | null) => void
}) {
  const tariff = stationTariffLabel(station.station ?? {})
  const routeMeta = compactParts([
    station.detourLabel ? `${station.detourLabel} desvío` : '',
    station.distanceLabel ?? '',
  ]).join(' · ')
  const facts = compactParts([
    tariff === 'No disponible' || tariff === 'Sin verificar' ? '' : tariff,
    station.evseRatioLabel || station.capacityLabel || '',
    station.powerLabel ?? '',
  ]).slice(0, 3)

  return (
    <article
      ref={cardRef}
      className={cn('a2ui-route-station-card', selected && 'a2ui-route-station-card-selected')}
      role="listitem"
    >
      <button
        type="button"
        className="a2ui-route-station-card-button"
        aria-pressed={selected}
        onClick={onSelect}
      >
        <span className="a2ui-route-station-card-main">
          <span className="a2ui-route-station-card-marker">
            {station.markerLabel}
          </span>
          <span className="min-w-0 flex-1 text-left">
            <span className="line-clamp-1 break-words text-[0.8125rem] font-semibold leading-4 tracking-tight text-foreground [overflow-wrap:anywhere]">{station.label}</span>
            {routeMeta ? (
              <span className="mt-0.5 block truncate text-[0.6875rem] leading-4 text-body">{routeMeta}</span>
            ) : null}
          </span>
        </span>
        <span className="a2ui-route-station-card-footer">
          <span className="a2ui-route-station-card-facts" aria-label="Datos principales">
            {facts.map((fact) => (
              <span key={fact} className="a2ui-route-station-card-fact">{fact}</span>
            ))}
            {station.connectorLabels && station.connectorLabels.length > 0 ? (
              <StationConnectorBadge connector={station.connectorLabels[0]!} />
            ) : null}
          </span>
        </span>
      </button>
    </article>
  )
}

function scrollStationCardIntoView(card: HTMLElement | null) {
  const strip = card?.closest<HTMLElement>('.a2ui-route-station-strip')
  if (!card || !strip) {
    return
  }

  const targetLeft = card.offsetLeft - ((strip.clientWidth - card.offsetWidth) / 2)
  const nextLeft = Math.max(0, targetLeft)
  if (typeof strip.scrollTo === 'function') {
    strip.scrollTo({
      left: nextLeft,
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    })
    return
  }
  strip.scrollLeft = nextLeft
}

function handleStationStripWheel(event: WheelEvent<HTMLDivElement>) {
  const strip = event.currentTarget
  const maxScrollLeft = strip.scrollWidth - strip.clientWidth
  if (maxScrollLeft <= 0) {
    return
  }

  const rawDelta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
  const multiplier = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? strip.clientWidth : 1
  const nextLeft = Math.max(0, Math.min(maxScrollLeft, strip.scrollLeft + (rawDelta * multiplier)))
  if (nextLeft === strip.scrollLeft) {
    return
  }

  strip.scrollLeft = nextLeft
}

function routeCorridorStations(props: Record<string, unknown>): RecordList {
  const primaryStation = record(props.primaryStation)
  return [
    primaryStation,
    ...list(props.stations),
  ].filter((station): station is Record<string, unknown> => station !== null)
}

function routeCorridorStationCountLabel(count: number) {
  if (count === 0) {
    return 'Sin estaciones trazadas'
  }
  if (count === 1) {
    return '1 estación cerca de la ruta'
  }
  return `${formatNumber(count)} estaciones cerca de la ruta`
}

function DecisionNarrative({ props }: { props: Record<string, unknown> }) {
  const takeaway = text(props.takeaway, '')
  const why = text(props.why, '')
  const uncertainty = uncertaintyText(props.uncertainty)

  if (!takeaway && !why && !uncertainty) {
    return null
  }

  return (
    <div className="rounded-md bg-muted px-3 py-2 text-sm leading-6">
      {takeaway ? <p className="font-semibold tracking-tight text-foreground">{takeaway}</p> : null}
      {why ? <p className={cn('text-body', takeaway && 'mt-1')}>{why}</p> : null}
      {uncertainty ? <p className={cn('text-muted-foreground', (takeaway || why) && 'mt-1')}>{uncertainty}</p> : null}
    </div>
  )
}

function MetricGridRows({ rows, inverted = false }: { rows: Array<[string, string]>; inverted?: boolean }) {
  return (
    <div className="grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(7rem,100%),1fr))] gap-2 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="min-w-0 rounded-md bg-muted px-2.5 py-2">
          <span className={`block whitespace-normal text-caption font-medium leading-4 [overflow-wrap:anywhere] ${inverted ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>{label}</span>
          <span className={`block break-words text-compact font-semibold leading-5 tracking-tight [overflow-wrap:anywhere] ${inverted ? 'text-primary-foreground' : 'text-foreground'}`}>{value}</span>
        </div>
      ))}
    </div>
  )
}

function StationListCard({ title, stations }: { title: string; stations: RecordList }) {
  const subtitle = stations.length === 1 ? '1 alternativa' : `${formatNumber(stations.length)} alternativas`

  return (
    <A2UICard icon={BatteryCharging} tone="route" title={title} subtitle={subtitle}>
      {stations.length === 0 ? (
        <p className="text-sm leading-6 text-body">No hay estaciones alternativas para mostrar.</p>
      ) : (
        <ol className="flex flex-col">
          {stations.map((station, index) => (
            <StationListItem key={`${stationTitle(station, 'Estación')}-${index}`} station={station} />
          ))}
        </ol>
      )}
    </A2UICard>
  )
}

function StationListItem({ station }: { station: Record<string, unknown> }) {
  const address = text(station.address, '')
  const connectors = connectorLabels(station.connectorTypes)
  const amenities = amenityLabels(station.amenities)
  const power = isKnownNumber(station.powerKw) ? metric(station.powerKw, 'kW') : ''
  const capacity = stationListCapacity(station)
  const comparisonMetrics = compactRows([
    isKnownNumber(station.detourMin) ? ['Desvío', metric(station.detourMin, 'min')] : null,
    isKnownNumber(station.distanceKm) ? ['Distancia', metric(station.distanceKm, 'km')] : null,
    stationPriceListRow(station),
  ]).slice(0, 3)

  return (
    <li className="border-t border-border py-3 first:border-t-0 first:pt-0 last:pb-0">
      <div className="min-w-0">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="break-words text-sm font-semibold leading-5 tracking-tight text-foreground [overflow-wrap:anywhere]">
              {stationTitle(station, 'Estación')}
            </div>
            {address ? (
              <div className="mt-0.5 break-words text-caption font-medium leading-4 text-muted-foreground [overflow-wrap:anywhere]">
                {address}
              </div>
            ) : null}
          </div>
          {power || capacity ? (
            <div className="flex shrink-0 flex-col items-end gap-1">
              {power ? (
                <span className="text-caption font-semibold leading-4 text-foreground">
                  {power}
                </span>
              ) : null}
              {capacity ? (
                <span className="text-[0.6875rem] font-semibold leading-3 text-body">
                  <span className="sr-only">Puestos </span>
                  {capacity}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        {comparisonMetrics.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
            {comparisonMetrics.map(([label, value]) => (
              <StationListMetric key={label} label={label} value={value} />
            ))}
          </div>
        ) : null}
        {connectors.length > 0 || amenities.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 overflow-hidden text-caption font-medium leading-4 text-muted-foreground">
            {connectors.length > 0 ? <StationConnectorBadges connectors={connectors} /> : null}
            {connectors.length > 0 && amenities.length > 0 ? <span aria-hidden="true">·</span> : null}
            {amenities.length > 0 ? <StationListInlineValues label="Servicios" values={amenities} /> : null}
          </div>
        ) : null}
      </div>
    </li>
  )
}

function StationListMetric({ label, value }: { label: string; value: string }) {
  return (
    <span className="min-w-0 text-caption leading-4 text-body [overflow-wrap:anywhere]">
      <span className="font-medium text-muted-foreground">{label}</span>{' '}
      <span className="font-semibold text-foreground">{value}</span>
    </span>
  )
}

function StationConnectorBadges({ connectors }: { connectors: string[] }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      <span className="sr-only">Conectores</span>
      {connectors.map((connector) => (
        <StationConnectorBadge key={connector} connector={connector} />
      ))}
    </div>
  )
}

function StationListInlineValues({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5">
      <span className="sr-only">{label}</span>
      {values.map((value, index) => (
        <span key={value} className="inline-flex min-w-0 items-center gap-1">
          {index > 0 ? <span className="text-muted-foreground" aria-hidden="true">·</span> : null}
          <span className="break-words text-body [overflow-wrap:anywhere]">
            {value}
          </span>
        </span>
      ))}
    </div>
  )
}

function RouteMapCanvas({
  data,
  variant,
  density = 'default',
  selectedStationId,
  onStationSelect,
  detailStationId,
  onStationDetailClose,
}: {
  data: RouteMapData
  variant: 'compact' | 'expanded'
  density?: 'default' | 'mini'
  selectedStationId?: string | null
  onStationSelect?: (stationId: string | null) => void
  detailStationId?: string | null
  onStationDetailClose?: () => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const markerElementsRef = useRef<Record<string, HTMLElement>>({})
  const activeSelectedStationIdRef = useRef<string | null>(null)
  const [status, setStatus] = useState<'idle' | 'static' | 'failed'>('idle')
  const [internalSelectedStationId, setInternalSelectedStationId] = useState<string | null>(null)
  const isExpanded = variant === 'expanded'
  const usesDefaultStyle = !mapStyleUrl()
  const activeSelectedStationId = selectedStationId !== undefined ? selectedStationId : internalSelectedStationId
  const activeDetailStationId = detailStationId !== undefined ? detailStationId : null
  const detailStation = isExpanded
    ? data.stationPoints.find((station) => station.id === activeDetailStationId) ?? null
    : null
  const dataKey = useMemo(() => JSON.stringify({
    routeGeometry: data.routeGeometry,
    points: data.points.map((point) => [point.id, point.lat, point.lon, point.kind]),
  }), [data])
  const selectStation = useCallback((stationId: string | null) => {
    if (onStationSelect) {
      onStationSelect(stationId)
      return
    }
    setInternalSelectedStationId(stationId)
  }, [onStationSelect])

  useEffect(() => {
    activeSelectedStationIdRef.current = activeSelectedStationId
  }, [activeSelectedStationId])

  useEffect(() => {
    const container = containerRef.current
    if (!container || !data.routeGeometry || !canUseWebGl()) {
      setStatus('static')
      return
    }

    let disposed = false
    const markers: MapLibreMarker[] = []
    markerElementsRef.current = {}

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
          attributionControl: isExpanded ? { compact: true } : usesDefaultStyle ? false : { compact: true },
          interactive: isExpanded,
        })
        mapRef.current = map
        if (isExpanded) {
          map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
          window.requestAnimationFrame(() => collapseMapAttribution(containerRef.current))
        }
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
            paint: { 'line-color': '#ffffff', 'line-width': isExpanded ? 8 : density === 'mini' ? 10 : 9, 'line-opacity': 0.92 },
          })
          map.addLayer({
            id: 'route-line',
            type: 'line',
            source: 'route',
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': '#146c5f', 'line-width': isExpanded ? 4 : density === 'mini' ? 5.5 : 4.75 },
          })
          for (const point of data.points) {
            const isClickableStation = isExpanded && isStationMapPoint(point)
            const element = mapMarkerElement(point, isClickableStation, point.id === activeSelectedStationIdRef.current)
            markerElementsRef.current[point.id] = element
            if (isClickableStation) {
              element.addEventListener('click', () => selectStation(point.id))
            }
            const marker = new maplibregl.Marker({ element, anchor: 'center' })
              .setLngLat([point.lon, point.lat])
              .addTo(map)
            markers.push(marker)
          }
          const bounds = routeBounds(data)
          if (bounds) {
            map.fitBounds(bounds, {
              padding: mapFitPadding(variant, density),
              maxZoom: mapFitMaxZoom(variant, density),
              duration: 0,
            })
          }
          map.resize()
          if (isExpanded) {
            window.requestAnimationFrame(() => collapseMapAttribution(containerRef.current))
          }
        })
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
      markerElementsRef.current = {}
      mapRef.current?.remove()
      mapRef.current = null
    }
  }, [data, dataKey, density, isExpanded, selectStation, usesDefaultStyle, variant])

  useEffect(() => {
    for (const [stationId, element] of Object.entries(markerElementsRef.current)) {
      element.classList.toggle('a2ui-map-marker-selected', stationId === activeSelectedStationId)
    }

    if (!isExpanded || !activeSelectedStationId) {
      return
    }

    const selectedPoint = data.stationPoints.find((station) => station.id === activeSelectedStationId)
    if (!selectedPoint) {
      return
    }

    mapRef.current?.flyTo({
      center: [selectedPoint.lon, selectedPoint.lat],
      zoom: 10.2,
      duration: prefersReducedMotion() ? 0 : 280,
      essential: false,
    })
  }, [activeSelectedStationId, data.stationPoints, isExpanded])

  return (
    <div className={cn('a2ui-map-shell', isExpanded ? 'a2ui-map-shell-expanded' : 'a2ui-map-shell-compact', !isExpanded && density === 'mini' && 'a2ui-map-shell-mini')}>
      <div ref={containerRef} className={cn('a2ui-maplibre-canvas', status !== 'idle' && 'opacity-0')} aria-label={isExpanded ? 'Mapa interactivo de ruta' : 'Vista previa de ruta'} />
      {!isExpanded && usesDefaultStyle && status === 'idle' ? (
        <a className="a2ui-map-attribution" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" aria-label="Atribución de OpenStreetMap">
          © OSM
        </a>
      ) : null}
      {status !== 'idle' ? <StaticRouteMap data={data} selectedStationId={activeSelectedStationId} /> : null}
      {detailStation ? (
        <RouteMapStationDetails station={detailStation} onClose={onStationDetailClose ?? (() => selectStation(null))} />
      ) : null}
      {status === 'failed' ? (
        <span className="absolute left-3 top-3 rounded-md bg-surface px-2 py-1 text-xs font-medium text-muted-foreground shadow-sm">
          Vista estática
        </span>
      ) : null}
    </div>
  )
}

function mapFitPadding(variant: 'compact' | 'expanded', density: 'default' | 'mini') {
  if (variant === 'expanded') {
    return { top: 72, bottom: 220, left: 72, right: 72 }
  }
  if (density === 'mini') {
    return { top: 10, bottom: 10, left: 12, right: 12 }
  }
  return { top: 22, bottom: 22, left: 28, right: 28 }
}

function mapFitMaxZoom(variant: 'compact' | 'expanded', density: 'default' | 'mini') {
  if (variant === 'expanded') {
    return 11
  }
  return density === 'mini' ? 8.8 : 7.6
}

function StaticRouteMap({ data, selectedStationId }: { data: RouteMapData; selectedStationId?: string | null }) {
  const geometry = data.routeGeometry ?? schematicGeometry(data)
  const projected = projectedRoute(geometry, data.points)
  return (
    <svg className="a2ui-static-map" viewBox="0 0 640 280" role="img" aria-label="Vista de ruta">
      <rect width="640" height="280" rx="14" className="fill-[color-mix(in_oklch,var(--color-route-soft)_32%,var(--color-muted))]" />
      <path d={projected.path} className="fill-none stroke-white/90 stroke-[12] [stroke-linecap:round] [stroke-linejoin:round]" />
      <path d={projected.path} className="fill-none stroke-route stroke-[5] [stroke-linecap:round] [stroke-linejoin:round]" />
      {projected.points.map((point) => (
        <g key={point.id} transform={`translate(${point.x} ${point.y})`}>
          {point.id === selectedStationId ? (
            <circle r="14" className="fill-route/20 stroke-route stroke-[2]" />
          ) : null}
          <circle r={point.kind === 'primary' ? 9 : 7} className={point.kind === 'primary' ? 'fill-warning stroke-surface stroke-[3]' : 'fill-primary stroke-surface stroke-[3]'} />
          <text x={point.kind === 'destination' ? -10 : 10} y="-10" textAnchor={point.kind === 'destination' ? 'end' : 'start'} className="fill-foreground text-[18px] font-bold">
            {point.label}
          </text>
        </g>
      ))}
    </svg>
  )
}

function RouteMapStationDetails({ station, onClose }: { station: RouteMapPoint; onClose: () => void }) {
  const stationProps = station.station ?? mapPointStationProps(station)

  return (
    <div className="a2ui-map-station-popover">
      <StationDetailPanel station={stationProps} titleOverride={station.roleLabel} onClose={onClose} />
    </div>
  )
}

function mapPointStationProps(station: RouteMapPoint): Record<string, unknown> {
  return {
    stationName: station.label,
    connectorTypes: station.connectorLabels,
  }
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
    .map((station, index) => stationMapPoint(station, 'station', primary ? index + 1 : index))
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
    markerLabel: kind === 'primary' ? '1' : String(index + 1),
    capacityLabel: stationCapacity(item),
    evseRatioLabel: stationEvseRatio(item),
    powerLabel: isKnownNumber(item.powerKw) ? metric(item.powerKw, 'kW') : '',
    distanceLabel: isKnownNumber(item.distanceKm) ? metric(item.distanceKm, 'km') : '',
    detourLabel: isKnownNumber(item.detourMin) ? metric(item.detourMin, 'min') : '',
    priceLabel: stationPrice(item) === 'No disponible' ? '' : stationPrice(item),
    connectorLabels: connectorLabels(item.connectorTypes),
    station: item,
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

function mapLibreStyle() {
  return mapStyleUrl() || DEFAULT_MAP_STYLE_URL
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

function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

function collapseMapAttribution(container: HTMLElement | null) {
  const attribution = container?.querySelector<HTMLDetailsElement>('.maplibregl-ctrl-attrib.maplibregl-compact')
  if (!attribution) {
    return
  }
  attribution.open = false
  attribution.classList.remove('maplibregl-compact-show')
}

function mapMarkerElement(point: RouteMapPoint, isClickable = false, isSelected = false) {
  const element = document.createElement('div')
  element.className = `a2ui-map-marker a2ui-map-marker-${point.kind}${isSelected ? ' a2ui-map-marker-selected' : ''}`
  if (isClickable) {
    element.className += ' a2ui-map-marker-clickable'
    element.setAttribute('role', 'button')
    element.setAttribute('tabindex', '0')
    element.setAttribute('aria-label', `Ver ${point.label}`)
    element.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        element.click()
      }
    })
  }
  element.title = point.label
  const dot = document.createElement('span')
  dot.className = 'a2ui-map-marker-dot'
  dot.textContent = point.markerLabel ?? ''
  const label = document.createElement('span')
  label.className = 'a2ui-map-marker-label'
  label.textContent = isStationMapPoint(point) && point.evseRatioLabel ? point.evseRatioLabel : point.label
  element.append(dot, label)
  return element
}

function isStationMapPoint(point: RouteMapPoint) {
  return point.kind === 'primary' || point.kind === 'station'
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
  const actionItems = actions.map((action, index) => {
    const target = actionTarget(action)
    const isDisabled = bool(action.disabled) || target === null
    const isPrimary = text(action.priority, '') === 'primary'

    return { action, index, target, isDisabled, isPrimary }
  })
  const primaryActions = actionItems.filter((item) => item.isPrimary)
  const supportingActions = actionItems.filter((item) => !item.isPrimary)

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-2">
      {primaryActions.map((item) => (
        <ActionButtonItem
          key={`${text(item.action.label)}-${item.index}`}
          item={item}
          sourceComponentId={sourceComponentId}
          onActionEvent={onActionEvent}
        />
      ))}
      {supportingActions.length > 0 ? (
        <div className="flex min-w-0 max-w-full flex-wrap items-start gap-2">
          {supportingActions.map((item) => (
            <ActionButtonItem
              key={`${text(item.action.label)}-${item.index}`}
              item={item}
              sourceComponentId={sourceComponentId}
              onActionEvent={onActionEvent}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}

function ActionButtonItem({
  item,
  sourceComponentId,
  onActionEvent,
}: {
  item: {
    action: Record<string, unknown>
    index: number
    target: ActionTarget | null
    isDisabled: boolean
    isPrimary: boolean
  }
  sourceComponentId: string
  onActionEvent?: (name: string, context?: Record<string, unknown>, sourceComponentId?: string) => void
}) {
  const unavailableReason = text(item.action.reason, '') || 'Esta acción no está disponible en este contexto.'
  const shouldExplainUnavailable = Boolean((item.isDisabled && text(item.action.reason, '')) || (!bool(item.action.disabled) && item.target === null))

  return (
    <div className={cn('flex min-w-0 max-w-full flex-col gap-1', item.isPrimary ? 'w-full' : 'flex-none')}>
      <Button
        type="button"
        disabled={item.isDisabled}
        variant={item.isPrimary ? 'default' : 'ghost'}
        className={cn(
          'h-auto min-h-11 min-w-0 max-w-full whitespace-normal break-words px-3 py-2 leading-5 [text-wrap:balance]',
          item.isPrimary ? 'w-full font-bold' : 'w-auto px-2.5 text-body hover:text-foreground',
        )}
        onClick={() => handleAction(item.target, onActionEvent, sourceComponentId)}
      >
        {text(item.action.label)}
      </Button>
      {shouldExplainUnavailable ? (
        <p className="max-w-[18rem] text-xs leading-5 text-muted-foreground">{unavailableReason}</p>
      ) : null}
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
    <A2UICard
      icon={AlertTriangle}
      tone="neutral"
      title="No puedo mostrar una parte de la respuesta"
      subtitle="Esa parte se ocultó sin interrumpir la conversación."
      contentClassName="flex flex-col gap-2 text-sm text-muted-foreground"
    >
      <p>{safeFallbackMessage(message)}</p>
      <details className="text-xs">
        <summary className="cursor-pointer font-medium text-body">Detalle para soporte</summary>
        <code className="mt-1 block break-words">{type}</code>
      </details>
    </A2UICard>
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

function stationCapacity(item: Record<string, unknown>) {
  const evseRatio = stationEvseRatio(item)
  if (evseRatio) {
    return `${evseRatio} disponibles`
  }
  const evses = knownNumber(item.availableEvses)
  if (evses !== null) {
    return `${formatNumber(evses)} disponibles`
  }
  const totalEvses = stationTotalEvses(item)
  if (totalEvses !== null) {
    return `${formatNumber(totalEvses)} puestos`
  }
  return ''
}

function stationAvailabilityRows(item: Record<string, unknown>) {
  const availableEvses = knownNumber(item.availableEvses)
  const totalEvses = stationTotalEvses(item)
  return compactRows([
    availableEvses !== null ? ['Disponibles', formatNumber(availableEvses)] : null,
    totalEvses !== null ? ['Total', formatNumber(totalEvses)] : null,
    text(item.confidence, '') ? ['Confianza', text(item.confidence)] : null,
  ])
}

function stationPriceDetailRow(item: Record<string, unknown>): [string, string] | null {
  if (bool(item.priceIsEstimated)) {
    return knownNumber(item.pricePerKwhEur) === null ? null : ['Precio', 'Sin verificar']
  }
  return stationPriceRow(item)
}

function stationDetailNotes(item: Record<string, unknown>) {
  return compactParts([
    bool(item.priceIsEstimated)
      ? 'La tarifa recibida no está verificada; no la uso para comparar costes.'
      : '',
    uncertaintyText(item.uncertainty),
  ])
}

function stationListCapacity(item: Record<string, unknown>) {
  const evseRatio = stationEvseRatio(item)
  if (evseRatio) {
    return `${evseRatio} puestos`
  }
  const evses = knownNumber(item.availableEvses)
  if (evses !== null) {
    return `${formatNumber(evses)} puestos libres`
  }
  const totalEvses = stationTotalEvses(item)
  if (totalEvses !== null) {
    return `${formatNumber(totalEvses)} puestos`
  }
  return ''
}

function stationEvseRatio(item: Record<string, unknown>) {
  const availableEvses = knownNumber(item.availableEvses)
  const totalEvses = stationTotalEvses(item)
  if (availableEvses === null || totalEvses === null) {
    return ''
  }
  return `${formatNumber(availableEvses)}/${formatNumber(totalEvses)}`
}

function stationTotalEvses(item: Record<string, unknown>) {
  return knownNumber(item.totalEvses)
}

function connectorLabels(value: unknown) {
  return strings(value).map((item) => item.toUpperCase())
}

function manualLocationHint(fields: string[], { includeCoordinates = false }: { includeCoordinates?: boolean } = {}) {
  const normalized = fields.map((field) => field.trim()).filter(Boolean)
  const coordinatePattern = /coord|lat|lon/i
  const primaryFields = normalized.filter((field) => !coordinatePattern.test(field))
  const coordinateFields = normalized.length > primaryFields.length
  const visibleFields = (primaryFields.length > 0 ? primaryFields : ['ciudad', 'carretera o punto cercano']).map(sentenceCaseInline)
  const hint = `También puedes escribir ${spanishList(visibleFields)}.`
  return includeCoordinates && coordinateFields ? `${hint} Si ya las tienes, también sirven coordenadas.` : hint
}

function sentenceCaseInline(value: string) {
  return value ? `${value[0]?.toLocaleLowerCase('es-ES')}${value.slice(1)}` : value
}

function spanishList(values: string[]) {
  if (values.length <= 1) {
    return values[0] ?? ''
  }
  if (values.length === 2) {
    return `${values[0]} o ${values[1]}`
  }
  return `${values.slice(0, -1).join(', ')} o ${values[values.length - 1]}`
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

function stationTariffLabel(item: Record<string, unknown>) {
  if (bool(item.priceIsEstimated)) {
    return 'Sin verificar'
  }
  const min = knownNumber(item.pricePerKwhMinEur ?? item.minPricePerKwhEur ?? item.tariffMinEurPerKwh)
  const max = knownNumber(item.pricePerKwhMaxEur ?? item.maxPricePerKwhEur ?? item.tariffMaxEurPerKwh)
  const currency = text(item.currency, 'EUR').toUpperCase() === 'EUR' ? '€' : text(item.currency, 'EUR')
  if (min !== null && max !== null) {
    return min === max
      ? `${formatPrice(min)} ${currency}/kWh`
      : `${formatPrice(min)}-${formatPrice(max)} ${currency}/kWh`
  }
  const row = stationPriceRow(item)
  return row?.[1] ?? 'No disponible'
}

function stationPriceRow(item: Record<string, unknown>): [string, string] | null {
  const value = stationPrice(item)
  return value === 'No disponible' ? null : ['Precio', value]
}

function stationPriceListRow(item: Record<string, unknown>): [string, string] | null {
  if (bool(item.priceIsEstimated)) {
    return ['Precio', 'Sin verificar']
  }
  const row = stationPriceRow(item)
  return row ? [row[0], row[1].replace(' €/kWh', '€/kWh')] : null
}

function uncertaintyText(value: unknown) {
  const uncertainty = record(value)
  if (!uncertainty) {
    return ''
  }
  const body = text(uncertainty.text, '')
  const source = dataSourceLabel(uncertainty.source)
  const freshness = text(uncertainty.freshness, '')
  return compactParts([body, source ? `Fuente: ${source}.` : '', freshness ? `Actualización: ${freshness}.` : '']).join(' ')
}

function dataSourceLabel(value: unknown) {
  const source = text(value, '').trim().toLowerCase()
  if (!source || source === 'demo' || source === 'sample') {
    return ''
  }
  const labels: Record<string, string> = {
    plan_route: 'planificador de ruta',
    route_provider: 'proveedor de ruta',
    authorized_chargers: 'datos autorizados de carga',
    charger_import: 'datos autorizados de carga',
  }
  return labels[source] ?? text(value, '')
}

function compactRows(rows: Array<[string, string] | null>): Array<[string, string]> {
  return rows.filter((row): row is [string, string] => row !== null && row[1].trim().length > 0)
}

function compactParts(parts: string[]) {
  return parts.map((part) => part.trim()).filter(Boolean)
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

function compactDuration(durationText: unknown, durationMin: unknown) {
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
  return remaining > 0 ? `${hours}h ${remaining}` : `${hours}h`
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
  if (normalized.includes('a2ui') || normalized.includes('deepseek') || normalized.includes('json')) {
    return 'He ocultado una parte que no venía en un formato seguro. Puedes continuar corrigiendo la petición o reintentarla.'
  }
  return message || 'He ocultado una parte que no venía en un formato seguro.'
}
