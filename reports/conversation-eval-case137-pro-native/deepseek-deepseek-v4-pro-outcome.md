# Kalmio Conversation Eval Report

- Run: `deepseek-deepseek-v4-pro-outcome`
- Cases: `1`

## Assertions

| Evaluator | Passed | Total | Pass rate |
| --- | ---: | ---: | ---: |
| `case_acceptance` | `0` | `1` | `0.0%` |
| `expected_text_hint_present` | `1` | `1` | `100.0%` |
| `expected_tools_pass` | `1` | `1` | `100.0%` |
| `forbidden_tools_pass` | `1` | `1` | `100.0%` |
| `hard_contract_pass` | `0` | `1` | `0.0%` |
| `no_fabrication_failure` | `1` | `1` | `100.0%` |
| `no_fallback` | `1` | `1` | `100.0%` |
| `no_http_error` | `1` | `1` | `100.0%` |
| `no_llm_error` | `0` | `1` | `0.0%` |
| `no_tool_error` | `0` | `1` | `0.0%` |
| `no_tool_failure` | `0` | `1` | `0.0%` |
| `safety_pass` | `0` | `1` | `0.0%` |
| `task_success` | `0` | `1` | `0.0%` |
| `tool_policy_pass` | `1` | `1` | `100.0%` |
| `ui_family_pass` | `1` | `1` | `100.0%` |

## Score Averages

| Metric | Average |
| --- | ---: |
| `duration_ms` | `43279.99` |
| `estimated_cost_usd` | `0.0` |
| `fallbacks` | `0.0` |
| `llm_calls` | `2.0` |
| `repairs` | `0.0` |
| `tool_calls` | `3.0` |

## Failed Task Success Cases

- `case-137`: ["herramientas con error: [{'tool': 'resolve_location', 'status': 'error', 'metadata': {'argsValid': True, 'error': 'No conozco esa ubicación. Pide ciudad o coordenadas exactas.', 'ok': False, 'resultValid': True, 'toolContractId': 'https://kalmio.app/agent/contracts/conversation-tools/v1/resolve_location', 'toolContractVersion': 'v1'}}]"]
