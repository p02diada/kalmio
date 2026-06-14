import { API_BASE_URL } from '@/lib/api/config'
import { assertRecord, errorDetail, readBoolean, readNullableNumber, readString } from '@/lib/api/validation'

let csrfToken: string | null = null

export const authQueryKey = ['auth-user'] as const

export type AuthUser = {
  id: number | null
  email: string
  authenticated: boolean
}

export type AuthCredentials = {
  email: string
  password: string
}

export async function getCurrentUser(): Promise<AuthUser> {
  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    credentials: 'include',
  })
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(errorDetail(body, `Auth request failed with ${response.status}`))
  }

  return parseAuthUser(body)
}

export async function register(payload: AuthCredentials): Promise<AuthUser> {
  return submitAuth('/api/auth/register', payload)
}

export async function login(payload: AuthCredentials): Promise<AuthUser> {
  return submitAuth('/api/auth/login', payload)
}

export async function logout(): Promise<AuthUser> {
  await ensureCsrfCookie()
  const response = await fetch(`${API_BASE_URL}/api/auth/logout`, {
    method: 'POST',
    credentials: 'include',
    headers: csrfHeaders(),
  })
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(errorDetail(body, `Logout failed with ${response.status}`))
  }

  cacheCsrfToken(body)
  return parseAuthUser(body)
}

export async function ensureCsrfCookie(): Promise<void> {
  if (csrfToken) {
    return
  }

  const response = await fetch(`${API_BASE_URL}/api/auth/csrf`, {
    credentials: 'include',
  })
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(`CSRF request failed with ${response.status}`)
  }

  const parsed = assertRecord(body, 'CSRF')
  const token = readString(parsed, 'csrf_token', 'CSRF')
  csrfToken = token || getCookie('csrftoken')
}

export function csrfHeaders(): HeadersInit {
  return csrfToken ? { 'X-CSRFToken': csrfToken } : {}
}

async function submitAuth(path: string, payload: AuthCredentials): Promise<AuthUser> {
  await ensureCsrfCookie()
  const response = await fetch(`${API_BASE_URL}${path}`, {
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
    throw new Error(errorDetail(body, `Auth request failed with ${response.status}`))
  }

  cacheCsrfToken(body)
  return parseAuthUser(body)
}

function parseAuthUser(body: unknown): AuthUser {
  const value = assertRecord(body, 'Auth')
  const authenticated = readBoolean(value, 'authenticated', 'Auth')
  const id = readNullableNumber(value, 'id', 'Auth')
  const email = readString(value, 'email', 'Auth')
  if (id !== null && !Number.isInteger(id)) {
    throw new Error('Auth: id inválido.')
  }
  return {
    id,
    email,
    authenticated,
  }
}

function cacheCsrfToken(body: unknown): void {
  if (body && typeof body === 'object' && typeof (body as { csrf_token?: unknown }).csrf_token === 'string') {
    csrfToken = (body as { csrf_token: string }).csrf_token
  }
}

function getCookie(name: string): string | null {
  const cookies = document.cookie ? document.cookie.split('; ') : []
  const prefix = `${name}=`
  const match = cookies.find((cookie) => cookie.startsWith(prefix))
  return match ? decodeURIComponent(match.slice(prefix.length)) : null
}
