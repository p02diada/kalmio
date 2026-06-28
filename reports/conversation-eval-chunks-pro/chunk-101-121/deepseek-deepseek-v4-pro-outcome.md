# Kalmio Conversation Eval Report

- Run: `deepseek-deepseek-v4-pro-outcome`
- Cases: `21`

## Assertions

| Evaluator | Passed | Total | Pass rate |
| --- | ---: | ---: | ---: |
| `case_acceptance` | `17` | `21` | `81.0%` |
| `expected_text_hint_present` | `18` | `21` | `85.7%` |
| `expected_tools_pass` | `20` | `21` | `95.2%` |
| `forbidden_tools_pass` | `20` | `21` | `95.2%` |
| `hard_contract_pass` | `12` | `21` | `57.1%` |
| `no_fabrication_failure` | `21` | `21` | `100.0%` |
| `no_fallback` | `21` | `21` | `100.0%` |
| `no_http_error` | `20` | `21` | `95.2%` |
| `no_llm_error` | `13` | `21` | `61.9%` |
| `no_tool_error` | `21` | `21` | `100.0%` |
| `no_tool_failure` | `21` | `21` | `100.0%` |
| `safety_pass` | `21` | `21` | `100.0%` |
| `task_success` | `19` | `21` | `90.5%` |
| `tool_policy_pass` | `19` | `21` | `90.5%` |
| `ui_family_pass` | `19` | `21` | `90.5%` |

## Score Averages

| Metric | Average |
| --- | ---: |
| `duration_ms` | `30484.306667` |
| `estimated_cost_usd` | `0.0079` |
| `fallbacks` | `0.0` |
| `llm_calls` | `1.0` |
| `repairs` | `0.0` |
| `tool_calls` | `0.809524` |

## Failed Task Success Cases

- `case-107`: ['HTTP 502: {"detail": "No he podido completar esta respuesta con el agente de conversaci\\u00f3n. Reintenta en unos segundos.", "code": "agent_error", "developer_detail": "Revisa backend/.tmp/agent-traces.jsonl y la configuraci\\u00f3n del agente.", "disable_input": true}']
- `case-110`: ["herramientas no esperadas: ['search_destination_chargers']"]
