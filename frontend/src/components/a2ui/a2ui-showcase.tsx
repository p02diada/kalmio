import { useState } from 'react'

import { A2UIRenderer } from '@/components/a2ui/a2ui-renderer'
import { Badge } from '@/components/ui/badge'
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
            label: 'Elegir esta parada',
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
    focus: 'La experiencia debe mostrar el corredor, estaciones cercanas, riesgo y coste sin obligar a interpretar pins.',
    blocks: [
      block('route-assistant', 'AssistantMessage', {
        text: 'Zaragoza a Valencia con 24% de batería. Mostraré el corredor con estaciones cercanas y marcaré lo que no pueda validar con los datos disponibles.',
      }),
      block('route-plan', 'RouteCorridorCard', {
        distanceKm: 309,
        durationMin: 204,
        energyKwh: null,
        arrivalBattery: null,
        takeaway: 'Corredor con puntos de carga trazados.',
        uncertainty: {
          level: 'medium',
          text: 'La batería de llegada no se valida sin consumo o perfil completo del vehículo.',
        },
        origin: { label: 'Zaragoza', lat: 41.6488, lon: -0.8891 },
        destination: { label: 'Valencia', lat: 39.4699, lon: -0.3763 },
        stations: [
          {
            stationName: 'Punto de muestra La Plana',
            address: 'Área de servicio La Plana',
            lat: 40.345,
            lon: -0.997,
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
          },
          {
            stationName: 'Punto de muestra Mudéjar',
            lat: 40.583,
            lon: -1.268,
            powerKw: 100,
            pricePerKwhEur: 0.43,
            currency: 'EUR',
            priceIsEstimated: false,
            distanceKm: 136,
            detourMin: 9,
            availableEvses: 2,
            totalEvses: 4,
            connectorTypes: ['CCS2'],
          },
          {
            stationName: 'Punto de muestra Teruel norte',
            lat: 40.421,
            lon: -1.094,
            powerKw: 60,
            pricePerKwhEur: 0.31,
            currency: 'EUR',
            priceIsEstimated: false,
            distanceKm: 125,
            detourMin: 4,
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
      block('route-station-detail', 'StationDetailCard', {
        stationName: 'Punto de muestra La Plana',
        address: 'Área de servicio La Plana',
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
            label: 'Elegir este punto de carga',
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
    focus: componentFocus(String(type)),
    block: sample ? { ...sample, id: `component-${sample.type}` } : block(`component-${type}`, type, {}),
  }
})

function componentFocus(type: string) {
  const focusByType: Record<string, string> = {
    AssistantMessage: 'Debe sonar como copiloto: breve, honesto y sin convertir la respuesta en un panel técnico.',
    UserMessage: 'Debe mantener claro qué dijo el conductor sin competir con la recomendación del asistente.',
    RouteCorridorCard: 'Debe mostrar ruta y estaciones cercanas al corredor sin convertirlo en una recomendación única.',
    StationPreviewCard: 'Debe ser una recomendación escaneable que abre el detalle completo de la estación.',
    StationDetailCard: 'Debe estructurar toda la información disponible de una estación sin prometer disponibilidad ni precios no verificados.',
    StationList: 'Debe permitir comparar alternativas rápido sin obligar a leer párrafos largos.',
    ActionButtons: 'Debe separar acción primaria, corrección y acciones bloqueadas sin ambigüedad.',
    PositionRequestCard: 'Debe obtener ubicación con permiso explícito y ofrecer alternativa manual equivalente.',
    PreferenceChips: 'Debe ofrecer correcciones rápidas con contexto visible, no aparecer como botones sueltos.',
    ErrorFallbackCard: 'Debe fallar de forma tranquila: ocultar lo inseguro y mantener vivo el chat.',
  }

  return focusByType[type] ?? 'Bloque de respuesta renderizado de forma aislada para revisar encaje visual y estados.'
}

export function A2UIShowcasePage() {
  const [showTechnical, setShowTechnical] = useState(false)
  const [lastAction, setLastAction] = useState<string | null>(null)

  return (
    <section className="a2ui-showcase-page flex flex-col gap-4 pb-4">
      <div className="-mx-4 border-b border-border bg-background/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 md:sticky md:top-0 md:z-10 md:-mx-14 md:px-14">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="default">Agentic Signal</Badge>
              <Badge variant="secondary">Catálogo v1.0</Badge>
            </div>
            <h1 className="mt-2 text-xl font-semibold leading-7 tracking-normal">Catálogo A2UI</h1>
            <p className="text-xs leading-5 text-muted-foreground">
              {uniqueComponentTypes.length} componentes · contrato v0.9.1
            </p>
          </div>
          <label className="flex shrink-0 items-center gap-2 text-xs leading-5 text-muted-foreground">
            <Switch
              aria-label="Mostrar datos técnicos"
              checked={showTechnical}
              onCheckedChange={setShowTechnical}
            />
            Datos
          </label>
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

      <div className="flex flex-wrap gap-2">
        {componentCases.map((item) => (
          <a
            key={item.id}
            href={`#${item.id}`}
            className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
          >
            {item.type}
          </a>
        ))}
      </div>

      {lastAction ? (
        <p className="text-xs leading-5 text-muted-foreground">Acción: {lastAction}</p>
      ) : null}

      <ComponentCatalogGrid
        items={componentCases}
        showTechnical={showTechnical}
        onChipClick={(value) => setLastAction(`chip:${value}`)}
        onActionEvent={(name) => setLastAction(`event:${name}`)}
        onPositionSubmit={(value) => setLastAction(`position:${value}`)}
        onManualPositionRequest={() => setLastAction('manual-position')}
      />

      {showTechnical ? (
        <div className="border-t border-border pt-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold">Cobertura del catálogo</p>
            <span className="text-xs text-muted-foreground">
              {uniqueComponentTypes.length} componentes
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

function ComponentCatalogGrid({
  items,
  showTechnical,
  onChipClick,
  onActionEvent,
  onPositionSubmit,
  onManualPositionRequest,
}: {
  items: ComponentCase[]
  showTechnical: boolean
} & ShowcaseActions) {
  return (
    <div className="grid w-full grid-cols-1 items-start gap-3 pb-2 sm:grid-cols-[repeat(auto-fit,minmax(21.5rem,23.4375rem))] sm:justify-center lg:justify-start">
      {items.map((item) => (
        <article id={item.id} key={item.id} className="scroll-mt-28 rounded-lg border border-border bg-surface">
          <div className="border-b border-border bg-muted px-3 py-2">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h2 className="truncate text-sm font-semibold leading-5 tracking-normal">{item.type}</h2>
              </div>
              <Badge variant="secondary" className="hidden shrink-0 font-mono text-[0.68rem] sm:inline-flex">
                M
              </Badge>
            </div>
            {showTechnical ? (
              <div className="mt-2 flex flex-wrap gap-1">
                <Badge variant="secondary" className="font-mono text-[0.62rem]">
                  {item.block.id}
                </Badge>
                <Badge variant="secondary" className="font-mono text-[0.62rem]">
                  {item.block.type}
                </Badge>
              </div>
            ) : null}
          </div>

          <div className="w-full bg-background px-3 py-3 sm:mx-auto sm:max-w-[23.4375rem]">
            <A2UIRenderer
              blocks={[item.block]}
              onChipClick={onChipClick}
              onActionEvent={onActionEvent}
              onPositionSubmit={onPositionSubmit}
              onManualPositionRequest={onManualPositionRequest}
            />
            {showTechnical ? (
              <p className="mt-2 text-xs leading-5 text-body">{item.focus}</p>
            ) : null}
          </div>
        </article>
      ))}
    </div>
  )
}
