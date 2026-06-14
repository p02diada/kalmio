export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function errorDetail(body: unknown, fallback: string): string {
  return isRecord(body) && typeof body.detail === 'string' ? body.detail : fallback
}

export function assertRecord(value: unknown, context: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`${context}: respuesta inválida.`)
  }
  return value
}

export function readString(record: Record<string, unknown>, key: string, context: string): string {
  const value = record[key]
  if (typeof value !== 'string') {
    throw new Error(`${context}: ${key} inválido.`)
  }
  return value
}

export function readNullableString(record: Record<string, unknown>, key: string, context: string): string | null {
  const value = record[key]
  if (value === null) {
    return null
  }
  if (typeof value !== 'string') {
    throw new Error(`${context}: ${key} inválido.`)
  }
  return value
}

export function readNumber(record: Record<string, unknown>, key: string, context: string): number {
  const value = record[key]
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`${context}: ${key} inválido.`)
  }
  return value
}

export function readNullableNumber(record: Record<string, unknown>, key: string, context: string): number | null {
  const value = record[key]
  if (value === null) {
    return null
  }
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`${context}: ${key} inválido.`)
  }
  return value
}

export function readBoolean(record: Record<string, unknown>, key: string, context: string): boolean {
  const value = record[key]
  if (typeof value !== 'boolean') {
    throw new Error(`${context}: ${key} inválido.`)
  }
  return value
}

export function readArray(record: Record<string, unknown>, key: string, context: string): unknown[] {
  const value = record[key]
  if (!Array.isArray(value)) {
    throw new Error(`${context}: ${key} inválido.`)
  }
  return value
}
