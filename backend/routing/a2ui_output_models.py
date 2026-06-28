from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


A2UI_OUTPUT_CONTRACT_ID = "https://kalmio.app/agent/contracts/a2ui-output/v1"
A2UI_OUTPUT_CONTRACT_VERSION = "v1"


class A2UIBlockOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    version: int = Field(1, ge=1)
    props: dict[str, Any] = Field(default_factory=dict)


class PydanticAIFinalOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    intent: str | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    blocks: list[A2UIBlockOutput]
    metadata: dict[str, Any] | None = None
    rationale: str | None = None

    @model_validator(mode="after")
    def require_blocks(self) -> "PydanticAIFinalOutput":
        if not self.blocks:
            raise ValueError("La respuesta final necesita blocks A2UI.")
        return self

    def block_dicts(self) -> list[dict[str, Any]]:
        return [block.model_dump() for block in self.blocks]


class PydanticAIDecision(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["tool_call", "final"]
    intent: str | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    blocks: list[A2UIBlockOutput] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None
    rationale: str | None = None

    @model_validator(mode="after")
    def require_decision_payload(self) -> "PydanticAIDecision":
        if self.type == "tool_call" and not self.tool:
            raise ValueError("tool_call necesita tool.")
        if self.type == "final" and not self.blocks:
            raise ValueError("final necesita blocks.")
        return self
