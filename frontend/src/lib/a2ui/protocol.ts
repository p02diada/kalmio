import {
  A2UI_PROTOCOL_VERSION,
  KALMIO_A2UI_CATALOG_ID,
  KALMIO_A2UI_SURFACE_ID,
  type A2UIBlock,
  type A2UIComponentDefinition,
  type A2UIProtocolMessage,
} from './types'

type LocalBlocksToProtocolOptions = {
  surfaceId: string
  dataModel?: unknown
  sendDataModel?: boolean
  theme?: Record<string, unknown>
}

export type ProcessedA2UISurface = {
  surfaceId: string
  catalogId: string
  blocks: A2UIBlock[]
  dataModel?: unknown
}

export function localBlocksToProtocolMessages(
  blocks: A2UIBlock[],
  { surfaceId, dataModel, sendDataModel, theme }: LocalBlocksToProtocolOptions,
): A2UIProtocolMessage[] {
  const messages: A2UIProtocolMessage[] = [
    {
      version: A2UI_PROTOCOL_VERSION,
      createSurface: {
        surfaceId,
        catalogId: KALMIO_A2UI_CATALOG_ID,
        ...(theme ? { theme } : {}),
        ...(sendDataModel === undefined ? {} : { sendDataModel }),
      },
    },
    {
      version: A2UI_PROTOCOL_VERSION,
      updateComponents: {
        surfaceId,
        components: blocks.map(localBlockToComponentDefinition),
      },
    },
  ]

  if (dataModel !== undefined) {
    messages.push({
      version: A2UI_PROTOCOL_VERSION,
      updateDataModel: {
        surfaceId,
        path: '/',
        value: dataModel,
      },
    })
  }

  return messages
}

export function localBlockToComponentDefinition(block: A2UIBlock): A2UIComponentDefinition {
  return {
    ...block.props,
    id: block.id,
    component: block.type,
    version: block.version,
  }
}

export function processA2UIProtocolMessages(messages: A2UIProtocolMessage[]): ProcessedA2UISurface {
  let surfaceId = KALMIO_A2UI_SURFACE_ID
  let catalogId = KALMIO_A2UI_CATALOG_ID
  let dataModel: unknown
  const components = new Map<string, A2UIComponentDefinition>()
  const componentOrder: string[] = []

  for (const message of messages) {
    if (message.version !== A2UI_PROTOCOL_VERSION) {
      throw new Error(`A2UI: versión no soportada ${message.version}.`)
    }

    if ('deleteSurface' in message) {
      if (message.deleteSurface.surfaceId === surfaceId) {
        components.clear()
        componentOrder.length = 0
        dataModel = undefined
      }
      continue
    }

    if ('createSurface' in message) {
      surfaceId = message.createSurface.surfaceId
      catalogId = message.createSurface.catalogId
      if (catalogId !== KALMIO_A2UI_CATALOG_ID) {
        throw new Error(`A2UI: catálogo no soportado ${catalogId}.`)
      }
      continue
    }

    if ('updateComponents' in message) {
      if (message.updateComponents.surfaceId !== surfaceId) {
        continue
      }
      for (const component of message.updateComponents.components) {
        if (!componentOrder.includes(component.id)) {
          componentOrder.push(component.id)
        }
        components.set(component.id, component)
      }
      continue
    }

    if ('updateDataModel' in message && message.updateDataModel.surfaceId === surfaceId) {
      dataModel = message.updateDataModel.value
    }
  }

  return {
    surfaceId,
    catalogId,
    blocks: componentOrder
      .map((id) => components.get(id))
      .filter((component): component is A2UIComponentDefinition => Boolean(component))
      .map(componentDefinitionToLocalBlock),
    ...(dataModel === undefined ? {} : { dataModel }),
  }
}

export function componentDefinitionToLocalBlock(component: A2UIComponentDefinition): A2UIBlock {
  const { id, component: componentType, version, ...props } = component
  return {
    id,
    type: componentType,
    version: typeof version === 'number' && Number.isFinite(version) ? version : 1,
    props,
  }
}
