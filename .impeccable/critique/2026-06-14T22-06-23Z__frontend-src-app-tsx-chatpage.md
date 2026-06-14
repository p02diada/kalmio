---
target: pagina de chat A2UI con 10 conversaciones reales en modo codex
total_score: 20
p0_count: 0
p1_count: 3
timestamp: 2026-06-14T22-06-23Z
slug: frontend-src-app-tsx-chatpage
---
**Design Health Score**

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 1 | Rutas largas quedan en espera y terminan como error técnico sin progreso útil. |
| 2 | Match System / Real World | 2 | La cabecera habla del backend/A2UI y algunos errores dicen "Codex local". |
| 3 | User Control and Freedom | 2 | Hay reinicio y entrada manual, pero no cancelar/reintentar una operación lenta. |
| 4 | Consistency and Standards | 2 | El catálogo renderiza estable, pero urgencia aparece como destino y hay tarjetas anidadas. |
| 5 | Error Prevention | 2 | Pregunta datos críticos, pero deja pasar rutas con energía/llegada 0 y props sin normalizar. |
| 6 | Recognition Rather Than Recall | 3 | Chips iniciales y etiquetas ayudan; las preguntas de aclaración no muestran campos útiles en algunos casos. |
| 7 | Flexibility and Efficiency | 2 | Chips aceleran, pero el chat no auto-enfoca el resultado ni ofrece acciones de corrección. |
| 8 | Aesthetic and Minimalist Design | 2 | Calmado, pero con demasiadas tarjetas de igual peso y composer que interrumpe el contenido. |
| 9 | Error Recovery | 1 | Los fallos de Codex/JSON no se traducen a recuperación accionable. |
| 10 | Help and Documentation | 3 | El sistema explica que pedirá datos y muestra riesgos, pero la microcopy sigue siendo técnica. |
| **Total** | | **20/40** | **Funcional, pero necesita robustez y jerarquía antes de sentirse confiable.** |

**Anti-Patterns Verdict**

**LLM assessment**: No parece una landing genérica de IA; sí parece una primera UI interna de producto. La estructura básica es sobria, pero la experiencia todavía expone el andamiaje técnico: "backend", "A2UI", "Codex local", props crudas y estados de fallo sin traducción al lenguaje del conductor.

**Deterministic scan**: `detect.mjs --json frontend/src/App.tsx frontend/src/components/a2ui/a2ui-renderer.tsx` devolvió `[]`.

**Visual overlay**: La inyección en Chrome headless funcionó y reportó 4 hallazgos: 2 `cramped-padding` en botones/chips, 1 `nested-cards` en listas internas, y 1 `layout-transition` por transición de `width` en `body`. No hay overlay visible para el usuario porque la inspección fue headless; sí hay evidencia de consola.

**Overall Impression**

El chat ya demuestra el principio correcto: el backend decide, el frontend renderiza bloques permitidos y los riesgos aparecen explícitamente. Pero la experiencia no aguanta todavía una situación de ansiedad de carga: cuando una ruta tarda o falla, la interfaz habla como infraestructura; cuando sí responde, el resultado queda enterrado entre chips, burbujas y composer sticky.

**What's Working**

- El `LocationRequestCard` es el mejor bloque: pide ubicación sin inventar, ofrece alternativa manual y usa una jerarquía clara.
- Las búsquedas de destino devuelven alternativas reales con riesgo explícito; esto respeta el contrato de no inventar disponibilidad/precios.
- El sistema de fallback por bloque es sólido como arquitectura: un componente roto no tumba la conversación completa.

**Priority Issues**

