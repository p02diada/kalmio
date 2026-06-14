# Codex AI Test Path

Kalmio keeps deterministic local planning as the default path. For AI experiments, run Codex as a project-scoped assistant with the smallest current GPT-5.5-class model documented for low-cost, simple workloads.

## Project Defaults

The repo includes `.codex/config.toml`:

```toml
model = "gpt-5.5"
```

OpenAI's current model documentation lists GPT-5.5 as the default target for low-cost, simple high-volume tasks. Codex documentation also supports setting the local CLI/IDE model through `.codex/config.toml`.

## How To Test

From the project root:

```bash
codex
```

For one-off checks:

```bash
codex exec "Revisa el flujo de chat de Kalmio y sugiere una respuesta conservadora para una ruta Cordoba-Valencia con 58%."
```

Keep this path behind development/testing only until the product has a bounded contract for AI output, validation, observability, cost controls, and failure handling. The app should never invent charger availability, prices, coordinates, or vehicle state.
