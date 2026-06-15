# Codex AI Test Path

Kalmio keeps deterministic local planning as the default path. For AI experiments, run Codex as a project-scoped assistant with the smallest model that can reliably handle the current EV conversation task. The current project default is `gpt-5.4-mini`.

## Project Defaults

The repo includes `.codex/config.toml`:

```toml
model = "gpt-5.4-mini"
```

Codex also supports setting the local CLI/IDE model through `.codex/config.toml`.

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
