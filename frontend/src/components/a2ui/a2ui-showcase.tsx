import { useMemo, useState } from 'react'

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
    focus: 'El conductor necesita una decision rapida, margen claro y una forma segura de corregir ubicacion.',
    blocks: [
      block('urgent-user', 'UserMessage', {
        text: 'Estoy en Zaragoza con 9%, no conozco la zona y necesito cargar ya.',
      }),
      block('urgent-location-request', 'LocationRequestCard', {
        reason: 'urgent_charge',
        title: 'Necesito tu ubicacion',
        body: 'Comparte una ubicacion aproximada o escribe ciudad y carretera para buscar cargadores cercanos.',
        precision: 'approximate',
        manualFields: ['Ciudad', 'Coordenadas', 'Carretera o salida'],
      }),
      block('urgent-location-detail', 'LocationDetailCard', {
        label: { label: 'Zaragoza, entorno urbano' },
        lat: 41.6488,
        lon: -0.8891,
        precision: 'approximate',
        context: 'Ubicacion aproximada usada para orientar la busqueda.',
        needsConfirmation: true,
      }),
      block('urgent-station', 'StationDetailCard', {
        title: 'Estación cercana',
        stationName: 'Demo Charge Urgente',
        address: 'Salida 245, entorno urbano',
        distanceKm: 7.6,
        powerKw: 150,
        availableEvses: 2,
        connectorTypes: ['CCS2', 'TYPE2'],
      }),
      block('urgent-risk', 'RiskExplanationCard', {
        level: 'alto',
        text: 'La bateria actual deja poco margen. Esta revision usa datos de muestra; no confirma disponibilidad ni precio.',
      }),
      block('urgent-actions', 'ActionButtons', {
        actions: [
          {
            label: 'Confirmar esta parada',
            priority: 'primary',
            event: { name: 'confirm_stop', context: { scenario: 'urgent' } },
          },
          {
            label: 'Buscar otra cercana',
            event: { name: 'find_alternative_stop', context: { scenario: 'urgent' } },
          },
        ],
      }),
    ],
  },
  {
    id: 'route',
    title: 'Ruta con parada comoda',
    focus: 'La experiencia debe explicar la parada principal, alternativas, riesgo y coste sin obligar a interpretar un mapa.',
    blocks: [
      block('route-assistant', 'AssistantMessage', {
        text: 'Voy a priorizar una parada con margen conservador y servicios utiles. Si faltan datos reales del proveedor, lo dire explicitamente.',
      }),
      block('route-trip', 'TripSummaryCard', {
        origin: { label: 'Zaragoza' },
        destination: { label: 'Valencia' },
        battery: 24,
        reserve: 12,
      }),
      block('route-summary', 'RouteSummaryCard', {
        distanceKm: 309,
        durationMin: 204,
        energyKwh: 55.6,
        arrivalBattery: 17,
      }),
      block('route-stop', 'StationDetailCard', {
        title: 'Estación recomendada',
        stationName: 'Kalmio demo HPC',
        address: 'Area de servicio La Plana',
        powerKw: 150,
        distanceKm: 118,
        detourMin: 6,
        availableEvses: 4,
        connectorTypes: ['CCS2'],
        amenities: ['RESTAURANT', 'TOILETS', 'WIFI', 'PARKING_LOT'],
      }),
      block('route-map', 'MapPreviewCard', {
        origin: { label: 'Zaragoza' },
        stop: { label: 'Teruel' },
        destination: { label: 'Valencia' },
        isSchematic: true,
        source: 'demo',
      }),
      block('route-alternative-stations', 'StationList', {
        title: 'Otras estaciones viables',
        stations: [
          {
            stationName: 'Demo Charge 1',
            address: 'Area Mudejar',
            powerKw: 100,
            distanceKm: 92,
            detourMin: 4,
            availableEvses: 2,
            connectorTypes: ['CCS2'],
            amenities: ['CAFE', 'TOILETS'],
          },
          {
            stationName: 'Demo Charge 2',
            address: 'Teruel norte',
            powerKw: 60,
            distanceKm: 147,
            detourMin: 9,
            connectorCount: 3,
            connectorTypes: ['TYPE2'],
            amenities: ['SUPERMARKET', 'PARKING_LOT'],
          },
        ],
      }),
      block('route-alternative-routes', 'AlternativeRoutesList', {
        routes: [
          { name: 'Ruta directa por A-23', deltaMin: 0 },
          { name: 'Ruta con parada mas comoda', deltaMin: 14 },
          { name: 'Ruta con mas margen de bateria', deltaMin: 22 },
        ],
      }),
      block('route-cost', 'CostComparisonCard', {
        best: { label: 'Parada con menor coste estimado' },
        estimatedCostEur: 18.7,
        savingEur: 4.2,
      }),
      block('route-preferences', 'PreferenceChips', {
        title: 'Preferencias',
        chips: ['Parada con restaurante', 'Menos desvio', 'Mas margen de bateria', 'Solo carga rapida'],
      }),
    ],
  },
  {
    id: 'destination',
    title: 'Llegada y estancia',
    focus: 'El conductor no necesita una parada inmediata; necesita saber que falta, que debe confirmar y como queda el plan al llegar.',
    blocks: [
      block('destination-user', 'UserMessage', {
        text: 'Llegare a un hotel en Valencia y estare dos noches. Quiero cargar sin perder la manana.',
      }),
      block('destination-question', 'ClarifyingQuestionCard', {
        question: 'Para cerrar el plan necesito un dato mas.',
        fields: ['Direccion del hotel', 'Bateria al llegar', 'Conector'],
      }),
      block('destination-charging', 'DestinationChargingCard', {
        destination: { label: 'Hotel Centro Valencia' },
        needsConfirmation: true,
      }),
      block('destination-stay', 'StayPlanningCard', {
        nights: 2,
        city: { label: 'Valencia' },
        recommendation: { label: 'Cargar al llegar y dejar margen para desplazamientos urbanos.' },
      }),
      block('destination-station', 'StationDetailCard', {
        title: 'Estación cerca del destino',
        stationName: 'Valencia Centro AC',
        address: 'Parking Centro Valencia',
        distanceKm: 0.6,
        powerKw: 22,
        availableEvses: 3,
        connectorTypes: ['TYPE2'],
      }),
      block('destination-actions', 'ActionButtons', {
        actions: [
          {
            label: 'Confirmar hotel',
            priority: 'primary',
            event: { name: 'confirm_destination', context: { scenario: 'destination' } },
          },
          {
            label: 'Abrir proveedor',
            functionCall: { call: 'openUrl', args: { url: 'https://kalmio.app' } },
          },
          {
            label: 'Reservar plaza',
            disabled: true,
            reason: 'La reserva no esta disponible en esta demo.',
          },
        ],
      }),
    ],
  },
  {
    id: 'fallback',
    title: 'Bloque no renderizable',
    focus: 'La experiencia debe fallar de forma minima y permitir que el chat continue.',
    blocks: [
      block('fallback-error', 'ErrorFallbackCard', {
        originalType: 'DemoBrokenCard',
        message: 'Bloque de demo no renderizable.',
      }),
    ],
  },
]

