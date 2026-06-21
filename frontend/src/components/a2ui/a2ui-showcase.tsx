import { useMemo, useState } from 'react'

import { A2UIRenderer } from '@/components/a2ui/a2ui-renderer'
import { ChatPendingStatus } from '@/components/chat/chat-pending-status'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import type { A2UIBlock } from '@/lib/a2ui/types'

type ExperienceScenario = {
  id: string
  title: string
  focus: string
  blocks: A2UIBlock[]
}

function block(id: string, type: A2UIBlock['type'], props: A2UIBlock['props']): A2UIBlock {
  return { id, type, version: 1, props }
}

const scenarios: ExperienceScenario[] = [
  {
    id: 'urgent',
    title: 'Carga urgente',
    focus: 'El conductor necesita una decisión rápida, margen claro y una forma segura de corregir la ubicación.',
    blocks: [
      block('urgent-user', 'UserMessage', {
        text: 'Estoy en Zaragoza con 9%, no conozco la zona y necesito cargar ya.',
      }),
      block('urgent-risk-copy', 'AssistantMessage', {
        text: 'Con 9% el margen es bajo. Primero confirmaré la zona y después te mostraré un punto de carga cercano con acciones directas.',
      }),
      block('urgent-position-request', 'PositionRequestCard', {
        reason: 'urgent_charge',
        title: 'Necesito tu ubicación',
        body: 'Comparte una ubicación aproximada o escribe ciudad y carretera para buscar cargadores cercanos.',
        precision: 'approximate',
        manualFields: ['Ciudad', 'Coordenadas', 'Carretera o salida'],
      }),
      block('urgent-location-copy', 'AssistantMessage', {
        text: 'Uso Zaragoza, entorno urbano como aproximación. Esta revisión no confirma disponibilidad ni precio en vivo; si no es tu zona, dime ciudad, carretera o coordenadas y ajusto el punto.',
      }),
      block('urgent-station', 'StationPreviewCard', {
        title: 'Estación cercana',
        stationName: 'Punto de muestra Zaragoza salida 245',
        address: 'Salida 245, entorno urbano con acceso por vía de servicio',
        distanceKm: 7.6,
        powerKw: 150,
        availableEvses: 2,
        connectorTypes: ['CCS2', 'TYPE2'],
        lat: 41.6561,
        lon: -0.8773,
      }),
      block('urgent-actions', 'ActionButtons', {
        actions: [
          {
            label: 'Usar este punto',
            priority: 'primary',
            event: { name: 'confirm_stop', context: { scenario: 'urgent' } },
          },
          {
            label: 'Abrir ruta',
            functionCall: {
              call: 'openUrl',
              args: { url: 'https://www.google.com/maps/dir/?api=1&destination=41.6561,-0.8773' },
            },
          },
          {
            label: 'Buscar otra opción',
            event: { name: 'find_alternative_stop', context: { scenario: 'urgent' } },
          },
        ],
      }),
    ],
  },
  {
    id: 'route',
    title: 'Ruta con parada cómoda',
    focus: 'La experiencia debe explicar la parada principal, alternativas, riesgo y coste sin obligar a interpretar un mapa.',
    blocks: [
      block('route-assistant', 'AssistantMessage', {
        text: 'Zaragoza a Valencia con 24% de batería. Priorizaré una parada con margen conservador y servicios útiles; si faltan datos del proveedor, lo diré explícitamente.',
      }),
      block('route-summary', 'RouteSummaryCard', {
        distanceKm: 309,
        durationMin: 204,
        energyKwh: 55.6,
        arrivalBattery: 17,
        takeaway: 'Llegada estimada con margen utilizable.',
        uncertainty: {
          level: 'medium',
          text: 'La estimación depende del consumo real y del tráfico.',
        },
      }),
      block('route-stop', 'StationPreviewCard', {
        title: 'Estación recomendada',
        stationName: 'Punto de muestra La Plana',
        address: 'Área de servicio La Plana',
        takeaway: 'Mejor equilibrio entre margen, desvío y servicios.',
        why: 'Queda cerca de la ruta, tiene CCS2 y reduce el riesgo de llegar con batería baja.',
        powerKw: 150,
        pricePerKwhEur: 0.39,
        currency: 'EUR',
        priceIsEstimated: false,
        distanceKm: 118,
        detourMin: 6,
        availableEvses: 4,
        totalEvses: 8,
        connectorTypes: ['CCS2'],
        amenities: ['RESTAURANT', 'TOILETS', 'WIFI', 'PARKING_LOT'],
      }),
      block('route-map', 'MapPreviewCard', {
        origin: { label: 'Zaragoza', lat: 41.6488, lon: -0.8891 },
        destination: { label: 'Valencia', lat: 39.4699, lon: -0.3763 },
        primaryStation: {
          stationName: 'Punto de muestra La Plana',
          lat: 40.345,
          lon: -0.997,
          powerKw: 150,
          availableEvses: 4,
          totalEvses: 8,
          connectorTypes: ['CCS2'],
        },
        stations: [
          {
            stationName: 'Punto de muestra Mudéjar',
            lat: 40.583,
            lon: -1.268,
            powerKw: 100,
            availableEvses: 2,
            totalEvses: 4,
            connectorTypes: ['CCS2'],
          },
          {
            stationName: 'Punto de muestra Teruel norte',
            lat: 40.421,
            lon: -1.094,
            powerKw: 60,
            availableEvses: 1,
            totalEvses: 3,
            connectorTypes: ['TYPE2'],
          },
        ],
        routeGeometry: {
          type: 'LineString',
          coordinates: [
            [-0.8891, 41.6488],
            [-1.096, 41.143],
            [-1.105, 40.343],
            [-0.721, 39.861],
            [-0.3763, 39.4699],
          ],
        },
        corridorRadiusKm: 25,
        geometryPrecision: 'schematic',
      }),
      block('route-alternative-stations', 'StationList', {
        title: 'Otras estaciones viables',
        stations: [
          {
            stationName: 'Punto de muestra Mudéjar',
            address: 'Área Mudéjar',
            powerKw: 100,
            pricePerKwhEur: 0.52,
            currency: 'EUR',
            priceIsEstimated: false,
            distanceKm: 92,
            detourMin: 4,
            availableEvses: 2,
            totalEvses: 4,
            connectorTypes: ['CCS2'],
            amenities: ['CAFE', 'TOILETS'],
          },
          {
            stationName: 'Punto de muestra Teruel norte',
            address: 'Teruel norte',
            powerKw: 60,
            distanceKm: 147,
            detourMin: 9,
            availableEvses: 1,
            totalEvses: 3,
            connectorTypes: ['TYPE2'],
            amenities: ['SUPERMARKET', 'PARKING_LOT'],
          },
        ],
      }),
      block('route-cost', 'CostComparisonCard', {
        best: { label: 'Punto de muestra La Plana' },
        takeaway: 'Tarifa más baja entre las opciones verificadas.',
        why: 'La comparación solo se muestra cuando ambas tarifas están verificadas.',
        pricePerKwhEur: 0.39,
        comparedWith: { label: 'Punto de muestra Mudéjar' },
        comparedWithPricePerKwhEur: 0.52,
        savingPerKwhEur: 0.13,
        currency: 'EUR',
        priceIsEstimated: false,
      }),
      block('route-preferences', 'PreferenceChips', {
        title: 'Preferencias',
        chips: ['Parada con restaurante', 'Menos desvío', 'Más margen de batería', 'Solo carga rápida'],
      }),
    ],
  },
  {
    id: 'destination',
    title: 'Llegada y estancia',
    focus: 'El conductor no necesita una parada inmediata; necesita saber qué falta, qué debe confirmar y cómo queda el plan al llegar.',
    blocks: [
      block('destination-user', 'UserMessage', {
        text: 'Llegaré a un hotel en Valencia y estaré dos noches. Quiero cargar sin perder la mañana.',
      }),
      block('destination-question', 'AssistantMessage', {
        text: 'Para cerrar el plan necesito dirección del hotel, batería al llegar y conector.',
      }),
      block('destination-explanation', 'AssistantMessage', {
        text: 'El hotel exacto no está confirmado. Uso esta zona como aproximación y conviene confirmar acceso, tarifa y disponibilidad antes de depender de estos resultados.',
      }),
      block('destination-station', 'StationPreviewCard', {
        title: 'Estación cerca del destino',
        stationName: 'Valencia Centro AC',
        address: 'Parking Centro Valencia',
        distanceKm: 0.6,
        powerKw: 22,
        availableEvses: 3,
        connectorTypes: ['TYPE2'],
        lat: 39.4723,
        lon: -0.3768,
      }),
      block('destination-actions', 'ActionButtons', {
        actions: [
          {
            label: 'Usar este punto',
            priority: 'primary',
            event: { name: 'confirm_destination', context: { scenario: 'destination' } },
          },
          {
            label: 'Abrir ruta',
            functionCall: {
              call: 'openUrl',
              args: { url: 'https://www.google.com/maps/dir/?api=1&destination=39.4723,-0.3768' },
            },
          },
          {
            label: 'Reservar plaza',
            disabled: true,
            reason: 'La reserva todavía no está disponible.',
          },
        ],
      }),
    ],
  },
  {
    id: 'fallback',
    title: 'Respuesta parcial',
    focus: 'La experiencia debe fallar de forma mínima y permitir que el chat continúe.',
    blocks: [
      block('fallback-error', 'ErrorFallbackCard', {
        originalType: 'BloqueDeMuestra',
        message: 'Una parte de esta respuesta no se pudo mostrar.',
      }),
    ],
  },
]

