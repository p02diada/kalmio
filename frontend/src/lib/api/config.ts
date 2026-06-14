type ApiEnvironment = {
  VITE_API_BASE_URL?: string
  DEV: boolean
  PROD: boolean
}

export function resolveApiBaseUrl(env: ApiEnvironment, hostname = globalThis.location?.hostname): string {
  const configuredApiBaseUrl = env.VITE_API_BASE_URL?.trim()

  if (configuredApiBaseUrl === 'same-origin') {
    return ''
  }

  if (!configuredApiBaseUrl || configuredApiBaseUrl === '/') {
    if (env.DEV && isLocalHostname(hostname)) {
      return 'http://127.0.0.1:8000'
    }
    return ''
  }

  if (configuredApiBaseUrl.startsWith('/')) {
    return configuredApiBaseUrl.replace(/\/$/, '')
  }

  let parsed: URL
  try {
    parsed = new URL(configuredApiBaseUrl)
  } catch {
    throw new Error('VITE_API_BASE_URL must be "same-origin", "/", a same-origin path, or an absolute HTTP(S) URL.')
  }

  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('VITE_API_BASE_URL must use HTTP(S).')
  }

  if (env.PROD && parsed.protocol !== 'https:') {
    throw new Error('VITE_API_BASE_URL must use HTTPS in production.')
  }

  return parsed.toString().replace(/\/$/, '')
}

function isLocalHostname(hostname: string | undefined): boolean {
  return !hostname || hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1'
}

export const API_BASE_URL = resolveApiBaseUrl(import.meta.env)
