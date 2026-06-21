import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { localBlocksToProtocolMessages } from '@/lib/a2ui/protocol'
import type { A2UIBlock } from '@/lib/a2ui/types'
import App from './App'

function conversationBody(blocks: A2UIBlock[]) {
  return {
    messages: localBlocksToProtocolMessages(blocks, {
      surfaceId: 'kalmio-chat',
      dataModel: {
        conversation: {
          componentOrder: blocks.map((block) => ({ id: block.id, component: block.type })),
        },
      },
      sendDataModel: true,
    }),
  }
}

afterEach(() => {
  vi.restoreAllMocks()
  window.history.pushState(null, '', '/')
  sessionStorage.clear()
  localStorage.clear()
  document.cookie = 'csrftoken=; Max-Age=0'
})

describe('App', () => {
  it('renders a quick-start home that does not call the route planner', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'unexpected' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    render(<App />)

    expect((await screen.findAllByText('Kalmio'))[0]).toBeInTheDocument()
    expect(screen.getByText('Cuenta tu ruta o urgencia')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Abrir chat/i })).toBeInTheDocument()
    expect(screen.getByText('Antes de recomendar')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('starts the chat when users choose a guided prompt', async () => {
    document.cookie = 'csrftoken=test-token'
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = input.toString()
      if (url.includes('/api/conversation/messages')) {
        return Promise.resolve(
          new Response(
            JSON.stringify(conversationBody([
                {
                  id: 'assistant-initial',
                  type: 'AssistantMessage',
                  version: 1,
                  props: { text: 'Cuéntame qué necesitas.' },
                },
              ])),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      if (url.includes('/api/auth/csrf')) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: 'csrf cookie set', csrf_token: 'test-token' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      if (url.includes('/api/conversation/message')) {
        return Promise.resolve(
          new Response(
            JSON.stringify(conversationBody([
                {
                  id: 'user-1',
                  type: 'UserMessage',
                  version: 1,
                  props: { text: 'Quiero planificar dónde cargar al llegar a mi hotel o destino. Si falta la ubicación exacta, pregúntame antes de buscar opciones.' },
                },
                {
                  id: 'location-1',
                  type: 'AssistantMessage',
                  version: 1,
                  props: {
                    text: 'Uso Valencia como ubicación aproximada para buscar estaciones de carga.',
                  },
                },
              ])),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }

      return Promise.reject(new Error(`Unexpected request: ${url}`))
    })

    render(
      <StrictMode>
        <App />
      </StrictMode>,
    )
    fireEvent.click(await screen.findByRole('button', { name: /Plan al llegar/i }))

    await waitFor(() =>
      expect(fetchSpy.mock.calls.some(([input]) => input.toString().includes('/api/conversation/message'))).toBe(true),
    )
    expect(fetchSpy.mock.calls.some(([input]) => input.toString().includes('/api/conversation/route'))).toBe(false)
    const messageCall = fetchSpy.mock.calls.find(([input]) => input.toString().endsWith('/api/conversation/message'))
    expect(JSON.parse(messageCall?.[1]?.body?.toString() ?? '{}')).toEqual({
      text: 'Quiero planificar dónde cargar al llegar a mi hotel o destino. Si falta la ubicación exacta, pregúntame antes de buscar opciones.',
    })
    expect(await screen.findByText(/Uso Valencia como ubicación aproximada/i)).toBeInTheDocument()
  })

  it('renders unknown A2UI blocks with a safe fallback', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = input.toString()
      if (url.includes('/api/conversation/messages')) {
        return Promise.resolve(
          new Response(
            JSON.stringify(conversationBody([
                {
                  id: 'unknown-1',
                  type: 'MadeUpComponent',
                  version: 1,
                  props: {},
                },
              ])),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`))
    })

    render(<App />)
    fireEvent.click((await screen.findAllByRole('link', { name: /Chat/i }))[0])

    expect(await screen.findByText('No puedo mostrar una parte de la respuesta')).toBeInTheDocument()
    expect(screen.getByText('MadeUpComponent')).toBeInTheDocument()
  })

  it('translates technical conversation errors into recovery copy with retry', async () => {
    document.cookie = 'csrftoken=test-token'
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = input.toString()
      if (url.includes('/api/conversation/messages')) {
        return Promise.resolve(
          new Response(
            JSON.stringify(conversationBody([
                {
                  id: 'assistant-initial',
                  type: 'AssistantMessage',
                  version: 1,
                  props: { text: 'Cuéntame qué necesitas.' },
                },
              ])),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      if (url.includes('/api/auth/csrf')) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: 'csrf cookie set', csrf_token: 'test-token' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      if (url.includes('/api/conversation/message')) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: 'El agente no devolvió JSON válido.' }), {
            status: 502,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`))
    })

    render(<App />)
    fireEvent.click((await screen.findAllByRole('link', { name: /Chat/i }))[0])
    fireEvent.change(await screen.findByLabelText('Mensaje para Kalmio'), {
      target: { value: 'Madrid a Valencia con 20%' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))

    expect(await screen.findByText(/No he podido completar la comprobación/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeInTheDocument()
    expect(screen.queryByText(/DeepSeek/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/JSON válido/i)).not.toBeInTheDocument()
  })

  it('scrolls new agent results to the primary recommendation instead of the last alternative', async () => {
    document.cookie = 'csrftoken=test-token'
    const scrollIntoView = vi.fn(function (this: HTMLElement) {})
    Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    })
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = input.toString()
      if (url.includes('/api/conversation/messages')) {
        return Promise.resolve(
          new Response(
            JSON.stringify(conversationBody([
                {
                  id: 'assistant-initial',
                  type: 'AssistantMessage',
                  version: 1,
                  props: { text: 'Cuéntame qué necesitas.' },
                },
              ])),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      if (url.includes('/api/auth/csrf')) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: 'csrf cookie set', csrf_token: 'test-token' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      if (url.includes('/api/conversation/message')) {
        return Promise.resolve(
          new Response(
            JSON.stringify(conversationBody([
                {
                  id: 'user-1',
                  type: 'UserMessage',
                  version: 1,
                  props: { text: 'Estoy en Córdoba con un 18%' },
                },
                {
                  id: 'assistant-1',
                  type: 'AssistantMessage',
                  version: 1,
                  props: { text: 'Te dejo una opción principal y una alternativa útil.' },
                },
                {
                  id: 'recommended-station',
                  type: 'StationPreviewCard',
                  version: 1,
                  props: {
                    stationName: 'BALLENOIL-ES336090-COLON',
                    powerKw: 150,
                    distanceKm: 0.8,
                    availableEvses: 2,
                    totalEvses: 4,
                    connectorTypes: ['CCS2'],
                  },
                },
                {
                  id: 'alternatives',
                  type: 'StationList',
                  version: 1,
                  props: {
                    stations: [
                      {
                        stationName: 'Parking Calle Sevilla Nº5 - Córdoba',
                        powerKw: 22,
                        distanceKm: 1.2,
                        availableEvses: 1,
                        totalEvses: 2,
                      },
                    ],
                  },
                },
              ])),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`))
    })

    render(<App />)
    fireEvent.click((await screen.findAllByRole('link', { name: /Chat/i }))[0])
    expect(await screen.findByText('Cuéntame qué necesitas.')).toBeInTheDocument()
    scrollIntoView.mockClear()

    fireEvent.change(await screen.findByLabelText('Mensaje para Kalmio'), {
      target: { value: 'Estoy en Córdoba con un 18%' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))

    expect(await screen.findByText('BALLENOIL-ES336090-COLON')).toBeInTheDocument()
    expect(screen.getByText('Parking Calle Sevilla Nº5 - Córdoba')).toBeInTheDocument()
    await waitFor(() => {
      const target = scrollIntoView.mock.contexts.at(-1) as HTMLElement | undefined
      expect(target?.dataset.a2uiBlockId).toBe('recommended-station')
    })
    expect(scrollIntoView.mock.calls.at(-1)?.[0]).toMatchObject({ block: 'start' })
  })

  it('shows the user message immediately while the backend agent is still responding', async () => {
    document.cookie = 'csrftoken=test-token'
    let resolveMessage: (response: Response) => void = () => {}
    const pendingMessage = new Promise<Response>((resolve) => {
      resolveMessage = resolve
    })
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = input.toString()
      if (url.includes('/api/conversation/messages')) {
        return Promise.resolve(
          new Response(
            JSON.stringify(conversationBody([
                {
                  id: 'assistant-initial',
                  type: 'AssistantMessage',
                  version: 1,
                  props: { text: 'Cuéntame qué necesitas.' },
                },
              ])),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      if (url.includes('/api/auth/csrf')) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: 'csrf cookie set', csrf_token: 'test-token' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      if (url.includes('/api/conversation/message')) {
        return pendingMessage
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`))
    })

    render(<App />)
    fireEvent.click((await screen.findAllByRole('link', { name: /Chat/i }))[0])
    fireEvent.change(await screen.findByLabelText('Mensaje para Kalmio'), {
      target: { value: 'Estoy en Córdoba con un 18%' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))

    expect(await screen.findByText('Estoy en Córdoba con un 18%')).toBeInTheDocument()

    resolveMessage(
      new Response(
        JSON.stringify(conversationBody([
            {
              id: 'user-1',
              type: 'UserMessage',
              version: 1,
              props: { text: 'Estoy en Córdoba con un 18%' },
            },
            {
              id: 'assistant-1',
              type: 'AssistantMessage',
              version: 1,
              props: { text: 'Necesito confirmar un dato antes de recomendar.' },
            },
          ])),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    expect(await screen.findByText('Necesito confirmar un dato antes de recomendar.')).toBeInTheDocument()
  })
})
