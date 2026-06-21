import { csrfHeaders, ensureCsrfCookie } from '@/lib/api/auth'
import { API_BASE_URL } from '@/lib/api/config'
import { assertRecord, errorDetail, isRecord, readArray, readNumber, readString } from '@/lib/api/validation'
import { processA2UIProtocolMessages } from '@/lib/a2ui/protocol'
import {
  A2UI_PROTOCOL_VERSION,
  KALMIO_A2UI_SURFACE_ID,
  type A2UIBlock,
  type A2UIClientAction,
  type A2UIProtocolMessage,
} from '@/lib/a2ui/types'

export const conversationMessagesQueryKey = ['conversation-messages'] as const

export type ConversationMessagesResponse = {
  messages: A2UIProtocolMessage[]
  surfaceId: string
  blocks: A2UIBlock[]
  dataModel?: unknown
}

export type SendConversationActionInput = {
  name: string
  surfaceId?: string
  sourceComponentId?: string
  context?: Record<string, unknown>
}

export type ConversationProgressUpdate = {
  stage: string
  label: string
  tool?: string
  ok?: boolean
}

export class ConversationApiError extends Error {
  code?: string
  developerDetail?: string
  disableInput: boolean

  constructor(message: string, options: { code?: string; developerDetail?: string; disableInput?: boolean } = {}) {
    super(message)
    this.name = 'ConversationApiError'
    this.code = options.code
    this.developerDetail = options.developerDetail
    this.disableInput = Boolean(options.disableInput)
  }
}

