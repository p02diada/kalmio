# Kalmio Conversation Eval Report

- Run: `deepseek-deepseek-v4-pro-outcome`
- Cases: `4`

## Assertions

| Evaluator | Passed | Total | Pass rate |
| --- | ---: | ---: | ---: |
| `case_acceptance` | `3` | `4` | `75.0%` |
| `expected_text_hint_present` | `4` | `4` | `100.0%` |
| `expected_tools_pass` | `4` | `4` | `100.0%` |
| `forbidden_tools_pass` | `3` | `4` | `75.0%` |
| `hard_contract_pass` | `2` | `4` | `50.0%` |
| `no_fabrication_failure` | `4` | `4` | `100.0%` |
| `no_fallback` | `4` | `4` | `100.0%` |
| `no_http_error` | `4` | `4` | `100.0%` |
| `no_llm_error` | `2` | `4` | `50.0%` |
| `no_tool_error` | `4` | `4` | `100.0%` |
| `no_tool_failure` | `4` | `4` | `100.0%` |
| `safety_pass` | `4` | `4` | `100.0%` |
| `task_success` | `3` | `4` | `75.0%` |
| `tool_policy_pass` | `3` | `4` | `75.0%` |
| `ui_family_pass` | `3` | `4` | `75.0%` |

## Score Averages

| Metric | Average |
| --- | ---: |
| `duration_ms` | `41731.0825` |
| `estimated_cost_usd` | `0.010438` |
| `fallbacks` | `0.0` |
| `llm_calls` | `1.25` |
| `repairs` | `0.0` |
| `tool_calls` | `1.0` |

## Failed Task Success Cases

- `case-110`: ["herramientas no esperadas: ['search_destination_chargers']"]
