---
target: todos los componentes del A2UI
total_score: 26
p0_count: 0
p1_count: 2
timestamp: 2026-06-15T17-30-04Z
slug: frontend-src-components-a2ui
---
# A2UI Components Critique

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | El chat muestra fases de envío, pero los bloques no exponen sistemáticamente fuente, frescura, confianza o falta de datos en vivo. |
| 2 | Match System / Real World | 3 | El español es prudente, pero algunas métricas quedan técnicas sin explicar por qué importan para conducir. |
| 3 | User Control and Freedom | 2 | Las acciones abren enlaces directamente y la vía manual de ubicación está parcialmente desconectada del chat. |
| 4 | Consistency and Standards | 3 | El vocabulario visual es consistente, pero la recomendación documentada como verde termina como bloque negro primario. |
| 5 | Error Prevention | 3 | Fallbacks y valores desconocidos son prudentes; falta limitar listas, acciones y chips para evitar sobrecarga. |
| 6 | Recognition Rather Than Recall | 2 | Las tarjetas muestran datos, pero no siempre explican el siguiente paso seguro ni la razón de la recomendación. |
| 7 | Flexibility and Efficiency | 2 | Hay chips y acciones, pero sin límites visuales ni una ruta manual robusta cuando falla geolocalización. |
| 8 | Aesthetic and Minimalist Design | 3 | Sobrio y escaneable; la repetición de plantillas métricas aplana la prioridad EV. |
| 9 | Error Recovery | 3 | Buen fallback por bloque; falta un cierre más accionable para que el usuario sepa cómo continuar. |
| 10 | Help and Documentation | 2 | Hay documentación y guía inicial, pero los bloques críticos no enseñan lo suficiente dentro del momento de decisión. |
| **Total** | | **26/40** | **Sólido, pero todavía no suficientemente directivo para ansiedad de carga.** |

## Anti-Patterns Verdict

**LLM assessment**: No parece AI slop decorativo obvio. La superficie evita gradientes gratuitos, vidrio, mega sombras y composición SaaS genérica. El problema es product slop: demasiados tipos A2UI con propósitos EV distintos se reducen a `MetricCard`, `ListCard` o botones sueltos. Eso produce familiaridad, pero no una jerarquía situacional clara para urgencia, ruta, destino y estancia.

**Deterministic scan**: `detect.mjs` se ejecutó contra `frontend/src/components/a2ui`, `frontend/src/App.tsx`, `A2UI_COMPONENTS.md` y `frontend/A2UI_VISUAL_LANGUAGE.md`. Exit code `0`, JSON `[]`, `0` findings. El detector no encontró patrones prohibidos.

**Visual overlays**: No hay overlay fiable. El preflight de live injection devolvió `config_missing` para `.impeccable/live/config.json`; no se inició live server ni se inyectó script. Además, no existe una ruta/story/fixture que renderice todos los componentes A2UI juntos para revisión visual.

## Overall Impression

El sistema está bien orientado como primera vertical slice: seguro, sobrio, móvil y conservador. La mayor oportunidad es convertir el catálogo desde “tarjetas de datos” hacia “decisiones EV guiadas”: una recomendación debe explicar prioridad, riesgo, evidencia y próximo paso de forma inmediata.

## What's Working

- El contrato de seguridad es fuerte: catálogo allowlisted, fallback de componente desconocido, error boundary por bloque y normalización de props.
- El tono base encaja con Kalmio: “No calculado”, “No disponible” y “Datos a confirmar” son honestos y conservadores.
- La base visual es limpia y móvil-first: Geist, escala compacta, radio moderado, acentos semánticos y sin decoración excesiva.

## Priority Issues

**[P1] La jerarquía EV se aplana en tarjetas métricas genéricas**

**Why it matters**: Una carga urgente, una ruta larga, una carga en destino y una estancia tienen cargas emocionales y decisiones distintas. Hoy varios tipos usan la misma plantilla, así que el usuario ve datos pero no una guía clara.

**Fix**: Diseñar layouts propios para `UrgentChargeCard`, `DestinationChargingCard` y `StayPlanningCard` con encabezado de decisión, riesgo/reserva, recomendación, acción primaria y nota de incertidumbre. Dejar `MetricCard` para resúmenes secundarios.

**Suggested command**: `$impeccable shape frontend/src/components/a2ui`

**[P1] La recomendación principal contradice el lenguaje visual documentado**

