from __future__ import annotations

from routing.policies.base import PolicyContext, PolicyIssue, issue, issues
from routing.policies.actions import action_buttons_contract_issues
from routing.policies.messages import assistant_message_contract_issues
from routing.policies.stations import station_list_contract_issues
from routing.policies.traceability import (
    map_preview_contract_issues,
    required_station_reference_contract_issues,
    route_summary_contract_issues,
    station_metric_contract_issues,
    station_reference_contract_issues,
)


class ComponentTraceabilityPolicy:
    code = "a2ui.component_traceability"

    def check(self, context: PolicyContext) -> list[PolicyIssue]:
        from routing import agent as legacy

        facts = context.facts
        user_context = legacy.user_conversation_text(context.message, context.history_blocks)
        facts["vehicle"].update(legacy.parse_vehicle_fields(user_context))
        explicit_coordinates = legacy.coordinates_from_text(user_context)
        collected: list[PolicyIssue] = []

        for index, item in enumerate(context.blocks):
            path = f"blocks[{index}]"
            if not isinstance(item, dict):
                collected.append(issue(self.code, "Todos los bloques A2UI deben ser objetos.", path=path))
                continue
            block_type = item.get("type")
            props = item.get("props") if isinstance(item.get("props"), dict) else {}

            if block_type == "StationList":
                collected.extend(issues(self.code, station_list_contract_issues(props, facts), path=path))
            elif block_type == "AssistantMessage":
                collected.extend(issues(self.code, assistant_message_contract_issues(props, facts), path=path))
            elif block_type in legacy.STATION_CARD_TYPES:
                station_name = props.get("name") or props.get("stationName")
                messages = [
                    *required_station_reference_contract_issues(f"{block_type}.name", station_name, facts),
                    *station_reference_contract_issues(f"{block_type}.name", station_name, facts),
                    *station_metric_contract_issues(str(block_type), props, facts),
                ]
                collected.extend(issues(self.code, messages, path=path))
            elif block_type == "RouteCorridorCard":
                messages = [
                    *route_summary_contract_issues(props, facts, "RouteCorridorCard"),
                    *map_preview_contract_issues(
                        props,
                        facts,
                        explicit_coordinates,
                        "RouteCorridorCard",
                    ),
                ]
                collected.extend(issues(self.code, messages, path=path))
            elif block_type == "ActionButtons":
                collected.extend(
                    issues(
                        self.code,
                        action_buttons_contract_issues(props, facts, explicit_coordinates),
                        path=path,
                    )
                )
        return collected