const uniqueComponentTypes = Array.from(
  new Set(scenarios.flatMap((scenario) => scenario.blocks.map((item) => item.type))),
)

export function A2UIShowcasePage() {
  const [showTechnical, setShowTechnical] = useState(false)
  const [lastAction, setLastAction] = useState<string | null>(null)
  const blockCount = useMemo(
    () => scenarios.reduce((total, scenario) => total + scenario.blocks.length, 0),
    [],
  )

  return (
    <section className="flex flex-col gap-5 pb-4">
      <div className="sticky top-0 z-10 -mx-6 border-b border-border bg-surface/95 px-6 py-3 backdrop-blur md:-mx-14 md:px-14">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-mono text-xs leading-4 text-muted-foreground">A2UI review surface</p>
            <h1 className="text-2xl font-semibold tracking-normal">Revision de experiencia</h1>
          </div>
          <Badge variant="secondary" className="shrink-0">
            {uniqueComponentTypes.length} tipos
          </Badge>
        </div>

        <div className="mt-3 flex items-center justify-between gap-3">
          <label className="flex min-w-0 items-center gap-2 text-xs leading-5 text-muted-foreground">
            <Switch
              aria-label="Mostrar metadatos A2UI"
              checked={showTechnical}
              onCheckedChange={setShowTechnical}
            />
            Mostrar IDs tecnicos
          </label>
          {lastAction ? (
            <span className="truncate text-right text-xs leading-5 text-muted-foreground">
              Accion: {lastAction}
            </span>
          ) : null}
        </div>
      </div>

      <div className="rounded-md border border-warning bg-warning-soft px-3 py-2 text-xs leading-5 text-foreground">
        Datos de muestra para revisar flujo, responsive y claridad. No representan disponibilidad, precio, estaciones reales ni una ruta calculada.
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {scenarios.map((scenario) => (
          <a
            key={scenario.id}
            href={`#${scenario.id}`}
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
          >
            {scenario.title}
          </a>
        ))}
      </div>

      <div className="flex flex-col gap-8">
        {scenarios.map((scenario, index) => (
          <article id={scenario.id} key={scenario.id} className="scroll-mt-24 space-y-3 border-t border-border pt-5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 space-y-1">
                <p className="font-mono text-xs leading-4 text-muted-foreground">
                  Escenario {index + 1}
                </p>
                <h2 className="text-xl font-semibold tracking-normal">{scenario.title}</h2>
                <p className="text-sm leading-6 text-body">{scenario.focus}</p>
              </div>
              <Badge variant="secondary" className="shrink-0">
                {scenario.blocks.length} bloques
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
              onLocationSubmit={(value) => setLastAction(`location:${value}`)}
              onManualLocationRequest={() => setLastAction('manual-location')}
            />
          </article>
        ))}
      </div>

      <div className="border-t border-border pt-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-semibold">Cobertura del catalogo</p>
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
    </section>
  )
}