**Why it matters**: `frontend/A2UI_VISUAL_LANGUAGE.md` define recomendación como acento verde calmado, pero `RecommendedStopCard` usa fondo negro primario. Eso se lee más como CTA premium que como parada segura y conservadora.

**Fix**: Crear un rol visual `recommendation` real: superficie clara, borde/acento sobrio, confianza visible, y negro reservado para la acción primaria. Si el verde no es deseado, actualizar la doc y los tokens para eliminar esa contradicción.

**Suggested command**: `$impeccable colorize frontend/src/components/a2ui`

**[P2] Acciones, chips y alternativas pueden sobrecargar la decisión**

**Why it matters**: En EV, más opciones no siempre ayudan. Con batería baja, más de 3-4 opciones visibles puede devolver al usuario al modo “mapa de cargadores” y aumentar indecisión.

**Fix**: Limitar alternativas visibles a 3, colapsar el resto bajo “Ver más”, limitar acciones a primaria/secundaria, agrupar chips por propósito y no renderizar arrays arbitrarios sin jerarquía.

**Suggested command**: `$impeccable distill frontend/src/components/a2ui`

**[P2] La ubicación manual está prometida pero no completamente integrada**

**Why it matters**: Si el navegador bloquea geolocalización, el usuario necesita una salida clara. `LocationRequestCard` tiene `onManualLocationRequest`, pero la integración del chat solo pasa `onChipClick`.

**Fix**: Pasar `onLocationSubmit` y `onManualLocationRequest` desde `App.tsx`; al elegir manual, enfocar el composer y prellenar una instrucción corta como “Estoy en…”.

**Suggested command**: `$impeccable harden frontend/src/App.tsx`

**[P3] El mapa placeholder puede parecer factual**

**Why it matters**: El producto no debe inventar rutas, estaciones ni coordenadas. La línea sintética y los puntos pueden interpretarse como mapa real.

**Fix**: Etiquetar claramente “Vista esquemática” o “Previsualización no cartográfica”; mostrar fuente/estado si hay datos reales, y si no, convertirlo en resumen visual no cartográfico.

**Suggested command**: `$impeccable clarify frontend/src/components/a2ui`

## Persona Red Flags

**Conductor con 14% de batería en una ciudad desconocida**: `UrgentChargeCard` no prioriza “haz esto ahora” ni muestra riesgo/reserva con suficiente prominencia. Si geolocalización falla, la alternativa manual existe pero no enfoca ni guía el siguiente mensaje desde `App.tsx`. Varias alternativas o acciones podrían aumentar indecisión.

**Familia planificando Madrid-Valencia con pausa cómoda**: `RecommendedStopCard` no diferencia comodidad, servicios, tiempo de parada o riesgo práctico. `AlternativeStopsList` presenta filas homogéneas sin tradeoffs como “más segura”, “menos desvío” o “mejor para comer”. `StayPlanningCard` usa `Utensils`, pero solo muestra noches, ciudad y plan.

**Viajero prudente que no confía en datos no autorizados**: Las tarjetas no exponen sistemáticamente fuente, antigüedad o “sin datos en vivo”. `CostComparisonCard` puede parecer demasiado preciso si recibe importes. El mapa esquemático puede erosionar confianza si parece cartografía real.

## Minor Observations

- `MetricGridRows` usa tres columnas fijas y `truncate` en valores críticos; puede ocultar nombres, coordenadas o razones.
- `ActionButtons` decide la acción primaria por índice, no por semántica explícita.
- `RiskBand` interpreta severidad desde texto libre, lo que funciona visualmente pero deja frágil el contrato.
- `ErrorFallbackCard` oculta detalles técnicos de forma correcta, pero debería cerrar con “Puedes seguir escribiendo” o una instrucción equivalente.
- `PreferenceChips` no tiene contenedor ni título; puede aparecer como botones sueltos sin propósito.
- La cobertura automática del renderizador no instancia directamente todos los tipos del catálogo, aunque `A2UI_COMPONENTS.md` exige cobertura por componente.

## Questions to Consider

- ¿Qué bloque debería hacer que una persona con 12% de batería respire y actúe en menos de 5 segundos?
- ¿La recomendación principal debe parecer una tarjeta premium negra, o una decisión segura con evidencia?
- ¿Qué datos merecen estar siempre visibles: distancia, desvío, reserva, fuente, incertidumbre o acción?
- ¿Cuántas alternativas son realmente útiles antes de que Kalmio deje de ser copiloto y vuelva a ser mapa de cargadores?
