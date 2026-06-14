import type { RoutePlanFormValues } from '@/lib/api/route-plan'
import type { PreferenceSettings, VehicleSettings } from '@/lib/settings'

type ParsedRoutePiece = {
  key: keyof Pick<RoutePlanFormValues, 'originLabel' | 'destinationLabel' | 'originLat' | 'originLon' | 'destinationLat' | 'destinationLon'>
  label: string
  lat: string
  lon: string
}

const knownLocations: Record<string, ParsedRoutePiece> = {
  madrid: {
    key: 'destinationLabel',
    label: 'Madrid',
    lat: '40.4168',
    lon: '-3.7038',
  },
  valencia: {
    key: 'destinationLabel',
    label: 'Valencia',
    lat: '39.4699',
    lon: '-0.3763',
  },
  cordoba: {
    key: 'originLabel',
    label: 'Córdoba',
    lat: '37.8882',
    lon: '-4.7794',
  },
  sevilla: {
    key: 'destinationLabel',
    label: 'Sevilla',
    lat: '37.3891',
    lon: '-5.9845',
  },
  barcelona: {
    key: 'destinationLabel',
    label: 'Barcelona',
    lat: '41.3874',
    lon: '2.1686',
  },
  alcobendas: {
    key: 'destinationLabel',
    label: 'Alcobendas',
    lat: '40.5317',
    lon: '-3.6419',
  },
  alcora: {
    key: 'destinationLabel',
    label: 'Alcora',
    lat: '39.1230',
    lon: '-0.5025',
  },
}

type ParsedConversation = {
  form: Partial<RoutePlanFormValues>
  vehicle: Partial<VehicleSettings>
  preferences: Partial<PreferenceSettings>
  missing: string[]
  summary: string[]
}

export function parseConversationInput(input: string): ParsedConversation {
  const normalized = removeDiacritics(input.toLowerCase())
  const form: Partial<RoutePlanFormValues> = {}
  const vehicle: Partial<VehicleSettings> = {}
  const preferences: Partial<PreferenceSettings> = {}
  const missing: string[] = []
  const summary: string[] = []

  const route = parseRouteFromInput(normalized)
  if (route.originLabel) {
    form.originLabel = route.originLabel
    summary.push(`Origen ${route.originLabel}.`)
  }
  if (route.destinationLabel) {
    form.destinationLabel = route.destinationLabel
    summary.push(`Destino ${route.destinationLabel}.`)
  }
  if (route.originLat && route.originLon) {
    form.originLat = route.originLat
    form.originLon = route.originLon
  }
  if (route.destinationLat && route.destinationLon) {
    form.destinationLat = route.destinationLat
    form.destinationLon = route.destinationLon
  }

  if (route.originLat && route.originLon && route.originLabel) {
    summary.push('He ubicado el origen.')
  } else if (route.originLabel && !route.originLat) {
    missing.push('origen')
  }
  if (route.destinationLat && route.destinationLon && route.destinationLabel) {
    summary.push('He ubicado el destino.')
  } else if (route.destinationLabel && !route.destinationLat) {
    missing.push('destino')
  }

  const battery = parseFirstNumber(normalized, /(?:al|a|con|en)\s*(\d{1,3})\s*%/)
  if (battery !== null && battery <= 100) {
    vehicle.battery = battery
    summary.push(`Batería a ${battery}%.`)
  }

  const reserve = parseFirstNumber(
    normalized,
    /(?:no\s+quiero\s+bajar\s+del|no\s+bajar\s+de|reserva\s+minima|reserva\s+min|minimo)\s*(\d{1,2})\s*%/,
  )
  if (reserve !== null) {
    preferences.reserve_min_percent = Math.min(Math.max(reserve, 0), 80)
    summary.push(`Reserva mínima ${reserve}%.`)
  }

  const usable = parseFirstDecimal(
    normalized,
    /(?:bateria util|capacidad|bater[iy]a).*?(\d+(?:[,.]\d+)?)\s*(?:kwh)?/,
  )
  if (usable !== null) {
    vehicle.usable_battery_kwh = usable
    summary.push(`Batería útil ${usable} kWh.`)
  }

  const consumption = parseFirstDecimal(
    normalized,
    /(?:consumo|consumir|media).*?(\d+(?:[,.]\d+)?)\s*kwh\/?100\s*km/,
  )
  if (consumption !== null) {
    vehicle.consumption_kwh_per_100km = consumption
    summary.push(`Consumo ${consumption} kWh/100km.`)
  }

  const power = parseFirstDecimal(normalized, /(?:potencia|maxima|máxima|max|carga).*?(\d+(?:[,.]\d+)?)\s*kw/)
  if (power !== null) {
    vehicle.max_charge_kw = power
    summary.push(`Potencia máxima ${power} kW.`)
  }

  const model = parseFirstWord(normalized, /(modelo|coche|vehiculo|vehículo)\s+(?:de\s+)?([a-z0-9 .-]{3,60})/)
  if (model) {
    vehicle.model = model.trim().replace(/\s{2,}/g, ' ')
    summary.push(`Modelo ${vehicle.model}.`)
  }

  const connector = parseConnector(normalized)
  if (connector) {
    vehicle.connector = connector
    summary.push(`Conector ${connector}.`)
  }

  preferences.prefer_fast = /\b(rapida|rapido|mas rapido|rápido|rápida|speed|rapidez)\b/.test(normalized) || undefined
  preferences.prefer_cheap =
    /\b(barata|barato|baratas|baratos|econ(ómico|omica)|low cost)\b/.test(normalized) || undefined
  preferences.prefer_services =
    /\b(servicios|baño|restaurant|comer|cafeter|parar de comer|tiempo de parada)\b/.test(normalized) || undefined
  preferences.prefer_large_hubs =
    /\b(hub|parking|area|centro comercial|mall|restaurante|hotel)\b/.test(normalized) || undefined
  preferences.prefer_low_stress =
    /\b(tranquil|relaj|sin estres|sinestres|low stress|fácil|facil|sereno)\b/.test(normalized) || undefined
  if (/\b(evitar (un|unico|único)|avoid single|unicamente|solo)\s+conector\b/.test(normalized)) {
    preferences.avoid_single_connector = true
  }

  for (const [key, value] of Object.entries(preferences)) {
    if (value === undefined) {
      delete (preferences as Record<string, unknown>)[key]
    }
  }

  if (missing.length > 0) {
    summary.push(`Necesito coordenadas para ${missing.join(' y ')}.`)
  }

  return { form, vehicle, preferences, missing, summary }
}

