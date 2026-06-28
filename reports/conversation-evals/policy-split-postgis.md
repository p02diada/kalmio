# Kalmio Conversation Eval Report

- Run: `policy-split-postgis`
- Cases: `50`

## Assertions

| Evaluator | Passed | Total | Pass rate |
| --- | ---: | ---: | ---: |
| `case_acceptance` | `50` | `50` | `100.0%` |
| `expected_text_hint_present` | `50` | `50` | `100.0%` |
| `expected_tools_pass` | `50` | `50` | `100.0%` |
| `forbidden_tools_pass` | `50` | `50` | `100.0%` |
| `hard_contract_pass` | `50` | `50` | `100.0%` |
| `no_fabrication_failure` | `50` | `50` | `100.0%` |
| `no_fallback` | `50` | `50` | `100.0%` |
| `no_http_error` | `50` | `50` | `100.0%` |
| `no_llm_error` | `50` | `50` | `100.0%` |
| `no_tool_error` | `50` | `50` | `100.0%` |
| `no_tool_failure` | `50` | `50` | `100.0%` |
| `safety_pass` | `50` | `50` | `100.0%` |
| `task_success` | `50` | `50` | `100.0%` |
| `tool_policy_pass` | `50` | `50` | `100.0%` |
| `ui_family_pass` | `50` | `50` | `100.0%` |

## Score Averages

| Metric | Average |
| --- | ---: |
| `duration_ms` | `5175.1896` |
| `estimated_cost_usd` | `0.000518` |
| `fallbacks` | `0.0` |
| `llm_calls` | `1.12` |
| `repairs` | `0.0` |
| `tool_calls` | `0.92` |

## Failed Task Success Cases

- Ninguno.
