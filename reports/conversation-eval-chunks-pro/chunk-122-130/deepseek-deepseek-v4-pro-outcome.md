# Kalmio Conversation Eval Report

- Run: `deepseek-deepseek-v4-pro-outcome`
- Cases: `9`

## Assertions

| Evaluator | Passed | Total | Pass rate |
| --- | ---: | ---: | ---: |
| `case_acceptance` | `8` | `9` | `88.9%` |
| `expected_text_hint_present` | `9` | `9` | `100.0%` |
| `expected_tools_pass` | `9` | `9` | `100.0%` |
| `forbidden_tools_pass` | `8` | `9` | `88.9%` |
| `hard_contract_pass` | `8` | `9` | `88.9%` |
| `no_fabrication_failure` | `9` | `9` | `100.0%` |
| `no_fallback` | `9` | `9` | `100.0%` |
| `no_http_error` | `9` | `9` | `100.0%` |
| `no_llm_error` | `8` | `9` | `88.9%` |
| `no_tool_error` | `9` | `9` | `100.0%` |
| `no_tool_failure` | `9` | `9` | `100.0%` |
| `safety_pass` | `9` | `9` | `100.0%` |
| `task_success` | `8` | `9` | `88.9%` |
| `tool_policy_pass` | `8` | `9` | `88.9%` |
| `ui_family_pass` | `8` | `9` | `88.9%` |

## Score Averages

| Metric | Average |
| --- | ---: |
| `duration_ms` | `25469.478889` |
| `estimated_cost_usd` | `0.00948` |
| `fallbacks` | `0.0` |
| `llm_calls` | `1.111111` |
| `repairs` | `0.0` |
| `tool_calls` | `0.888889` |

## Failed Task Success Cases

- `case-123`: ["herramientas no esperadas: ['search_destination_chargers']"]
