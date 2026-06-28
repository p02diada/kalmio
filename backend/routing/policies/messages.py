from __future__ import annotations

from typing import Any


def assistant_message_contract_issues(props: dict, facts: dict[str, Any]) -> list[str]:
    from routing import agent as legacy

    text = legacy.display_text(props.get("text"), "")
    if not text:
        return []
    normalized_text = legacy.normalize(text)
    if legacy.has_approximation_disclaimer(normalized_text):
        return []

    issues = []
    for location in facts.get("approximateLocations", []):
        query = legacy.display_text(location.get("query"), "")
        resolved_label = legacy.display_text(location.get("resolvedLabel"), "")
        if query and legacy.normalize(query) in normalized_text:
            issues.append(
                "AssistantMessage.text sugiere ubicación exacta para "
                f"'{query}', pero la herramienta solo resolvió '{resolved_label}'. "
                "Debe decir que usa la ciudad/zona como aproximación o pedir coordenadas/dirección exacta."
            )
    return issues
