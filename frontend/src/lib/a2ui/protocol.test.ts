import { describe, expect, it } from 'vitest'

import { KALMIO_A2UI_CATALOG_ID } from './types'
import { localBlocksToProtocolMessages, localBlockToComponentDefinition, processA2UIProtocolMessages } from './protocol'

describe('A2UI protocol adapter', () => {
  it('wraps local blocks in official v0.9.1 surface envelopes', () => {
    const messages = localBlocksToProtocolMessages(
      [
        {
          id: 'assistant-1',
          type: 'AssistantMessage',
          version: 1,
          props: { text: 'Busca un cargador cercano.' },
        },
      ],
      {
        surfaceId: 'chat-turn-1',
        dataModel: { route: { origin: 'Córdoba' } },
        sendDataModel: true,
      },
    )

    expect(messages).toEqual([
      {
        version: 'v0.9.1',
        createSurface: {
          surfaceId: 'chat-turn-1',
          catalogId: KALMIO_A2UI_CATALOG_ID,
          sendDataModel: true,
        },
      },
      {
        version: 'v0.9.1',
        updateComponents: {
          surfaceId: 'chat-turn-1',
          components: [
            {
              id: 'assistant-1',
              component: 'AssistantMessage',
              version: 1,
              text: 'Busca un cargador cercano.',
            },
          ],
        },
      },
      {
        version: 'v0.9.1',
        updateDataModel: {
          surfaceId: 'chat-turn-1',
          path: '/',
          value: { route: { origin: 'Córdoba' } },
        },
      },
    ])
  })

  it('does not let local props override structural component fields', () => {
    const component = localBlockToComponentDefinition({
      id: 'safe-id',
      type: 'AssistantMessage',
      version: 1,
      props: {
        id: 'bad-id',
        component: 'InjectedComponent',
        text: 'Disponibilidad no confirmada.',
      },
    })

    expect(component).toMatchObject({
      id: 'safe-id',
      component: 'AssistantMessage',
      version: 1,
      text: 'Disponibilidad no confirmada.',
    })
  })

  it('processes official envelopes into local renderer blocks', () => {
    const surface = processA2UIProtocolMessages([
      {
        version: 'v0.9.1',
        createSurface: {
          surfaceId: 'chat-turn-1',
          catalogId: KALMIO_A2UI_CATALOG_ID,
        },
      },
      {
        version: 'v0.9.1',
        updateComponents: {
          surfaceId: 'chat-turn-1',
          components: [
            {
              id: 'assistant-1',
              component: 'AssistantMessage',
              version: 1,
              text: 'Puedo ayudarte con la carga.',
            },
          ],
        },
      },
      {
        version: 'v0.9.1',
        updateDataModel: {
          surfaceId: 'chat-turn-1',
          path: '/',
          value: { facts: { stops: [] } },
        },
      },
    ])

    expect(surface).toEqual({
      surfaceId: 'chat-turn-1',
      catalogId: KALMIO_A2UI_CATALOG_ID,
      blocks: [
        {
          id: 'assistant-1',
          type: 'AssistantMessage',
          version: 1,
          props: { text: 'Puedo ayudarte con la carga.' },
        },
      ],
      dataModel: { facts: { stops: [] } },
    })
  })
})
