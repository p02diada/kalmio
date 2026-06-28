from __future__ import annotations

import time
from typing import Any, Literal

from django.conf import settings
from pydantic import BaseModel, Field

from routing.instrumentation import (
    elapsed_ms,
    estimate_deepseek_cost,
    normalize_usage,
    record_trace_event,
    to_plain,
)


class PydanticAIFinalDecision(BaseModel):
    type: Literal["final"]
    blocks: list[dict[str, Any]]


class PydanticAIToolCallDecision(BaseModel):
    type: Literal["tool_call"]
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


PydanticAIDecision = PydanticAIFinalDecision | PydanticAIToolCallDecision


def request_pydantic_ai_decision(
    message: str,
    tool_history: list[dict[str, Any]] | None = None,
    repair_issues: list[str] | None = None,
    candidate_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    from routing.agent import AgentResponseError, conversation_agent_prompt, parse_agent_decision

    prompt = conversation_agent_prompt(
        message,
        tool_history=tool_history or [],
        repair_issues=repair_issues or [],
        candidate_blocks=candidate_blocks or [],
    )
    prompt = (
        f"{prompt}\n"
        "Contrato de salida para este runtime: devuelve exactamente una decisión estructurada validable. "
        "Para responder al usuario usa type='final' y blocks. Para pedir datos autorizados usa "
        "type='tool_call', tool y args. No mezcles tool_call dentro de blocks."
    )
    output = run_pydantic_ai_deepseek_decision(prompt)
    try:
        return parse_agent_decision(output)
    except AgentResponseError:
        raise
    except Exception as exc:
        raise AgentResponseError(f"Pydantic AI devolvió una decisión no parseable: {exc}") from exc


def run_pydantic_ai_deepseek_decision(prompt: str) -> dict[str, Any]:
    from routing.agent import AgentResponseError

    api_key = getattr(settings, "KALMIO_DEEPSEEK_API_KEY", "")
    if not api_key:
        raise AgentResponseError("DeepSeek no está configurado: falta KALMIO_DEEPSEEK_API_KEY o DEEPSEEK_API_KEY.")

    try:
        from pydantic_ai import Agent
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        from pydantic_ai.settings import ModelSettings
    except ImportError as exc:
        raise AgentResponseError("Pydantic AI no está instalado. Ejecuta pip install -r requirements.txt.") from exc

    model_name = getattr(settings, "KALMIO_DEEPSEEK_MODEL", "deepseek-v4-flash")
    model_settings = ModelSettings(
        max_tokens=getattr(settings, "KALMIO_DEEPSEEK_MAX_TOKENS", 1800),
        temperature=getattr(settings, "KALMIO_DEEPSEEK_TEMPERATURE", 0),
        timeout=getattr(settings, "KALMIO_DEEPSEEK_TIMEOUT_SECONDS", 30),
        extra_body={
            "thinking": {
                "type": "enabled" if getattr(settings, "KALMIO_DEEPSEEK_THINKING", False) else "disabled",
            }
        },
    )
    model = OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(
            base_url=getattr(settings, "KALMIO_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            api_key=api_key,
        ),
        settings=model_settings,
    )
    agent = Agent(
        model,
        output_type=PydanticAIDecision,
        system_prompt=(
            "Eres el runtime estructurado del agente EV de Kalmio. "
            "La respuesta final debe cumplir el contrato A2UI interno que recibes en el prompt."
        ),
        retries=1,
    )

    started = time.perf_counter()
    request_payload = pydantic_ai_request_payload(prompt, model_name, model_settings)
    try:
        result = agent.run_sync(prompt)
    except Exception as exc:
        record_trace_event(
            event="llm_api_call",
            name="pydantic_ai.Agent.run_sync",
            status="error",
            provider="pydantic_ai:deepseek",
            model=model_name,
            duration_ms=elapsed_ms(started),
            metadata=pydantic_ai_request_metadata(request_payload),
            request_payload=request_payload,
            error=str(exc),
        )
        raise AgentResponseError(f"Pydantic AI no pudo devolver una decisión con DeepSeek: {exc}") from exc

    usage = normalize_usage(to_plain(result.usage))
    output = result.output.model_dump()
    record_trace_event(
        event="llm_api_call",
        name="pydantic_ai.Agent.run_sync",
        status="ok",
        provider="pydantic_ai:deepseek",
        model=model_name,
        duration_ms=elapsed_ms(started),
        usage=usage,
        cost=estimate_deepseek_cost(usage),
        metadata={
            **pydantic_ai_request_metadata(request_payload),
            "outputType": output.get("type"),
        },
        request_payload=request_payload,
        response_payload={
            "output": output,
            "usage": to_plain(result.usage),
            "messages": to_plain(result.new_messages()),
        },
    )
    return output


def pydantic_ai_request_payload(prompt: str, model_name: str, model_settings: Any) -> dict[str, Any]:
    return {
        "model": model_name,
        "prompt": prompt,
        "outputType": "PydanticAIDecision",
        "settings": to_plain(model_settings),
    }


def pydantic_ai_request_metadata(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "promptChars": len(str(request.get("prompt") or "")),
        "outputType": request.get("outputType"),
        "maxTokens": (request.get("settings") or {}).get("max_tokens"),
        "temperature": (request.get("settings") or {}).get("temperature"),
    }
