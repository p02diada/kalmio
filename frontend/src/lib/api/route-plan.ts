import { csrfHeaders, ensureCsrfCookie } from '@/lib/api/auth'
import { API_BASE_URL } from '@/lib/api/config'
import {
  assertRecord,
  errorDetail,
  readArray,
  readBoolean,
  readNullableNumber,
  readNullableString,
  readNumber,
  readString,
} from '@/lib/api/validation'

export type CoordinatePayload = {
  lat: number
  lon: number
}

export type RoutePlanRequest = {
  origin: CoordinatePayload
  destination: CoordinatePayload
  origin_label: string
  destination_label: string
  corridor_radius_km: number
}

export type RoutePlanStation = {
  id: number
  external_id: string
  name: string
  power_kw: number
  connector: string
  available_connectors: number
  distance_to_route_km: number
  estimated_access_min: number
  price_eur_kwh: number | null
  price_is_estimated: boolean
  latitude: number
  longitude: number
  score: number
  reasons: string[]
}

export type RoutePlanResponse = {
  id: string | null
  created_at: string | null
  planning_level: 'ev_plan' | 'chargers_only'
  origin_label: string
  destination_label: string
  distance_km: number
  duration_min: number
  energy_kwh: number | null
  arrival_battery_percent: number | null
  recommendation: RoutePlanStation
  alternatives: RoutePlanStation[]
  warnings: string[]
}

export function buildRoutePlanRequest(
  form: RoutePlanFormValues,
): RoutePlanRequest {
  return {
    origin: {
      lat: parseBoundedNumber(form.originLat, 'latitud origen', -90, 90),
      lon: parseBoundedNumber(form.originLon, 'longitud origen', -180, 180),
    },
    destination: {
      lat: parseBoundedNumber(form.destinationLat, 'latitud destino', -90, 90),
      lon: parseBoundedNumber(form.destinationLon, 'longitud destino', -180, 180),
    },
    origin_label: cleanLabel(form.originLabel, 'Origen'),
    destination_label: cleanLabel(form.destinationLabel, 'Destino'),
    corridor_radius_km: parseBoundedNumber(form.corridorRadiusKm, 'radio de corredor', 0.1, 100),
  }
}

export type RoutePlanFormValues = {
  originLabel: string
  originLat: string
  originLon: string
  destinationLabel: string
  destinationLat: string
  destinationLon: string
  corridorRadiusKm: string
}

export async function requestRoutePlan(payload: RoutePlanRequest): Promise<RoutePlanResponse> {
  await ensureCsrfCookie()
  const response = await fetch(`${API_BASE_URL}/api/plans/route`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...csrfHeaders(),
    },
    body: JSON.stringify(payload),
  })

  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(errorDetail(body, `Route plan failed with ${response.status}`))
  }

  return parseRoutePlanResponse(body)
}

export async function listRoutePlans(): Promise<RoutePlanResponse[]> {
  const response = await fetch(`${API_BASE_URL}/api/plans/route`, {
    credentials: 'include',
  })
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(errorDetail(body, `Route plans request failed with ${response.status}`))
  }

  if (!Array.isArray(body)) {
    throw new Error('Route plans: respuesta inválida.')
  }
  return body.map((item) => parseRoutePlanResponse(item))
}

function cleanLabel(value: string, fallback: string): string {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : fallback
}

function parseBoundedNumber(value: string, label: string, min: number, max: number): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) {
    throw new Error(`Introduce un valor válido para ${label}.`)
  }
  if (parsed < min || parsed > max) {
    throw new Error(`Introduce ${label} entre ${min} y ${max}.`)
  }
  return parsed
}

function parseRoutePlanResponse(body: unknown): RoutePlanResponse {
  const value = assertRecord(body, 'Route plan')
  return {
    id: readNullableString(value, 'id', 'Route plan'),
    created_at: readNullableString(value, 'created_at', 'Route plan'),
    planning_level: readPlanningLevel(value),
    origin_label: readString(value, 'origin_label', 'Route plan'),
    destination_label: readString(value, 'destination_label', 'Route plan'),
    distance_km: readNumber(value, 'distance_km', 'Route plan'),
    duration_min: readNumber(value, 'duration_min', 'Route plan'),
    energy_kwh: readNullableNumber(value, 'energy_kwh', 'Route plan'),
    arrival_battery_percent: readNullableNumber(value, 'arrival_battery_percent', 'Route plan'),
    recommendation: parseRoutePlanStation(value.recommendation),
    alternatives: readArray(value, 'alternatives', 'Route plan').map((item) => parseRoutePlanStation(item)),
    warnings: readArray(value, 'warnings', 'Route plan').map((item) => {
      if (typeof item !== 'string') {
        throw new Error('Route plan: warnings inválido.')
      }
      return item
    }),
  }
}

function readPlanningLevel(value: Record<string, unknown>): RoutePlanResponse['planning_level'] {
  const planningLevel = readString(value, 'planning_level', 'Route plan')
  if (planningLevel !== 'ev_plan' && planningLevel !== 'chargers_only') {
    throw new Error('Route plan: planning_level inválido.')
  }
  return planningLevel
}

function parseRoutePlanStation(body: unknown): RoutePlanStation {
  const value = assertRecord(body, 'Route plan station')
  const reasons = readArray(value, 'reasons', 'Route plan station').map((item) => {
    if (typeof item !== 'string') {
      throw new Error('Route plan station: reasons inválido.')
    }
    return item
  })
  return {
    id: readNumber(value, 'id', 'Route plan station'),
    external_id: readString(value, 'external_id', 'Route plan station'),
    name: readString(value, 'name', 'Route plan station'),
    power_kw: readNumber(value, 'power_kw', 'Route plan station'),
    connector: readString(value, 'connector', 'Route plan station'),
    available_connectors: readNumber(value, 'available_connectors', 'Route plan station'),
    distance_to_route_km: readNumber(value, 'distance_to_route_km', 'Route plan station'),
    estimated_access_min: readNumber(value, 'estimated_access_min', 'Route plan station'),
    price_eur_kwh: readNullableNumber(value, 'price_eur_kwh', 'Route plan station'),
    price_is_estimated: readBoolean(value, 'price_is_estimated', 'Route plan station'),
    latitude: readNumber(value, 'latitude', 'Route plan station'),
    longitude: readNumber(value, 'longitude', 'Route plan station'),
    score: readNumber(value, 'score', 'Route plan station'),
    reasons,
  }
}