**[P1] Estado y recuperación de operaciones largas**
Why it matters: 3 de 10 conversaciones quedaron en timeout o error visible: Madrid-Valencia, Barcelona-Valencia y coste Madrid-Valencia. En una app contra ansiedad de carga, una espera muda o "Codex local no devolvió JSON válido" destruye confianza.
Fix: Mostrar estados intermedios por fases: interpretando solicitud, consultando ruta, buscando cargadores, validando riesgo. Si Codex falla, convertirlo en A2UI seguro: "No he podido completar el cálculo; puedo intentarlo con menos datos o pedirte origen/destino exactos".
Suggested command: `$impeccable harden chat failures and long-running route states`

**[P1] El composer sticky tapa la lectura del resultado**
Why it matters: En móvil, al inicio del scroll el composer aparece antes de las tarjetas de respuesta o deja el resultado por debajo del fold. El usuario puede creer que solo se envió el mensaje y no ver la recomendación.
Fix: Convertir el chat en un layout con área scrollable dedicada y composer fijo fuera del flujo, auto-scroll al último bloque nuevo, `scroll-padding-bottom` real y anclaje al resultado tras enviar.
Suggested command: `$impeccable layout chat conversation viewport`

**[P1] Contrato semántico A2UI inconsistente con la intención**
Why it matters: "Necesito cargar ya" en Córdoba renderizó `DestinationChargingCard`, una ruta devolvió energía `0 kWh` y llegada `0%`, y Alcobendas mostró `{'label': ...}` como destino. Son fallos de confianza, no solo de estética.
Fix: Endurecer normalización/validación de props antes del render: urgencia debe renderizar `UrgentChargeCard` o `LocationRequestCard`; valores 0 desconocidos deben mostrarse como "No calculado"; objetos nunca deben llegar como texto visible.
Suggested command: `$impeccable harden A2UI semantic validation and renderer guards`

**[P2] Jerarquía visual demasiado plana**
Why it matters: Recomendación, alternativas y riesgo compiten como tarjetas equivalentes. La decisión primaria no emerge con suficiente claridad, y las listas usan tarjetas dentro de tarjetas.
Fix: Hacer que el bloque principal sea un panel de decisión compacto, alternativas como lista sin card anidada, riesgo como banda integrada bajo la decisión. Mantener una sola tarjeta por bloque real.
Suggested command: `$impeccable distill A2UI recommendation hierarchy`

**[P2] Microcopy todavía habla al equipo, no al conductor**
Why it matters: "El backend decide...", "A2UI pintar" y "Codex local" rompen el tono de copiloto calmado. En móvil se leen antes que la ayuda real.
Fix: Sustituir cabecera por una promesa operacional: "Dime ruta, batería o destino. Si falta algo, te lo pediré antes de recomendar." Traducir errores a acciones del viaje.
Suggested command: `$impeccable clarify chat copy and error language`

**Persona Red Flags**

**Conductor con batería baja**: En el caso urgente con Córdoba, la UI muestra "Carga en destino" en vez de "Carga urgente". El riesgo existe, pero no hay prioridad emocional ni acción inmediata.

**Familia planificando ruta**: La pregunta ambigua responde "Falta un dato" pero no lista los campos visualmente; deja al usuario adivinando qué escribir a continuación.

**Usuario técnico recurrente**: Puede entender chips y reset, pero no tiene forma de inspeccionar/reintentar una operación fallida sin reiniciar o reescribir todo.

**Minor Observations**

- Varias estaciones largas se truncaron: "Parking San Agustín...", "Club de Padel...".
- El placeholder del composer es correcto, pero ocupa demasiado espacio visual cuando ya hay respuesta.
- Los chips iniciales quedan permanentes en cada conversación y empujan el resultado hacia abajo.
- El botón de reset no tiene confirmación ni estado de carga.

**Questions to Consider**

- ¿Debe el chat mostrar siempre los chips iniciales después del primer mensaje, o deberían colapsarse?
- ¿Qué dato debe ser imposible mostrar como `0`: energía, llegada, precio, disponibilidad?
- ¿La respuesta principal debería terminar en una acción concreta cuando hay recomendación, aunque sea "Abrir en Maps" deshabilitada con razón?
