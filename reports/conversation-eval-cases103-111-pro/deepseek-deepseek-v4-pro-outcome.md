# Kalmio Conversation Eval Report

- Run: `deepseek-deepseek-v4-pro-outcome`
- Cases: `9`

## Assertions

| Evaluator | Passed | Total | Pass rate |
| --- | ---: | ---: | ---: |
| `case_acceptance` | `7` | `9` | `77.8%` |
| `expected_text_hint_present` | `8` | `9` | `88.9%` |
| `expected_tools_pass` | `8` | `9` | `88.9%` |
| `forbidden_tools_pass` | `8` | `9` | `88.9%` |
| `hard_contract_pass` | `6` | `9` | `66.7%` |
| `no_fabrication_failure` | `9` | `9` | `100.0%` |
| `no_fallback` | `9` | `9` | `100.0%` |
| `no_http_error` | `8` | `9` | `88.9%` |
| `no_llm_error` | `7` | `9` | `77.8%` |
| `no_tool_error` | `9` | `9` | `100.0%` |
| `no_tool_failure` | `9` | `9` | `100.0%` |
| `safety_pass` | `9` | `9` | `100.0%` |
| `task_success` | `7` | `9` | `77.8%` |
| `tool_policy_pass` | `7` | `9` | `77.8%` |
| `ui_family_pass` | `7` | `9` | `77.8%` |

## Score Averages

| Metric | Average |
| --- | ---: |
| `duration_ms` | `29075.533333` |
| `estimated_cost_usd` | `0.008031` |
| `fallbacks` | `0.0` |
| `llm_calls` | `1.0` |
| `repairs` | `0.0` |
| `tool_calls` | `0.777778` |

## Failed Task Success Cases

- `case-110`: ["herramientas no esperadas: ['search_destination_chargers']"]
- `case-111`: ['HTTP 502: {"detail": "No he podido completar esta respuesta con el agente de conversaci\\u00f3n. Reintenta en unos segundos.", "code": "agent_error", "developer_detail": "Revisa backend/.tmp/agent-traces.jsonl y la configuraci\\u00f3n del agente.", "disable_input": true}']
