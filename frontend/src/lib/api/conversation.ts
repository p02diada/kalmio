import { csrfHeaders, ensureCsrfCookie } from '@/lib/api/auth'
import { API_BASE_URL } from '@/lib/api/config'
import { assertRecord, errorDetail, readArray, readNumber, readString } from '@/lib/api/validation'
import type { A2UIBlock } from '@/lib/a2ui/types'

export const conversationMessagesQueryKey = ['conversation-messages'] as const

export type ConversationMessagesResponse = {
  blocks: A2UIBlock[]
}

export async function getConversationMessages(): Promise<ConversationMessagesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/conversation/messages`, {
    credentials: 'include',
  })
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(conversationErrorMessage(body, response.status, 'load'))
  }

  return parseConversationMessagesResponse(body)
}

export async function sendConversationMessage(text: string): Promise<ConversationMessagesResponse> {
  await ensureCsrfCookie()
  const response = await fetch(`${API_BASE_URL}/api/conversation/message`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...csrfHeaders(),
    },
    body: JSON.stringify({ text }),
  })
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(conversationErrorMessage(body, response.status, 'send'))
  }

  return parseConversationMessagesResponse(body)
}

export async function clearConversation(): Promise<void> {
  await ensureCsrfCookie()
  const response = await fetch(`${API_BASE_URL}/api/conversation`, {
    method: 'DELETE',
    credentials: 'include',
    headers: csrfHeaders(),
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(conversationErrorMessage(body, response.status, 'clear'))
  }
}

function conversationErrorMessage(body: unknown, status: number, action: 'load' | 'send' | 'clear') {
  const detail = errorDetail(body, '')
  if (status === 429 && detail) {
    return detail
  }
  if (status === 403) {
    return 'No he podido verificar la sesión. Recarga la página y vuelve a intentarlo.'
  }
  if (hasTechnicalDetail(detail)) {
    return 'No he podido completar la comprobación con fiabilidad. Reintenta con origen, destino, batería y conector, o corrige los datos del mensaje.'
  }
  if (detail) {
    return detail
  }
  if (action === 'load') {
    return 'No he podido cargar la conversación. Reintenta en unos segundos.'
  }
  if (action === 'clear') {
    return 'No he podido reiniciar la conversación. Reintenta en unos segundos.'
  }
  return 'No he podido enviar el mensaje. Reintenta en unos segundos.'
}

function hasTechnicalDetail(value: string) {
  const normalized = value.toLowerCase()
  return (
    normalized.includes('codex')
    || normalized.includes('json')
    || normalized.includes('backend')
    || normalized.includes('a2ui')
    || normalized.includes('conversation ')
    || normalized.includes('request failed')
  )
}

function parseConversationMessagesResponse(body: unknown): ConversationMessagesResponse {
  const value = assertRecord(body, 'Conversation messages')
  return {
    blocks: readArray(value, 'blocks', 'Conversation messages').map((item) => parseA2UIBlock(item)),
  }
}

function parseA2UIBlock(body: unknown): A2UIBlock {
  const value = assertRecord(body, 'A2UI block')
  return {
    id: readString(value, 'id', 'A2UI block'),
    type: readString(value, 'type', 'A2UI block'),
    version: readNumber(value, 'version', 'A2UI block'),
    props: assertRecord(value.props, 'A2UI block props'),
  }
}
