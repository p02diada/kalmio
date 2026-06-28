from __future__ import annotations

from routing.policies.actions import action_button_sequence_contract_issues
from routing.policies.base import PolicyContext, PolicyIssue, issues


class CopyAndFactPolicy:
    code = "a2ui.copy_and_fact"

    def check(self, context: PolicyContext) -> list[PolicyIssue]:
        from routing import agent as legacy

        facts = context.facts
        user_context = legacy.user_conversation_text(context.message, context.history_blocks)
        facts["vehicle"].update(legacy.parse_vehicle_fields(user_context))
        checks: list[tuple[str, list[str]]] = [
            ("factual_charger_copy", legacy.factual_charger_copy_contract_issues(context.blocks, facts)),
            (
                "destination_city_approximation",
                legacy.destination_city_approximation_contract_issues(
                    context.blocks,
                    context.tool_history,
                    user_context,
                    facts,
                ),
            ),
            ("approximate_location", legacy.approximate_location_contract_issues(context.blocks, facts)),
            ("comfort_copy", legacy.comfort_copy_contract_issues(context.blocks)),
            ("night_safety_copy", legacy.night_safety_copy_contract_issues(context.blocks, user_context)),
            (
                "night_safety_warning_order",
                legacy.night_safety_warning_order_contract_issues(context.blocks, user_context),
            ),
            (
                "requested_service_data",
                legacy.requested_service_data_contract_issues(
                    context.blocks,
                    context.tool_history,
                    user_context,
                    facts,
                ),
            ),
            (
                "default_reserve_copy",
                legacy.default_reserve_copy_contract_issues(
                    context.blocks,
                    context.tool_history,
                    user_context,
                    facts,
                ),
            ),
            (
                "unvalidated_route_margin_copy",
                legacy.unvalidated_route_margin_copy_contract_issues(
                    context.blocks,
                    context.tool_history,
                    facts,
                ),
            ),
            (
                "chargers_only_warning_order",
                legacy.chargers_only_warning_order_contract_issues(
                    context.blocks,
                    context.tool_history,
                    facts,
                ),
            ),
            (
                "max_useful_power_copy",
                legacy.max_useful_power_copy_contract_issues(
                    context.blocks,
                    context.tool_history,
                    facts,
                ),
            ),
            ("few_stops_copy_context", legacy.few_stops_copy_context_contract_issues(context.blocks, user_context)),
            ("departure_battery_copy", legacy.departure_battery_copy_contract_issues(context.blocks, user_context)),
            (
                "future_trip_volatility_copy",
                legacy.future_trip_volatility_copy_contract_issues(context.blocks, user_context),
            ),
            (
                "reservation_capability_copy",
                legacy.reservation_capability_copy_contract_issues(context.blocks, user_context),
            ),
            (
                "cheap_route_reserve_context",
                legacy.cheap_route_reserve_context_contract_issues(context.blocks, user_context),
            ),
            (
                "price_preference_context",
                legacy.price_preference_context_contract_issues(
                    context.blocks,
                    user_context,
                    context.tool_history,
                    facts,
                ),
            ),
            ("minimum_charge_context", legacy.minimum_charge_context_contract_issues(context.blocks, user_context)),
            (
                "single_connector_preference",
                legacy.single_connector_preference_contract_issues(
                    context.blocks,
                    context.tool_history,
                    user_context,
                    facts,
                ),
            ),
            ("action_button_sequence", action_button_sequence_contract_issues(context.blocks)),
        ]

        collected: list[PolicyIssue] = []
        for suffix, messages in checks:
            collected.extend(issues(f"{self.code}.{suffix}", messages))
        return collected
