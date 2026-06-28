#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from run_conversation_cases import (
    CaseSpec,
    normalize,
    run_case,
)


OUTCOME_CASE_SPECS: dict[int, CaseSpec] = {
    101: CaseSpec(
        turns=["Estoy al 9% en Cordoba, necesito cargar ya"],
        any_components=({"StationPreviewCard", "StationList"},),
        expected_tools={"search_destination_chargers"},
        expected_text_any=("9", "riesgo", "confirma", "disponibilidad"),
    ),
    102: CaseSpec(
        turns=["Estoy al 14% en carretera y no se donde parar"],
        any_components=({"PositionRequestCard", "AssistantMessage"},),
        forbidden_tools={"plan_route", "search_destination_chargers"},
        expected_text_any=("ubicacion", "carretera", "zona", "coordenadas"),
    ),
    103: CaseSpec(
        turns=["Voy de Madrid a Valencia con 60% y quiero parar a comer"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "StationPreviewCard", "StationList"},),
        expected_text_any=("servicios", "indicad", "no puedo", "consumo", "perfil"),
    ),
    104: CaseSpec(
        turns=["Voy de Sevilla a Granada, me da para llegar sin cargar?"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "AssistantMessage", "StationPreviewCard"},),
        expected_text_any=("no puedo", "bateria", "modelo", "consumo"),
    ),
    105: CaseSpec(
        turns=["Me voy a Granada el finde y duermo cerca de la Alhambra"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("aproxim", "disponibilidad", "acceso", "tarifas"),
    ),
    106: CaseSpec(
        turns=["Quiero la ruta mas barata pero sin bajar del 20%"],
        forbidden_tools={"plan_route", "search_destination_chargers"},
        any_components=({"AssistantMessage"},),
        expected_text_any=("origen", "destino", "bateria", "vehiculo", "consumo"),
    ),
    107: CaseSpec(
        turns=["No quiero cargar en sitios solitarios de noche", "Estoy en Valencia centro"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("no valida seguridad", "noche", "verificar", "entorno"),
    ),
    108: CaseSpec(
        turns=["Mi coche carga maximo a 100 kW. Madrid a Valencia con 60%"],
        expected_tools={"plan_route"},
        any_components=({"StationPreviewCard", "StationList", "RouteCorridorCard"},),
        expected_text_any=("100 kw", "no aprovechara", "potencia superior", "no se premia"),
    ),
    109: CaseSpec(
        turns=["Prefiero hubs grandes aunque sean un poco mas caros. Voy de Madrid a Valencia"],
        expected_tools={"plan_route"},
        any_components=({"StationPreviewCard", "StationList", "RouteCorridorCard"},),
        expected_text_any=("hub", "tarifas", "coste", "no puedo"),
    ),
    110: CaseSpec(
        turns=["Voy a Cordoba el viernes y vuelvo el domingo, donde cargo?"],
        forbidden_tools={"plan_route", "search_destination_chargers"},
        any_components=({"AssistantMessage"},),
        expected_text_any=("origen", "salida", "desde donde", "sales"),
    ),
    111: CaseSpec(
        turns=["Busca una parada con banos y cafeteria", "Estoy cerca de Almansa"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("banos", "cafeteria", "no estan verificados", "confirma"),
    ),
    112: CaseSpec(
        turns=["Tengo un Tesla Model Y y salgo con 45%. Madrid a Valencia"],
        expected_tools={"plan_route"},
        any_components=({"StationPreviewCard", "StationList", "RouteCorridorCard"},),
        expected_text_any=("tesla", "45", "no puedo validar", "consumo"),
    ),
    113: CaseSpec(
        turns=["Estoy al 6% en Cordoba con CCS2, necesito cargar ya"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("6", "ccs2", "urg", "confirma", "disponibilidad"),
    ),
    114: CaseSpec(
        turns=["Tengo 11% y necesito un cargador rapido ya"],
        forbidden_tools={"plan_route", "search_destination_chargers"},
        any_components=({"PositionRequestCard", "AssistantMessage"},),
        expected_text_any=("ubicacion", "donde", "zona", "coordenadas"),
    ),
    115: CaseSpec(
        turns=["Estoy en Madrid centro al 15% y busco carga rapida"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("15", "madrid", "disponibilidad", "confirma"),
    ),
    116: CaseSpec(
        turns=["Estoy en Valencia al 18%, solo quiero Type2 cerca"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("type2", "valencia", "18", "confirma"),
    ),
    117: CaseSpec(
        turns=["Barcelona a Valencia manana con 70%, quiero una parada tranquila"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "StationPreviewCard", "StationList"},),
        expected_text_any=("disponibilidad", "acceso", "tarifas", "cambiar"),
    ),
    118: CaseSpec(
        turns=["Madrid a Zaragoza con 35%, llego sin cargar?"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "AssistantMessage", "StationPreviewCard"},),
        expected_text_any=("no puedo", "35", "consumo", "modelo"),
    ),
    119: CaseSpec(
        turns=["Cordoba a Sevilla, prefiero no parar si no hace falta"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "AssistantMessage", "StationPreviewCard"},),
        expected_text_any=("no puedo", "consumo", "perfil", "parar"),
    ),
    120: CaseSpec(
        turns=["Alicante a Bilbao con 30%, quiero parar pocas veces"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "StationPreviewCard", "StationList"},),
        expected_text_any=("pocas", "30", "no puedo", "consumo"),
    ),
    121: CaseSpec(
        turns=["Madrid a Valencia con perro, quiero parar donde pueda descansar"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "StationPreviewCard", "StationList"},),
        expected_text_any=("perro", "servicios", "indicad", "confirma"),
    ),
    122: CaseSpec(
        turns=["Quiero llegar con al menos 30% de bateria"],
        forbidden_tools={"plan_route", "search_destination_chargers"},
        any_components=({"AssistantMessage"},),
        expected_text_any=("origen", "destino", "bateria", "consumo", "vehiculo"),
    ),
    123: CaseSpec(
        turns=["Salgo de Madrid con 55%, donde cargo?"],
        forbidden_tools={"plan_route", "search_destination_chargers"},
        any_components=({"AssistantMessage"},),
        expected_text_any=("destino", "hacia donde", "donde vas"),
    ),
    124: CaseSpec(
        turns=["Quiero la ruta mas barata sin bajar del 20%", "Madrid a Valencia, salgo con 60%"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "StationPreviewCard", "StationList", "AssistantMessage"},),
        expected_text_any=("20", "60", "no puedo", "consumo", "precio"),
    ),
    125: CaseSpec(
        turns=["Buscame carga cerca de mi hotel en Valencia centro"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("valencia", "hotel", "aproxim", "confirma"),
    ),
    126: CaseSpec(
        turns=["Duermo en Granada y llego tarde, quiero cargar cerca del alojamiento"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("granada", "noche", "no valida seguridad", "confirma"),
    ),
    127: CaseSpec(
        turns=["Voy a una boda en Cordoba el sabado, quiero dejar el coche cargando cerca"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("cordoba", "sabado", "disponibilidad", "tarifas"),
    ),
    128: CaseSpec(
        turns=["Mañana trabajo en Sevilla centro, dime donde cargar por la mañana"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("sevilla", "mañana", "disponibilidad", "cambiar"),
    ),
    129: CaseSpec(
        turns=["Voy con ninos por Cordoba, necesito banos y algo para comer mientras cargo"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("ninos", "banos", "comer", "confirma"),
    ),
    130: CaseSpec(
        turns=["Busca cargador barato cerca de Valencia, no me importa tardar mas"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("valencia", "tarifa", "precio", "si esta disponible"),
    ),
    131: CaseSpec(
        turns=["Quiero el cargador mas seguro de noche en Madrid"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("madrid", "noche", "no valida seguridad", "entorno"),
    ),
    132: CaseSpec(
        turns=["Hay cargadores gratis en Cordoba?"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList", "AssistantMessage"},),
        expected_text_any=("cordoba", "gratis", "tarifa", "no puedo"),
    ),
    133: CaseSpec(
        turns=["Que es CCS2?"],
        forbidden_tools={"plan_route", "search_destination_chargers"},
        any_components=({"AssistantMessage"},),
        expected_text_any=("ccs2", "conector", "carga"),
    ),
    134: CaseSpec(
        turns=["Cuanto tarda cargar un coche electrico?"],
        forbidden_tools={"plan_route", "search_destination_chargers"},
        any_components=({"AssistantMessage"},),
        expected_text_any=("depende", "bateria", "potencia", "kw"),
    ),
    135: CaseSpec(
        turns=["Puedes reservarme un cargador?"],
        forbidden_tools={"plan_route", "search_destination_chargers"},
        any_components=({"AssistantMessage"},),
        expected_text_any=("no puedo reservar", "no puedo", "proveedor", "app"),
    ),
    136: CaseSpec(
        turns=["Mi coche usa CHAdeMO, tenlo en cuenta"],
        forbidden_tools={"plan_route", "search_destination_chargers"},
        any_components=({"AssistantMessage"},),
        expected_text_any=("chademo", "origen", "destino", "ubicacion"),
    ),
    137: CaseSpec(
        turns=["Voy de Madrid a Valencia con 60%", "Mejor salgo de Toledo"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "StationPreviewCard", "StationList"},),
        expected_text_any=("toledo", "valencia", "no puedo", "consumo"),
    ),
    138: CaseSpec(
        turns=["Busca cargador en Cordoba", "Mejor cerca de Granada"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("granada", "cordoba", "aproxim", "confirma"),
    ),
    139: CaseSpec(
        turns=["Voy a Granada mañana", "No tengo hotel, solo quiero zona centro"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("granada", "centro", "mañana", "disponibilidad"),
    ),
    140: CaseSpec(
        turns=["Estoy en Valencia con 20%", "Necesito CCS2 y cafeteria"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("valencia", "20", "ccs2", "cafeteria"),
    ),
    141: CaseSpec(
        turns=["Estoy al 5%, ayudame ya"],
        forbidden_tools={"plan_route", "search_destination_chargers"},
        any_components=({"PositionRequestCard", "AssistantMessage"},),
        expected_text_any=("ubicacion", "donde", "zona", "coordenadas"),
    ),
    142: CaseSpec(
        turns=["Estoy en Cordoba al 5%, no quiero moverme mucho"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("cordoba", "5", "cerca", "confirma"),
    ),
    143: CaseSpec(
        turns=["Madrid a Valencia con Tesla, prefiero supercargadores"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "StationPreviewCard", "StationList", "AssistantMessage"},),
        expected_text_any=("tesla", "no puedo", "proveedor", "autorizad"),
    ),
    144: CaseSpec(
        turns=["Quiero evitar autopistas de peaje de Madrid a Valencia"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "AssistantMessage"},),
        expected_text_any=("peaje", "proveedor", "no puedo", "ruta"),
    ),
    145: CaseSpec(
        turns=["Madrid a Barcelona, quiero ver carga cada 150 km por si acaso"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "StationPreviewCard", "StationList"},),
        expected_text_any=("150", "no puedo", "consumo", "corredor"),
    ),
    146: CaseSpec(
        turns=["Cuanto me costara cargar en Madrid-Valencia?"],
        any_components=({"RouteCorridorCard", "StationPreviewCard", "StationList", "AssistantMessage"},),
        expected_text_any=("precio", "tarifa", "no puedo", "consumo", "modelo", "bateria"),
    ),
    147: CaseSpec(
        turns=["Busca una estacion grande con muchos puestos cerca de Cordoba"],
        expected_tools={"search_destination_chargers"},
        any_components=({"StationPreviewCard", "StationList"},),
        expected_text_any=("cordoba", "puestos", "grande", "confirma"),
    ),
    148: CaseSpec(
        turns=["Vengo de Malaga a Madrid y salgo con 50%, quiero parar una vez"],
        expected_tools={"plan_route"},
        any_components=({"RouteCorridorCard", "StationPreviewCard", "StationList"},),
        expected_text_any=("malaga", "madrid", "50", "no puedo"),
    ),
    149: CaseSpec(
        turns=["Estoy en un parking sin cobertura, que datos te doy para buscar luego?"],
        forbidden_tools={"plan_route", "search_destination_chargers"},
        any_components=({"AssistantMessage"},),
        expected_text_any=("ubicacion", "direccion", "bateria", "conector"),
    ),
    150: CaseSpec(
        turns=["No quiero compartir mi ubicacion exacta, estoy en Cordoba"],
        any_components=({"AssistantMessage", "StationPreviewCard", "StationList"},),
        expected_text_any=("cordoba", "aproxim", "ubicacion exacta", "que necesitas"),
    ),
}


CATEGORY_BY_CASE = {
    1: "urgent_charging",
    2: "urgent_charging",
    3: "urgent_charging_followup",
    4: "clarification",
    5: "urgent_charging_comfort",
    6: "route_planning",
    7: "route_planning",
    8: "route_clarification",
    9: "route_clarification",
    10: "route_planning",
    11: "clarification",
    12: "preference_capture",
    13: "clarification",
    14: "clarification",
    15: "clarification",
    16: "destination_context",
    17: "destination_charging",
    18: "destination_charging",
    19: "destination_charging",
    20: "clarification",
    21: "route_comfort",
    22: "comfort_charging",
    23: "safety_preference",
    24: "route_comfort",
    25: "route_comfort",
    26: "route_vehicle_constraint",
    27: "charger_capacity",
    28: "route_planning",
    29: "route_preference",
    30: "route_vehicle_context",
    101: "urgent_charging",
    102: "clarification",
    103: "route_comfort",
    104: "route_clarification",
    105: "destination_charging",
    106: "clarification",
    107: "safety_preference",
    108: "route_vehicle_constraint",
    109: "route_preference",
    110: "clarification",
    111: "comfort_charging",
    112: "route_vehicle_context",
}

ALLOWED_UI_FAMILIES_BY_CASE = {
    1: ("charger_recommendation",),
    2: ("charger_recommendation",),
    3: ("charger_recommendation", "assistant_only"),
    4: ("clarification", "assistant_only"),
    5: ("charger_recommendation",),
    6: ("route_with_station", "route_summary", "station_with_route_context"),
    7: ("route_with_station", "route_summary", "station_with_route_context"),
    8: ("route_summary", "assistant_only"),
    9: ("route_summary", "assistant_only"),
    10: ("route_with_station", "station_with_route_context"),
    11: ("clarification", "assistant_only"),
    12: ("assistant_only",),
    13: ("clarification", "assistant_only"),
    14: ("clarification", "assistant_only"),
    15: ("clarification", "assistant_only"),
    16: ("destination_context", "assistant_only", "charger_recommendation"),
    17: ("destination_charging", "charger_recommendation"),
    18: ("destination_charging", "charger_recommendation"),
    19: ("destination_charging", "charger_recommendation"),
    20: ("clarification", "assistant_only"),
    21: ("route_with_station", "station_with_route_context"),
    22: ("charger_recommendation",),
    23: ("charger_recommendation",),
    24: ("route_with_station", "station_with_route_context"),
    25: ("route_with_station", "station_with_route_context"),
    26: ("route_with_station", "station_with_route_context"),
    27: ("charger_recommendation",),
    28: ("route_summary", "route_with_station", "station_with_route_context"),
    29: ("route_with_station", "station_with_route_context"),
    30: ("route_with_station", "route_summary", "station_with_route_context"),
    101: ("charger_recommendation",),
    102: ("clarification", "assistant_only"),
    103: ("route_with_station", "station_with_route_context", "route_summary"),
    104: ("route_summary", "assistant_only", "station_with_route_context"),
    105: ("destination_charging", "charger_recommendation"),
    106: ("clarification", "assistant_only"),
    107: ("charger_recommendation",),
    108: ("route_with_station", "station_with_route_context", "route_summary"),
    109: ("route_with_station", "station_with_route_context", "route_summary"),
    110: ("clarification", "assistant_only"),
    111: ("charger_recommendation",),
    112: ("route_with_station", "route_summary", "station_with_route_context"),
}

CATEGORY_BY_CASE.update(
    {
        113: "urgent_charging",
        114: "clarification",
        115: "urgent_charging",
        116: "urgent_charging",
        117: "route_comfort",
        118: "route_clarification",
        119: "route_clarification",
        120: "route_preference",
        121: "route_comfort",
        122: "clarification",
        123: "clarification",
        124: "route_price",
        125: "destination_charging",
        126: "destination_charging",
        127: "destination_charging",
        128: "destination_charging",
        129: "comfort_charging",
        130: "price_charging",
        131: "safety_preference",
        132: "price_charging",
        133: "simple_answer",
        134: "simple_answer",
        135: "capability_boundary",
        136: "preference_capture",
        137: "route_followup_correction",
        138: "destination_followup_correction",
        139: "destination_followup",
        140: "urgent_charging_followup",
        141: "clarification",
        142: "urgent_charging",
        143: "route_vehicle_context",
        144: "route_preference",
        145: "route_preference",
        146: "route_price",
        147: "charger_capacity",
        148: "route_preference",
        149: "offline_preparation",
        150: "privacy_preserving_location",
    }
)

ALLOWED_UI_FAMILIES_BY_CASE.update(
    {
        113: ("charger_recommendation",),
        114: ("clarification", "assistant_only"),
        115: ("charger_recommendation",),
        116: ("charger_recommendation",),
        117: ("route_with_station", "station_with_route_context", "route_summary"),
        118: ("route_summary", "assistant_only", "station_with_route_context"),
        119: ("route_summary", "assistant_only", "station_with_route_context"),
        120: ("route_with_station", "station_with_route_context", "route_summary"),
        121: ("route_with_station", "station_with_route_context", "route_summary"),
        122: ("clarification", "assistant_only"),
        123: ("clarification", "assistant_only"),
        124: ("route_with_station", "station_with_route_context", "route_summary"),
        125: ("destination_charging", "charger_recommendation"),
        126: ("destination_charging", "charger_recommendation"),
        127: ("destination_charging", "charger_recommendation"),
        128: ("destination_charging", "charger_recommendation"),
        129: ("charger_recommendation",),
        130: ("charger_recommendation",),
        131: ("charger_recommendation",),
        132: ("charger_recommendation", "assistant_only"),
        133: ("assistant_only",),
        134: ("assistant_only",),
        135: ("assistant_only",),
        136: ("assistant_only",),
        137: ("route_with_station", "station_with_route_context", "route_summary"),
        138: ("destination_charging", "charger_recommendation"),
        139: ("destination_charging", "charger_recommendation"),
        140: ("charger_recommendation",),
        141: ("clarification", "assistant_only"),
        142: ("charger_recommendation",),
        143: ("route_with_station", "station_with_route_context", "route_summary", "assistant_only"),
        144: ("route_summary", "assistant_only", "station_with_route_context"),
        145: ("route_with_station", "station_with_route_context", "route_summary"),
        146: ("route_with_station", "station_with_route_context", "route_summary", "assistant_only"),
        147: ("charger_recommendation",),
        148: ("route_with_station", "station_with_route_context", "route_summary"),
        149: ("assistant_only",),
        150: ("assistant_only", "charger_recommendation"),
    }
)


def spec_metadata(case_id: int, spec: CaseSpec) -> dict[str, Any]:
    return {
        "case": case_id,
        "category": CATEGORY_BY_CASE.get(case_id, "unknown"),
        "allowedUiFamilies": list(ALLOWED_UI_FAMILIES_BY_CASE.get(case_id, ())),
        "expectedTools": sorted(spec.expected_tools),
        "forbiddenTools": sorted(spec.forbidden_tools),
        "expectedComponents": sorted(spec.expected_components),
        "anyComponents": [sorted(options) for options in spec.any_components],
        "expectedTextAny": list(spec.expected_text_any),
    }


def specs_for_dataset(dataset: str) -> dict[int, CaseSpec]:
    if dataset == "outcome":
        return OUTCOME_CASE_SPECS
    raise ValueError(f"Unknown dataset: {dataset}")


def default_case_range(dataset: str, specs: dict[int, CaseSpec]) -> tuple[int, int]:
    return min(specs), max(specs)


def build_dataset(
    case_ids: list[int],
    *,
    specs: dict[int, CaseSpec] | None = None,
) -> Dataset[dict[str, Any], dict[str, Any], dict[str, Any]]:
    specs = specs or OUTCOME_CASE_SPECS
    cases = [
        Case(
            name=f"case-{case_id:02d}",
            inputs={"case": case_id, "turns": specs[case_id].turns},
            metadata=spec_metadata(case_id, specs[case_id]),
        )
        for case_id in case_ids
    ]
    return Dataset(
        name="kalmio-conversation-evals",
        cases=cases,
        evaluators=[
            CaseAcceptanceEvaluator(),
            HardContractEvaluator(),
            ToolPolicyEvaluator(),
            UIFamilyEvaluator(),
            SafetyEvaluator(),
            TaskSuccessEvaluator(),
            MetricsEvaluator(),
        ],
    )


def components(output: dict[str, Any]) -> set[str]:
    return {str(item) for item in output.get("components") or []}


def tools(output: dict[str, Any]) -> set[str]:
    return {str(item) for item in output.get("tools") or []}


def failures(output: dict[str, Any]) -> list[str]:
    return [str(item) for item in output.get("failures") or []]


def metrics(output: dict[str, Any]) -> dict[str, Any]:
    value = output.get("metrics")
    return value if isinstance(value, dict) else {}


def is_http_error(output: dict[str, Any]) -> bool:
    return any(item.startswith("HTTP ") for item in failures(output))


def has_llm_error(output: dict[str, Any]) -> bool:
    return bool(metrics(output).get("llmErrorCount") or 0)


def has_tool_error(output: dict[str, Any]) -> bool:
    return bool(metrics(output).get("toolErrorCount") or 0)


def ui_family_matches(output: dict[str, Any], family: str) -> bool:
    present = components(output)
    has_assistant = "AssistantMessage" in present
    has_position = "PositionRequestCard" in present
    has_station = bool({"StationPreviewCard", "StationList"} & present)
    has_route = "RouteCorridorCard" in present
    if family == "assistant_only":
        return has_assistant and not has_station and not has_route
    if family == "clarification":
        return has_position or (has_assistant and not tools(output))
    if family == "charger_recommendation":
        return has_station
    if family == "destination_context":
        return has_assistant and not has_route
    if family == "destination_charging":
        return has_station and has_assistant
    if family == "route_summary":
        return has_route
    if family == "route_with_station":
        return has_route and has_station
    if family == "station_with_route_context":
        return has_station and "plan_route" in tools(output)
    return False


@dataclass
class CaseAcceptanceEvaluator(Evaluator[dict[str, Any], dict[str, Any], dict[str, Any]]):
    def evaluate(self, ctx: EvaluatorContext[dict[str, Any], dict[str, Any], dict[str, Any]]) -> dict[str, bool]:
        return {"case_acceptance": bool(ctx.output.get("ok"))}


@dataclass
class HardContractEvaluator(Evaluator[dict[str, Any], dict[str, Any], dict[str, Any]]):
    def evaluate(self, ctx: EvaluatorContext[dict[str, Any], dict[str, Any], dict[str, Any]]) -> dict[str, bool]:
        no_http_error = not is_http_error(ctx.output)
        no_llm_error = not has_llm_error(ctx.output)
        no_tool_error = not has_tool_error(ctx.output)
        no_fallback = not bool(metrics(ctx.output).get("fallbackCount") or 0)
        return {
            "no_http_error": no_http_error,
            "no_llm_error": no_llm_error,
            "no_tool_error": no_tool_error,
            "no_fallback": no_fallback,
            "hard_contract_pass": no_http_error and no_llm_error and no_tool_error and no_fallback,
        }


@dataclass
class ToolPolicyEvaluator(Evaluator[dict[str, Any], dict[str, Any], dict[str, Any]]):
    def evaluate(self, ctx: EvaluatorContext[dict[str, Any], dict[str, Any], dict[str, Any]]) -> dict[str, bool]:
        metadata = ctx.metadata or {}
        observed = tools(ctx.output)
        expected = set(metadata.get("expectedTools") or [])
        forbidden = set(metadata.get("forbiddenTools") or [])
        return {
            "expected_tools_pass": expected <= observed,
            "forbidden_tools_pass": not (forbidden & observed),
            "tool_policy_pass": expected <= observed and not (forbidden & observed),
        }


@dataclass
class UIFamilyEvaluator(Evaluator[dict[str, Any], dict[str, Any], dict[str, Any]]):
    def evaluate(self, ctx: EvaluatorContext[dict[str, Any], dict[str, Any], dict[str, Any]]) -> dict[str, bool]:
        allowed = tuple((ctx.metadata or {}).get("allowedUiFamilies") or ())
        if not allowed:
            return {"ui_family_pass": True}
        return {
            "ui_family_pass": any(ui_family_matches(ctx.output, family) for family in allowed),
        }


@dataclass
class SafetyEvaluator(Evaluator[dict[str, Any], dict[str, Any], dict[str, Any]]):
    def evaluate(self, ctx: EvaluatorContext[dict[str, Any], dict[str, Any], dict[str, Any]]) -> dict[str, bool]:
        failure_text = " ".join(failures(ctx.output))
        expected_text = tuple((ctx.metadata or {}).get("expectedTextAny") or ())
        visible_text = normalize(str(ctx.output.get("visibleText") or ""))
        expected_text_present = True
        if expected_text:
            expected_text_present = any(term in visible_text for term in expected_text)
        no_fabrication_failure = "afirma cargadores encontrados/disponibles sin herramienta" not in failure_text
        no_tool_failure = "herramientas con error" not in failure_text
        return {
            "no_fabrication_failure": no_fabrication_failure,
            "no_tool_failure": no_tool_failure,
            "expected_text_hint_present": expected_text_present,
            "safety_pass": no_fabrication_failure and no_tool_failure,
        }


@dataclass
class TaskSuccessEvaluator(Evaluator[dict[str, Any], dict[str, Any], dict[str, Any]]):
    def evaluate(self, ctx: EvaluatorContext[dict[str, Any], dict[str, Any], dict[str, Any]]) -> dict[str, bool]:
        metadata = ctx.metadata or {}
        observed = tools(ctx.output)
        expected = set(metadata.get("expectedTools") or [])
        forbidden = set(metadata.get("forbiddenTools") or [])
        allowed_families = tuple(metadata.get("allowedUiFamilies") or ())
        ui_pass = not allowed_families or any(ui_family_matches(ctx.output, family) for family in allowed_families)
        return {
            "task_success": (
                not is_http_error(ctx.output)
                and not has_tool_error(ctx.output)
                and expected <= observed
                and not (forbidden & observed)
                and ui_pass
            )
        }


@dataclass
class MetricsEvaluator(Evaluator[dict[str, Any], dict[str, Any], dict[str, Any]]):
    def evaluate(self, ctx: EvaluatorContext[dict[str, Any], dict[str, Any], dict[str, Any]]) -> dict[str, float]:
        data = metrics(ctx.output)
        cost = data.get("cost") if isinstance(data.get("cost"), dict) else {}
        return {
            "duration_ms": float(data.get("durationMs") or 0),
            "llm_calls": float(data.get("llmCallCount") or 0),
            "tool_calls": float(data.get("toolCallCount") or 0),
            "repairs": float(data.get("repairCount") or 0),
            "fallbacks": float(data.get("fallbackCount") or 0),
            "estimated_cost_usd": float(cost.get("totalCostUsd") or 0),
        }


def evaluation_result_to_dict(value: Any) -> dict[str, Any]:
    return {
        "value": value.value,
        "reason": value.reason,
        "source": getattr(value.source, "name", None),
    }


def jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return repr(value)


def report_to_dict(report: Any) -> dict[str, Any]:
    cases = []
    assertion_totals: dict[str, dict[str, int]] = {}
    score_totals: dict[str, list[float]] = {}
    for case in report.cases:
        assertions = {name: evaluation_result_to_dict(value) for name, value in case.assertions.items()}
        scores = {name: evaluation_result_to_dict(value) for name, value in case.scores.items()}
        for name, value in case.assertions.items():
            item = assertion_totals.setdefault(name, {"passed": 0, "total": 0})
            item["total"] += 1
            if value.value is True:
                item["passed"] += 1
        for name, value in case.scores.items():
            try:
                score_totals.setdefault(name, []).append(float(value.value))
            except (TypeError, ValueError):
                pass
        cases.append(
            {
                "name": case.name,
                "inputs": case.inputs,
                "metadata": case.metadata,
                "output": case.output,
                "assertions": assertions,
                "scores": scores,
                "taskDurationSeconds": case.task_duration,
                "totalDurationSeconds": case.total_duration,
                "traceId": case.trace_id,
                "spanId": case.span_id,
            }
        )
    return {
        "name": report.name,
        "traceId": report.trace_id,
        "spanId": report.span_id,
        "assertionSummary": {
            name: {
                **item,
                "passRate": round(item["passed"] / item["total"], 4) if item["total"] else 0,
            }
            for name, item in assertion_totals.items()
        },
        "scoreAverages": {
            name: round(sum(values) / len(values), 6)
            for name, values in score_totals.items()
            if values
        },
        "cases": cases,
        "failures": jsonable(report.failures),
    }


def write_markdown(summary: dict[str, Any], output: Path) -> None:
    assertions = summary.get("assertionSummary") or {}
    scores = summary.get("scoreAverages") or {}
    lines = [
        "# Kalmio Conversation Eval Report",
        "",
        f"- Run: `{summary.get('name')}`",
        f"- Cases: `{len(summary.get('cases') or [])}`",
        "",
        "## Assertions",
        "",
        "| Evaluator | Passed | Total | Pass rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, item in sorted(assertions.items()):
        lines.append(f"| `{name}` | `{item['passed']}` | `{item['total']}` | `{item['passRate']:.1%}` |")
    lines.extend(["", "## Score Averages", "", "| Metric | Average |", "| --- | ---: |"])
    for name, value in sorted(scores.items()):
        lines.append(f"| `{name}` | `{value}` |")
    lines.extend(["", "## Failed Task Success Cases", ""])
    failed = [
        case
        for case in summary.get("cases") or []
        if ((case.get("assertions") or {}).get("task_success") or {}).get("value") is not True
    ]
    if not failed:
        lines.append("- Ninguno.")
    else:
        for case in failed:
            output_failures = (case.get("output") or {}).get("failures") or []
            lines.append(f"- `{case.get('name')}`: {output_failures}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def configure_eval_logfire(enable: bool, label: str) -> None:
    if not enable:
        return
    os.environ["KALMIO_LOGFIRE_ENABLED"] = "true"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from config.logfire import configure_logfire

    configure_logfire(
        service_name=os.getenv("KALMIO_LOGFIRE_SERVICE_NAME", "kalmio-conversation-evals"),
        environment=os.getenv("KALMIO_ENV", "development"),
        local_default=True,
    )
    try:
        import logfire

        logfire.info("starting conversation eval run", label=label)
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Pydantic Evals for Kalmio conversation cases.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--dataset", choices=["outcome"], default="outcome")
    parser.add_argument("--from", dest="case_from", type=int)
    parser.add_argument("--to", dest="case_to", type=int)
    parser.add_argument("--trace-file", default="backend/.tmp/agent-traces.jsonl")
    parser.add_argument("--label", default="conversation-evals")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--output", type=Path, help="Write eval summary JSON.")
    parser.add_argument("--markdown-output", type=Path, help="Write eval summary Markdown.")
    parser.add_argument("--logfire", action="store_true", help="Enable Logfire for this eval run.")
    args = parser.parse_args()

    configure_eval_logfire(args.logfire or os.getenv("KALMIO_LOGFIRE_ENABLED") == "true", args.label)

    specs = specs_for_dataset(args.dataset)
    default_from, default_to = default_case_range(args.dataset, specs)
    case_from = args.case_from if args.case_from is not None else default_from
    case_to = args.case_to if args.case_to is not None else default_to
    case_ids = [case_id for case_id in range(case_from, case_to + 1) if case_id in specs]
    missing = sorted(set(range(case_from, case_to + 1)) - set(case_ids))
    if missing:
        print(f"Casos sin spec en este runner: {missing}", file=sys.stderr)
        return 2

    api_base = args.api_base.rstrip("/")
    trace_file = Path(args.trace_file) if args.trace_file else None
    dataset = build_dataset(case_ids, specs=specs)

    def task(inputs: dict[str, Any]) -> dict[str, Any]:
        case_id = int(inputs["case"])
        try:
            return run_case(api_base, case_id, specs[case_id], trace_file)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            return {"case": case_id, "ok": False, "failures": [f"HTTP {exc.code}: {detail[:500]}"]}
        except Exception as exc:
            return {"case": case_id, "ok": False, "failures": [repr(exc)]}

    report = dataset.evaluate_sync(
        task,
        name=args.label,
        task_name="kalmio_backend_conversation",
        max_concurrency=args.max_concurrency,
        progress=True,
        repeat=args.repeat,
        metadata={"apiBase": api_base, "traceFile": str(trace_file) if trace_file else None, "dataset": args.dataset},
    )
    summary = report_to_dict(report)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    if args.markdown_output:
        write_markdown(summary, args.markdown_output)
    print(text)
    task_success = (summary.get("assertionSummary") or {}).get("task_success") or {}
    return 0 if task_success.get("passed") == task_success.get("total") else 1


if __name__ == "__main__":
    raise SystemExit(main())
