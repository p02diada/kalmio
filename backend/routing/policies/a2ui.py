from __future__ import annotations

from typing import Any

from routing.policies.base import PolicyContext, PolicyIssue, messages_from_issues
from routing.policies.components import ComponentTraceabilityPolicy
from routing.policies.copy import CopyAndFactPolicy


A2UI_POLICIES = (
    ComponentTraceabilityPolicy(),
    CopyAndFactPolicy(),
)


def run_a2ui_policies(context: PolicyContext) -> list[PolicyIssue]:
    issues: list[PolicyIssue] = []
    for policy in A2UI_POLICIES:
        issues.extend(policy.check(context))
    return issues


def a2ui_contract_issues(
    blocks: list[dict[str, Any]],
    tool_history: list[dict[str, Any]],
    message: str = "",
    history_blocks: list[dict] | None = None,
) -> list[str]:
    context = PolicyContext.from_inputs(
        blocks,
        tool_history,
        message=message,
        history_blocks=history_blocks or [],
    )
    return messages_from_issues(run_a2ui_policies(context))
