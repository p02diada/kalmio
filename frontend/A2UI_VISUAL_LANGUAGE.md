# A2UI Visual Language

## Purpose

A2UI blocks make assistant responses scannable and actionable. They are not decorative cards. Each block must clarify a decision, risk, alternative, or next action.

## Block Hierarchy

1. Primary recommendation.
2. Safety and reserve status.
3. Route or charging summary.
4. Alternatives.
5. Actions.
6. Supporting explanation.

## Visual Roles

- Recommendation: calm green accent, high confidence when justified.
- Risk: amber accent, concise explanation.
- Route: blue accent, distance and duration emphasis.
- Assistant question: violet accent, compact form or chips.
- Error fallback: neutral surface, technical type visible.

## Layout

- One block per row on mobile.
- Avoid nested cards.
- Keep action rows sticky only when the block is a primary decision.
- Use compact labels and clear numeric emphasis.

## Copy Rules

- Use short Spanish copy.
- Avoid overpromising. Prefer "estimado", "sin datos en vivo", "fuente no disponible", and "conviene confirmar".
- Actions should name the action: "Abrir en Maps", "Guardar plan", "Ajustar reserva".

## Fallback

Unknown or invalid blocks render `ErrorFallbackCard` with the original type, a short explanation, and no destructive actions.
