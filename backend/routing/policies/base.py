from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from routing.evidence import ToolFactLedger, build_tool_fact_ledger


class PolicyIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    path: str | None = None
    severity: Literal["error", "warning"] = "error"


def issue(code: str, message: str, path: str | None = None) -> PolicyIssue:
    return PolicyIssue(code=code, message=message, path=path)


def issues(code: str, messages: list[str], path: str | None = None) -> list[PolicyIssue]:
    return [issue(code, message, path=path) for message in messages]


class PolicyContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    blocks: list[dict[str, Any]]
    tool_history: list[dict[str, Any]] = Field(default_factory=list)
    message: str = ""
    history_blocks: list[dict[str, Any]] = Field(default_factory=list)
    ledger: ToolFactLedger

    @classmethod
    def from_inputs(
        cls,
        blocks: list[dict[str, Any]],
        tool_history: list[dict[str, Any]],
        message: str = "",
        history_blocks: list[dict[str, Any]] | None = None,
    ) -> "PolicyContext":
        return cls(
            blocks=blocks,
            tool_history=tool_history,
            message=message,
            history_blocks=history_blocks or [],
            ledger=build_tool_fact_ledger(tool_history, history_blocks=history_blocks or []),
        )

    @property
    def facts(self) -> dict[str, Any]:
        return self.ledger.as_policy_facts()


class Policy(Protocol):
    code: str

    def check(self, context: PolicyContext) -> list[PolicyIssue]:
        ...


def messages_from_issues(issues: list[PolicyIssue]) -> list[str]:
    seen: set[str] = set()
    messages: list[str] = []
    for issue in issues:
        if issue.message in seen:
            continue
        seen.add(issue.message)
        messages.append(issue.message)
    return messages
