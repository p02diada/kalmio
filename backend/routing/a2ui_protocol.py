from __future__ import annotations

import json
from typing import Any

A2UI_PROTOCOL_VERSION = "v0.9.1"
KALMIO_A2UI_CATALOG_ID = "https://kalmio.app/a2ui/catalogs/ev-assistant/v1/catalog.json"
KALMIO_A2UI_SURFACE_ID = "kalmio-chat"


def conversation_a2ui_response(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"messages": blocks_to_a2ui_messages(blocks)}


def blocks_to_a2ui_messages(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "version": A2UI_PROTOCOL_VERSION,
            "createSurface": {
                "surfaceId": KALMIO_A2UI_SURFACE_ID,
                "catalogId": KALMIO_A2UI_CATALOG_ID,
                "sendDataModel": True,
            },
        },
        {
            "version": A2UI_PROTOCOL_VERSION,
            "updateComponents": {
                "surfaceId": KALMIO_A2UI_SURFACE_ID,
                "components": [block_to_component(block) for block in blocks],
            },
        },
        {
            "version": A2UI_PROTOCOL_VERSION,
            "updateDataModel": {
                "surfaceId": KALMIO_A2UI_SURFACE_ID,
                "path": "/",
                "value": data_model_from_blocks(blocks),
            },
        },
    ]


def block_to_component(block: dict[str, Any]) -> dict[str, Any]:
    props = block.get("props") if isinstance(block.get("props"), dict) else {}
    component = dict(props)
    component["id"] = str(block.get("id") or "")
    component["component"] = str(block.get("type") or "")
    component["version"] = int(block.get("version") or 1)
    return component


def data_model_from_blocks(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "conversation": {
            "surfaceId": KALMIO_A2UI_SURFACE_ID,
            "componentOrder": [
                {"id": str(block.get("id") or ""), "component": str(block.get("type") or "")}
                for block in blocks
            ],
        },
        "facts": facts_from_blocks(blocks),
    }


def facts_from_blocks(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "locations": [],
        "routes": [],
        "stations": [],
    }
    for block in blocks:
        block_type = block.get("type")
        props = block.get("props") if isinstance(block.get("props"), dict) else {}
        source_component_id = str(block.get("id") or "")

        if block_type == "PlaceDetailCard":
            facts["locations"].append(with_source(props, source_component_id))
        elif block_type == "RouteSummaryCard":
            facts["routes"].append(with_source(props, source_component_id))
        elif block_type in {"StationPreviewCard", "StationDetailCard"}:
            facts["stations"].append(with_source(props, source_component_id))
        elif block_type == "StationList" and isinstance(props.get("stations"), list):
            facts["stations"].extend(
                with_source(station, source_component_id)
                for station in props["stations"]
                if isinstance(station, dict)
            )
    return facts


def with_source(value: dict[str, Any], source_component_id: str) -> dict[str, Any]:
    item = dict(value)
    item["sourceComponentId"] = source_component_id
    return item


def action_payload_to_text(action: dict[str, Any]) -> str:
    name = str(action.get("name") or "").strip()
    context = action.get("context") if isinstance(action.get("context"), dict) else {}
    if context:
        return f"Acción A2UI: {name} con contexto {json.dumps(context, ensure_ascii=False, sort_keys=True)}"
    return f"Acción A2UI: {name}"