const uniqueComponentTypes = Array.from(
  new Set(scenarios.flatMap((scenario) => scenario.blocks.map((item) => item.type))),
)

const componentCases = uniqueComponentTypes.map((type) => {
  const scenario = scenarios.find((item) => item.blocks.some((blockItem) => blockItem.type === type))
  const sample = scenario?.blocks.find((blockItem) => blockItem.type === type)

  return {
    id: String(type),
    type: String(type),
    scenarioTitle: scenario?.title ?? 'Sin escenario',
    focus: componentFocus(String(type)),
    block: sample ? { ...sample, id: `component-${sample.type}` } : block(`component-${type}`, type, {}),
  }
})

function componentFocus(type: string) {
  const focusByType: Record<string, string> = {
    AssistantMessage: 'Debe sonar como copiloto: breve, honesto y sin convertir la respuesta en un panel técnico.',
    UserMessage: 'Debe mantener claro qué dijo el conductor sin competir con la recomendación del asistente.',
    RouteSummaryCard: 'Debe explicar esfuerzo, duración y llegada con números legibles en móvil.',
    StationPreviewCard: 'Debe ser una recomendación escaneable que abre el detalle completo de la estación.',
    StationDetailCard: 'Debe estructurar toda la información disponible de una estación sin prometer disponibilidad ni precios no verificados.',
    StationList: 'Debe permitir comparar alternativas rápido sin obligar a leer párrafos largos.',
    CostComparisonCard: 'Debe mostrar ahorro solo cuando el precio está verificado y dejar clara la comparación.',
    MapPreviewCard: 'Debe apoyar la ruta, no convertirse en la tarea principal del conductor.',
    ActionButtons: 'Debe separar acción primaria, corrección y acciones bloqueadas sin ambigüedad.',
    PositionRequestCard: 'Debe obtener ubicación con permiso explícito y ofrecer alternativa manual equivalente.',
    PreferenceChips: 'Debe ofrecer correcciones rápidas con contexto visible, no aparecer como botones sueltos.',
    ErrorFallbackCard: 'Debe fallar de forma tranquila: ocultar lo inseguro y mantener vivo el chat.',
  }

  return focusByType[type] ?? 'Bloque de respuesta renderizado de forma aislada para revisar encaje visual y estados.'
}

