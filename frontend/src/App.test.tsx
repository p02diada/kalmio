import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  vi.useRealTimers()
  vi.restoreAllMocks()
  window.history.pushState(null, '', '/')
  sessionStorage.clear()
  localStorage.clear()
  document.cookie = 'csrftoken=; Max-Age=0'
})

describe('App', () => {
  it('renders the chat landing state without calling the route planner', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = input.toString()
      if (url.includes('/api/conversation/messages')) {
        return Promise.resolve(
          new Response(JSON.stringify(conversationBody([])), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`))
    })

    render(<App />)

    expect((await screen.findAllByText('Kalmio'))[0]).toBeInTheDocument()
    expect(await screen.findByText('Cuéntame ruta, batería o urgencia.')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Mensaje para Kalmio' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Carga urgente/i })).toBeInTheDocument()
    expect(fetchSpy.mock.calls.some(([input]) => input.toString().includes('/api/conversation/route'))).toBe(false)
  })

  it('starts the chat when users choose a guided prompt', async () => {
    document.cookie = 'csrftoken=test-token'
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = input.toString()
      if (url.includes('/api/conversation/messages')) {
        return Promise.resolve(
          new Response(JSON.stringify(conversationBody([])), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
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

  it('focuses the chat composer when users choose manual location entry', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = input.toString()
      if (url.includes('/api/conversation/messages')) {
        return Promise.resolve(
          new Response(
            JSON.stringify(conversationBody([
                {
                  id: 'position-request',
                  type: 'PositionRequestCard',
                  version: 1,
                  props: {
                    title: 'Necesito tu ubicación',
                    body: 'Comparte tu ubicación o escribe una ciudad o punto cercano.',
                    manualFields: ['ciudad', 'latitud', 'longitud'],
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

    const composer = await screen.findByLabelText('Mensaje para Kalmio')
    const manualButton = await screen.findByRole('button', { name: 'Escribir ubicación' })
    manualButton.focus()
    expect(document.activeElement).toBe(manualButton)

    fireEvent.click(manualButton)

    expect(document.activeElement).toBe(composer)
    expect(screen.getByText(/también sirven coordenadas/i)).toBeInTheDocument()
  })

  it('scrolls new agent results to the primary recommendation instead of the last alternative', async () => {
    document.cookie = 'csrftoken=test-token'
    const scrollIntoView = vi.fn(function (this: HTMLElement, options?: ScrollIntoViewOptions) {
      void options
    })
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
    expect(screen.getByText('Contactando con Kalmio')).toBeInTheDocument()

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

  it.each([
    {
      label: 'respuesta rápida',
      elapsedMs: 2000,
      expectedCopy: 'Contactando con Kalmio',
      hiddenCopy: ['Esperando la respuesta', 'Está tardando más de lo habitual', 'Si no llega, podrás reintentarlo'],
    },
    {
      label: 'respuesta normal',
      elapsedMs: 7000,
      expectedCopy: 'Esperando la respuesta',
      hiddenCopy: ['Está tardando más de lo habitual', 'Si no llega, podrás reintentarlo'],
    },
    {
      label: 'respuesta lenta',
      elapsedMs: 13000,
      expectedCopy: 'Está tardando más de lo habitual',
      hiddenCopy: ['Si no llega, podrás reintentarlo'],
    },
    {
      label: 'respuesta muy lenta',
      elapsedMs: 25000,
      expectedCopy: 'Si no llega, podrás reintentarlo',
      hiddenCopy: [],
    },
  ])('shows the right loader copy for $label after $elapsedMs ms', async ({ elapsedMs, expectedCopy, hiddenCopy }) => {
    document.cookie = 'csrftoken=test-token'
    const pendingMessage = new Promise<Response>(() => {})
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

    const { unmount } = render(<App />)
    fireEvent.click((await screen.findAllByRole('link', { name: /Chat/i }))[0])
    expect(await screen.findByText('Cuéntame qué necesitas.')).toBeInTheDocument()

    vi.useFakeTimers()

    fireEvent.change(screen.getByLabelText('Mensaje para Kalmio'), {
      target: { value: 'Estoy en Córdoba con un 18%' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))

    expect(screen.getByText('Contactando con Kalmio')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(elapsedMs)
    })
    expect(screen.getByText(expectedCopy)).toBeInTheDocument()
    hiddenCopy.forEach((copy) => {
      expect(screen.queryByText(copy)).not.toBeInTheDocument()
    })

    unmount()
  })
})