function parseRouteFromInput(input: string) {
  const parsed: {
    originLabel?: string
    originLat?: string
    originLon?: string
    destinationLabel?: string
    destinationLat?: string
    destinationLon?: string
  } = {}

  const explicit = input.match(/(?:de|desde)\s+([a-z0-9 .-]+?)\s+(?:a|hasta|hacia)\s+([a-z0-9 .-]+)/i)
  if (explicit) {
    const origin = resolveLocation(explicit[1].trim())
    const destination = resolveLocation(explicit[2].trim())
    if (origin) {
      parsed.originLabel = origin.label
      parsed.originLat = origin.lat
      parsed.originLon = origin.lon
    }
    if (destination) {
      parsed.destinationLabel = destination.label
      parsed.destinationLat = destination.lat
      parsed.destinationLon = destination.lon
    }
  } else {
    const destinationMatch = input.match(/(?:a|hacia|hasta)\s+([a-z0-9 .-]{2,60})/)
    if (destinationMatch) {
      const destination = resolveLocation(destinationMatch[1].trim())
      if (destination) {
        parsed.destinationLabel = destination.label
        parsed.destinationLat = destination.lat
        parsed.destinationLon = destination.lon
      }
    }

    const originMatch = input.match(/(?:de|desde)\s+([a-z0-9 .-]{2,60})/)
    if (originMatch) {
      const origin = resolveLocation(originMatch[1].trim())
      if (origin) {
        parsed.originLabel = origin.label
        parsed.originLat = origin.lat
        parsed.originLon = origin.lon
      }
    }
  }

  return parsed
}

function resolveLocation(name: string): ParsedRoutePiece | null {
  const normalized = removeDiacritics(name.toLowerCase())

  for (const [key, value] of Object.entries(knownLocations)) {
    if (normalized.includes(key)) {
      return {
        ...value,
      }
    }
  }

  return null
}

function parseFirstNumber(input: string, pattern: RegExp): number | null {
  const match = input.match(pattern)
  if (!match) {
    return null
  }
  return Math.max(0, Math.min(100, Number(match[1])))
}

function parseFirstDecimal(input: string, pattern: RegExp): number | null {
  const match = input.match(pattern)
  if (!match) {
    return null
  }
  return Number(match[1].replace(',', '.'))
}

function parseFirstWord(input: string, pattern: RegExp): string | null {
  const match = input.match(pattern)
  return match ? match[2]?.trim() ?? null : null
}

function parseConnector(input: string): string | null {
  if (/\bccs2\b|\bccs-2\b|\bccs\s+2\b/.test(input)) {
    return 'CCS2'
  }
  if (/\bchademo\b/.test(input)) {
    return 'CHAdeMO'
  }
  if (/\btype2\b|\btype 2\b|\btipo 2\b/.test(input)) {
    return 'Type2'
  }
  if (/\bgbt\b/.test(input)) {
    return 'GB/T'
  }
  if (/\btesla\b/.test(input)) {
    return 'Tesla'
  }
  return null
}

function removeDiacritics(value: string): string {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
}
