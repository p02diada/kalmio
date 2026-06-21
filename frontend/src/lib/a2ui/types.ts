export const A2UI_PROTOCOL_VERSION = 'v0.9.1'
export const KALMIO_A2UI_CATALOG_ID = 'https://kalmio.app/a2ui/catalogs/ev-assistant/v1/catalog.json'
export const KALMIO_A2UI_SURFACE_ID = 'kalmio-chat'

export type KalmioA2UIType =
  | 'AssistantMessage'
  | 'UserMessage'
  | 'RouteSummaryCard'
  | 'StationPreviewCard'
  | 'StationDetailCard'
  | 'StationList'
  | 'CostComparisonCard'
  | 'MapPreviewCard'
  | 'ActionButtons'
  | 'PositionRequestCard'
  | 'PreferenceChips'
  | 'ErrorFallbackCard'

export type KalmioEvidence = {
  label: string
  value: string | number | boolean | null
  unit?: string
  status?: 'known' | 'estimated' | 'unknown'
  sourcePath?: string
}

export type KalmioUncertainty = {
  level: 'info' | 'medium' | 'high'
  text: string
  source?: string
  freshness?: string
}

export type KalmioAction = {
  label: string
  priority?: 'primary' | 'secondary'
  disabled?: boolean
  reason?: string
  event?: {
    name: string
    context?: Record<string, unknown>
  }
  functionCall?: {
    call: 'openUrl'
    args: { url: string }
  }
}

export type KalmioDecisionProps = {
  title?: string
  takeaway?: string
  why?: string
  evidence?: KalmioEvidence[]
  uncertainty?: KalmioUncertainty
  primaryAction?: KalmioAction
}

export type KalmioA2UIBlock = {
  id: string
  type: KalmioA2UIType | string
  version: number
  props: Record<string, unknown>
}

export type A2UIType = KalmioA2UIType

// Local renderer state derived from official A2UI envelopes.
export type A2UIBlock = KalmioA2UIBlock

export type A2UIComponentDefinition = {
  id: string
  component: KalmioA2UIType | string
} & Record<string, unknown>

export type A2UICreateSurfaceMessage = {
  version: typeof A2UI_PROTOCOL_VERSION
  createSurface: {
    surfaceId: string
    catalogId: typeof KALMIO_A2UI_CATALOG_ID | string
    theme?: Record<string, unknown>
    sendDataModel?: boolean
  }
}

export type A2UIUpdateComponentsMessage = {
  version: typeof A2UI_PROTOCOL_VERSION
  updateComponents: {
    surfaceId: string
    components: A2UIComponentDefinition[]
  }
}

export type A2UIUpdateDataModelMessage = {
  version: typeof A2UI_PROTOCOL_VERSION
  updateDataModel: {
    surfaceId: string
    path?: string
    value: unknown
  }
}

export type A2UIDeleteSurfaceMessage = {
  version: typeof A2UI_PROTOCOL_VERSION
  deleteSurface: {
    surfaceId: string
  }
}

export type A2UIProtocolMessage =
  | A2UICreateSurfaceMessage
  | A2UIUpdateComponentsMessage
  | A2UIUpdateDataModelMessage
  | A2UIDeleteSurfaceMessage

export type A2UIClientAction = {
  name: string
  surfaceId: string
  sourceComponentId?: string
  timestamp: string
  context?: Record<string, unknown>
}

export type A2UIClientActionMessage = {
  version: typeof A2UI_PROTOCOL_VERSION
  action: A2UIClientAction
}