export async function getConversationMessages(): Promise<ConversationMessagesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/conversation/messages`, {
    credentials: 'include',
  })
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw conversationError(body, response.status, 'load')
  }

  return parseConversationMessagesResponse(body)
}

export async function sendConversationMessage(text: string): Promise<ConversationMessagesResponse> {
  return postConversationPayload({ text })
}

export async function sendConversationMessageStream(
  text: string,
  onProgress?: (progress: ConversationProgressUpdate) => void,
): Promise<ConversationMessagesResponse> {
  return postConversationPayloadStream({ text }, onProgress)
}

export async function sendConversationAction(action: SendConversationActionInput): Promise<ConversationMessagesResponse> {
  return postConversationPayload({
    version: A2UI_PROTOCOL_VERSION,
    action: {
      name: action.name,
      surfaceId: action.surfaceId ?? KALMIO_A2UI_SURFACE_ID,
      ...(action.sourceComponentId ? { sourceComponentId: action.sourceComponentId } : {}),
      timestamp: new Date().toISOString(),
      context: action.context ?? {},
    } satisfies A2UIClientAction,
  })
}

export async function sendConversationActionStream(
  action: SendConversationActionInput,
  onProgress?: (progress: ConversationProgressUpdate) => void,
): Promise<ConversationMessagesResponse> {
  return postConversationPayloadStream({
    version: A2UI_PROTOCOL_VERSION,
    action: {
      name: action.name,
      surfaceId: action.surfaceId ?? KALMIO_A2UI_SURFACE_ID,
      ...(action.sourceComponentId ? { sourceComponentId: action.sourceComponentId } : {}),
      timestamp: new Date().toISOString(),
      context: action.context ?? {},
    } satisfies A2UIClientAction,
  }, onProgress)
}

async function postConversationPayload(payload: unknown): Promise<ConversationMessagesResponse> {
  await ensureCsrfCookie()
  const response = await fetch(`${API_BASE_URL}/api/conversation/message`, {
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
    throw conversationError(body, response.status, 'send')
  }

  return parseConversationMessagesResponse(body)
}

async function postConversationPayloadStream(
  payload: unknown,
  onProgress?: (progress: ConversationProgressUpdate) => void,
): Promise<ConversationMessagesResponse> {
  await ensureCsrfCookie()
  const response = await fetch(`${API_BASE_URL}/api/conversation/message/stream`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
      ...csrfHeaders(),
    },
    body: JSON.stringify(payload),
  })

  const contentType = response.headers.get('Content-Type') ?? ''
  if (!response.ok) {
    const body = contentType.includes('application/json') ? await response.json().catch(() => null) : null
    throw conversationError(body, response.status, 'send')
  }

  if (!contentType.includes('text/event-stream')) {
    const body = await response.json().catch(() => null)
    return parseConversationMessagesResponse(body)
  }

  if (!response.body) {
    throw new ConversationApiError('No he podido recibir el progreso de la conversación.')
  }

  return parseConversationEventStream(response.body, onProgress)
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
    throw conversationError(body, response.status, 'clear')
  }
}

async function parseConversationEventStream(
  body: ReadableStream<Uint8Array>,
  onProgress?: (progress: ConversationProgressUpdate) => void,
): Promise<ConversationMessagesResponse> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const part of parts) {
      const result = handleConversationStreamEvent(part, onProgress)
      if (result) {
        return result
      }
    }
  }

  buffer += decoder.decode()
  if (buffer.trim()) {
    const result = handleConversationStreamEvent(buffer, onProgress)
    if (result) {
      return result
    }
  }

  throw new ConversationApiError('La conversación terminó sin una respuesta válida.')
}

function handleConversationStreamEvent(
  rawEvent: string,
  onProgress?: (progress: ConversationProgressUpdate) => void,
): ConversationMessagesResponse | null {
  const lines = rawEvent.split(/\r?\n/)
  const event = lines.find((line) => line.startsWith('event:'))?.slice('event:'.length).trim() ?? 'message'
  const data = lines
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice('data:'.length).trimStart())
    .join('\n')

  if (!data) {
    return null
  }
  const payload = JSON.parse(data) as unknown
  if (event === 'progress') {
    const value = assertRecord(payload, 'Conversation progress')
    onProgress?.({
      stage: readString(value, 'stage', 'Conversation progress'),
      label: readString(value, 'label', 'Conversation progress'),
      ...(typeof value.tool === 'string' ? { tool: value.tool } : {}),
      ...(typeof value.ok === 'boolean' ? { ok: value.ok } : {}),
    })
    return null
  }
  if (event === 'done') {
    return parseConversationMessagesResponse(payload)
  }
  if (event === 'error') {
    throw conversationError(payload, 502, 'send')
  }
  return null
}

function conversationError(body: unknown, status: number, action: 'load' | 'send' | 'clear') {
  const value = isRecord(body) ? body : {}
  const code = typeof value.code === 'string' ? value.code : undefined
  const developerDetail = typeof value.developer_detail === 'string' ? value.developer_detail : undefined
  const disableInput = value.disable_input === true
  const message = conversationErrorMessage(body, status, action)
  return new ConversationApiError(developerDetail ? `${message} Diagnóstico: ${code ?? 'chat_error'}.` : message, {
    code,
    developerDetail,
    disableInput,
  })
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
    normalized.includes('deepseek')
    || normalized.includes('json')
    || normalized.includes('backend')
    || normalized.includes('a2ui')
    || normalized.includes('conversation ')
    || normalized.includes('request failed')
  )
}

function parseConversationMessagesResponse(body: unknown): ConversationMessagesResponse {
  const value = assertRecord(body, 'Conversation messages')
  const messages = readArray(value, 'messages', 'Conversation messages').map((item) => parseA2UIProtocolMessage(item))
  const surface = processA2UIProtocolMessages(messages)
  return {
    messages,
    surfaceId: surface.surfaceId,
    blocks: surface.blocks,
    ...(surface.dataModel === undefined ? {} : { dataModel: surface.dataModel }),
  }
}

function parseA2UIProtocolMessage(body: unknown): A2UIProtocolMessage {
  const value = assertRecord(body, 'A2UI message')
  const version = readString(value, 'version', 'A2UI message')
  const envelopeKeys = ['createSurface', 'updateComponents', 'updateDataModel', 'deleteSurface'].filter((key) => {
    const envelope = value[key]
    return envelope !== undefined && envelope !== null
  })

  if (envelopeKeys.length !== 1) {
    throw new Error('A2UI message: debe contener exactamente un envelope.')
  }

  const envelopeKey = envelopeKeys[0]
  if (envelopeKey === 'createSurface') {
    const createSurface = assertRecord(value.createSurface, 'A2UI createSurface')
    return {
      version,
      createSurface: {
        surfaceId: readString(createSurface, 'surfaceId', 'A2UI createSurface'),
        catalogId: readString(createSurface, 'catalogId', 'A2UI createSurface'),
        ...(isRecord(createSurface.theme) ? { theme: createSurface.theme } : {}),
        ...(typeof createSurface.sendDataModel === 'boolean' ? { sendDataModel: createSurface.sendDataModel } : {}),
      },
    } as A2UIProtocolMessage
  }

  if (envelopeKey === 'updateComponents') {
    const updateComponents = assertRecord(value.updateComponents, 'A2UI updateComponents')
    return {
      version,
      updateComponents: {
        surfaceId: readString(updateComponents, 'surfaceId', 'A2UI updateComponents'),
        components: readArray(updateComponents, 'components', 'A2UI updateComponents').map((item) => {
          const component = assertRecord(item, 'A2UI component')
          return {
            ...component,
            id: readString(component, 'id', 'A2UI component'),
            component: readString(component, 'component', 'A2UI component'),
            ...(component.version === undefined ? {} : { version: readNumber(component, 'version', 'A2UI component') }),
          }
        }),
      },
    } as A2UIProtocolMessage
  }

  if (envelopeKey === 'updateDataModel') {
    const updateDataModel = assertRecord(value.updateDataModel, 'A2UI updateDataModel')
    return {
      version,
      updateDataModel: {
        surfaceId: readString(updateDataModel, 'surfaceId', 'A2UI updateDataModel'),
        ...(typeof updateDataModel.path === 'string' ? { path: updateDataModel.path } : {}),
        value: updateDataModel.value,
      },
    } as A2UIProtocolMessage
  }

  const deleteSurface = assertRecord(value.deleteSurface, 'A2UI deleteSurface')
  return {
    version,
    deleteSurface: {
      surfaceId: readString(deleteSurface, 'surfaceId', 'A2UI deleteSurface'),
    },
  } as A2UIProtocolMessage
}