const catalogStats = [
  ['Dirección visual', 'Agentic Signal'],
  ['Componentes', `${uniqueComponentTypes.length} tipos`],
  ['Escenarios', String(scenarios.length)],
  ['Contrato A2UI', 'v0.9.1'],
] as const

export function A2UIShowcasePage() {
  const [viewMode, setViewMode] = useState<'components' | 'scenarios'>('scenarios')
  const [reviewLayout, setReviewLayout] = useState<'detail' | 'mobile-grid'>('detail')
  const [showTechnical, setShowTechnical] = useState(false)
  const [lastAction, setLastAction] = useState<string | null>(null)
  const blockCount = useMemo(
    () => scenarios.reduce((total, scenario) => total + scenario.blocks.length, 0),
    [],
  )

  return (
    <section className="a2ui-showcase-page flex flex-col gap-5 pb-4">
      <div className="sticky top-0 z-10 -mx-6 border-b border-border bg-background/95 px-6 py-4 backdrop-blur md:-mx-14 md:px-14">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="default">Agentic Signal</Badge>
              <Badge variant="secondary">Catálogo v1.0</Badge>
            </div>
            <div className="space-y-1">
              <h1 className="text-2xl font-semibold tracking-normal">Catálogo A2UI</h1>
              <p className="max-w-3xl text-sm leading-6 text-body">
                Componentes dinámicos permitidos para respuestas de viaje EV. Esta página revisa cómo se ven con la dirección visual elegida y mantiene los datos de muestra separados del contrato real.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 lg:w-[28rem]">
            {catalogStats.map(([label, value]) => (
              <div key={label} className="rounded-md border border-border bg-surface px-3 py-2">
                <p className="text-caption font-medium leading-4 text-muted-foreground">{label}</p>
                <p className="mt-1 text-sm font-semibold leading-5 text-foreground">{value}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2">
            <div className="flex rounded-full bg-muted p-1" aria-label="Modo de revisión">
              <Button
                type="button"
                variant={viewMode === 'components' ? 'default' : 'ghost'}
                size="sm"
                className="h-8 rounded-full px-3"
                onClick={() => setViewMode('components')}
              >
                Componentes
              </Button>
              <Button
                type="button"
                variant={viewMode === 'scenarios' ? 'default' : 'ghost'}
                size="sm"
                className="h-8 rounded-full px-3"
                onClick={() => setViewMode('scenarios')}
              >
                Escenarios
              </Button>
            </div>
            <div className="flex rounded-full bg-muted p-1" aria-label="Presentación">
              <Button
                type="button"
                variant={reviewLayout === 'detail' ? 'default' : 'ghost'}
                size="sm"
                className="h-8 rounded-full px-3"
                onClick={() => setReviewLayout('detail')}
              >
                Detalle
              </Button>
              <Button
                type="button"
                variant={reviewLayout === 'mobile-grid' ? 'default' : 'ghost'}
                size="sm"
                className="h-8 rounded-full px-3"
                onClick={() => setReviewLayout('mobile-grid')}
              >
                Galería M
              </Button>
            </div>
          </div>
          <label className="flex min-w-0 items-center gap-2 text-xs leading-5 text-muted-foreground">
            <Switch
              aria-label="Mostrar datos técnicos"
              checked={showTechnical}
              onCheckedChange={setShowTechnical}
            />
            Mostrar datos técnicos
          </label>
          {lastAction ? (
            <span className="truncate text-right text-xs leading-5 text-muted-foreground">
              Acción: {lastAction}
            </span>
          ) : null}
        </div>
      </div>

      <div className="flex flex-col gap-2 rounded-md border border-warning bg-warning-soft px-3 py-2 text-xs leading-5 text-foreground sm:flex-row sm:items-start">
        <Badge variant="warning" className="shrink-0 border-foreground/10 bg-surface">
          Muestra
        </Badge>
        <p>
          Estos datos sirven para revisar flujo, responsive y claridad. No representan disponibilidad, precio, estaciones reales ni una ruta calculada.
        </p>
      </div>

      <article id="chat-waiting" className="scroll-mt-28 rounded-md border border-border bg-surface">
        <div className="border-b border-border px-3 py-2">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-mono text-xs leading-4 text-muted-foreground">Estado operativo</p>
              <h2 className="text-sm font-semibold leading-5 tracking-normal">Espera del chat</h2>
            </div>
            <Badge variant="secondary" className="shrink-0">
              Nuevo
            </Badge>
          </div>
          <p className="mt-1 text-xs leading-5 text-body">
            Esto es lo que ve el conductor después de enviar un mensaje mientras Kalmio resuelve la respuesta.
          </p>
        </div>
        <div className="mx-auto flex w-full max-w-[23.4375rem] flex-col gap-3 bg-background px-3 py-4">
          <A2UIRenderer
            blocks={[
              block('waiting-preview-user', 'UserMessage', {
                text: 'Estoy en Córdoba con un 18% y CCS2.',
              }),
            ]}
          />
          <ChatPendingStatus messageIndex={2} />
        </div>
      </article>

      <div className="flex flex-wrap gap-2">
        <a
          href="#chat-waiting"
          className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
        >
          Espera del chat
        </a>
        {(viewMode === 'components' ? componentCases : scenarios).map((item) => (
          <a
            key={item.id}
            href={`#${item.id}`}
            className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
          >
            {'type' in item ? item.type : item.title}
          </a>
        ))}
      </div>

      {reviewLayout === 'mobile-grid' ? (
        <MobileGridReview
          items={viewMode === 'components' ? componentCases : scenarios}
          mode={viewMode}
          showTechnical={showTechnical}
          onChipClick={(value) => setLastAction(`chip:${value}`)}
          onActionEvent={(name) => setLastAction(`event:${name}`)}
          onPositionSubmit={(value) => setLastAction(`position:${value}`)}
          onManualPositionRequest={() => setLastAction('manual-position')}
        />
      ) : viewMode === 'components' ? (
        <div className="flex flex-col gap-7">
          {componentCases.map((item) => (
            <article id={item.id} key={item.id} className="scroll-mt-28 space-y-3 border-t border-border pt-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <p className="font-mono text-xs leading-4 text-muted-foreground">{item.scenarioTitle}</p>
                  <h2 className="break-words text-xl font-semibold tracking-normal">{item.type}</h2>
                  <p className="text-sm leading-6 text-body">{item.focus}</p>
                </div>
                <Badge variant="secondary" className="shrink-0 font-mono text-[0.68rem]">
                  Vista aislada
                </Badge>
              </div>

              {showTechnical ? (
                <Badge variant="secondary" className="font-mono text-[0.68rem]">
                  {item.block.id}
                </Badge>
              ) : null}

              <A2UIRenderer
                blocks={[item.block]}
                onChipClick={(value) => setLastAction(`chip:${value}`)}
                onActionEvent={(name) => setLastAction(`event:${name}`)}
                onPositionSubmit={(value) => setLastAction(`position:${value}`)}
                onManualPositionRequest={() => setLastAction('manual-position')}
              />
            </article>
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-8">
          {scenarios.map((scenario, index) => (
            <article id={scenario.id} key={scenario.id} className="scroll-mt-28 space-y-3 border-t border-border pt-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <p className="font-mono text-xs leading-4 text-muted-foreground">
                    Escenario {index + 1}
                  </p>
                  <h2 className="text-xl font-semibold tracking-normal">{scenario.title}</h2>
                  <p className="text-sm leading-6 text-body">{scenario.focus}</p>
                </div>
                <Badge variant="secondary" className="shrink-0">
                  {showTechnical
                    ? countLabel(scenario.blocks.length, 'bloque', 'bloques')
                    : countLabel(scenario.blocks.length, 'parte', 'partes')}
                </Badge>
              </div>

              {showTechnical ? (
                <div className="flex flex-wrap gap-1.5">
                  {scenario.blocks.map((item) => (
                    <Badge key={item.id} variant="secondary" className="font-mono text-[0.68rem]">
                      {item.type}
                    </Badge>
                  ))}
                </div>
              ) : null}

              <A2UIRenderer
                blocks={scenario.blocks}
                onChipClick={(value) => setLastAction(`chip:${value}`)}
                onActionEvent={(name) => setLastAction(`event:${name}`)}
                onPositionSubmit={(value) => setLastAction(`position:${value}`)}
                onManualPositionRequest={() => setLastAction('manual-position')}
              />
            </article>
          ))}
        </div>
      )}

      {showTechnical ? (
        <div className="border-t border-border pt-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold">Cobertura del catálogo</p>
            <span className="text-xs text-muted-foreground">
              {blockCount} bloques / {uniqueComponentTypes.length} tipos
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {uniqueComponentTypes.map((type) => (
              <Badge key={type} variant="secondary" className="font-mono text-[0.68rem]">
                {type}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  )
}

type ShowcaseActions = {
  onChipClick: (value: string) => void
  onActionEvent: (name: string) => void
  onPositionSubmit: (value: string) => void
  onManualPositionRequest: () => void
}

type ComponentCase = (typeof componentCases)[number]

function MobileGridReview({
  items,
  mode,
  showTechnical,
  onChipClick,
  onActionEvent,
  onPositionSubmit,
  onManualPositionRequest,
}: {
  items: ComponentCase[] | ExperienceScenario[]
  mode: 'components' | 'scenarios'
  showTechnical: boolean
} & ShowcaseActions) {
  return (
    <div className="mr-auto grid w-full max-w-[82.25rem] grid-cols-[repeat(auto-fit,minmax(20rem,1fr))] items-start gap-3 pb-2">
      {items.map((item) => {
        const isComponent = mode === 'components'
        const title = isComponent ? (item as ComponentCase).type : (item as ExperienceScenario).title
        const subtitle = isComponent ? (item as ComponentCase).scenarioTitle : 'Escenario completo'
        const focus = item.focus
        const blocks = isComponent ? [(item as ComponentCase).block] : (item as ExperienceScenario).blocks

        return (
          <article id={item.id} key={item.id} className="scroll-mt-28 rounded-lg border border-border bg-surface">
            <div className="border-b border-border bg-muted px-3 py-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate font-mono text-[0.68rem] leading-4 text-muted-foreground">
                    {subtitle}
                  </p>
                  <h2 className="truncate text-sm font-semibold leading-5 tracking-normal">{title}</h2>
                </div>
                <Badge variant="secondary" className="shrink-0 font-mono text-[0.68rem]">
                  M
                </Badge>
              </div>
              <p className="mt-1 line-clamp-2 text-xs leading-5 text-body">{focus}</p>
              {showTechnical ? (
                <div className="mt-2 flex flex-wrap gap-1">
                  {blocks.map((blockItem) => (
                    <Badge key={blockItem.id} variant="secondary" className="font-mono text-[0.62rem]">
                      {blockItem.type}
                    </Badge>
                  ))}
                </div>
              ) : null}
            </div>

            <div className="mx-auto w-full max-w-[23.4375rem] bg-background px-3 py-3">
              <A2UIRenderer
                blocks={blocks}
                onChipClick={onChipClick}
                onActionEvent={onActionEvent}
                onPositionSubmit={onPositionSubmit}
                onManualPositionRequest={onManualPositionRequest}
              />
            </div>
          </article>
        )
      })}
    </div>
  )
}

function countLabel(count: number, singular: string, plural: string) {
  return `${count} ${count === 1 ? singular : plural}`
}
