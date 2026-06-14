export type A2UIType =
  | 'AssistantMessage'
  | 'UserMessage'
  | 'TripSummaryCard'
  | 'RouteSummaryCard'
  | 'RecommendedStopCard'
  | 'AlternativeRoutesList'
  | 'AlternativeStopsList'
  | 'RiskExplanationCard'
  | 'CostComparisonCard'
  | 'UrgentChargeCard'
  | 'DestinationChargingCard'
  | 'StayPlanningCard'
  | 'MapPreviewCard'
  | 'ActionButtons'
  | 'ClarifyingQuestionCard'
  | 'LocationRequestCard'
  | 'LocationDetailCard'
  | 'PreferenceChips'
  | 'ErrorFallbackCard'

export type A2UIBlock = {
  id: string
  type: A2UIType | string
  version: number
  props: Record<string, unknown>
}
