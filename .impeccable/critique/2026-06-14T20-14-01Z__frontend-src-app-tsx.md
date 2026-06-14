---
target: home
total_score: 28
p0_count: 0
p1_count: 1
timestamp: 2026-06-14T20-14-01Z
slug: frontend-src-app-tsx
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | La home explica por copy que abrirá el chat, pero no muestra una transición clara ni qué estado viene después del envío. |
| 2 | Match System / Real World | 3 | "Ruta", "hotel" y "carga urgente" conectan con el mundo EV; "A2UI" es jerga interna para el conductor. |
| 3 | User Control and Freedom | 3 | Hay input libre y accesos rápidos; los prompts rápidos envían directo sin previsualización ni posibilidad de ajustar antes. |
| 4 | Consistency and Standards | 3 | Buen uso de shadcn/ui y navegación estándar; el H1 tiene escala de landing más que de herramienta productiva. |
| 5 | Error Prevention | 3 | El envío vacío está deshabilitado y el copy evita inventar datos; falta guiar mejor qué datos son críticos. |
| 6 | Recognition Rather Than Recall | 3 | Los tres inicios rápidos reducen recuerdo, pero podrían describir escenarios EV y datos necesarios con más precisión. |
| 7 | Flexibility and Efficiency | 3 | Sirve a usuarios que quieren escribir y a usuarios que prefieren elegir un modo; falta una vía estructurada de ruta completa. |
| 8 | Aesthetic and Minimalist Design | 3 | Limpia y calmada, sin decoración gratuita; también demasiado genérica y seca para la promesa emocional del producto. |
| 9 | Error Recovery | 2 | La home no anticipa fallos de proveedor, datos no fiables o ausencia de cargadores autorizados hasta después del chat. |
| 10 | Help and Documentation | 3 | El microcopy "preguntaré antes" ayuda; la alerta final mezcla confianza de producto con arquitectura interna. |
| **Total** | | **28/40** | **Sólida, pero todavía no suficientemente tranquilizadora ni propia.** |

## Anti-Patterns Verdict

**LLM assessment**: No parece una landing genérica de IA ni cae en los patrones prohibidos fuertes: no hay gradiente de texto, hero-metric template, glassmorphism decorativo, tarjetas anidadas ni exceso de sombras. El problema no es slop visual obvio; es que la home se siente demasiado heredada de una base Vercel/shadcn: blanco puro, Geist, contornos finos, H1 grande, tres botones outline y una alerta. Para una PWA que promete reducir ansiedad de carga, la pantalla es competente pero poco propia y poco tranquilizadora.

**Deterministic scan**: `detect.mjs --json frontend/src/App.tsx` devolvio `[]`. Cero hallazgos, cero reglas, cero severidades. El detector no encontro patrones automaticos de slop o anti-patterns en `frontend/src/App.tsx`.

**Visual overlays**: No hay overlay visible fiable. No estaba disponible una Browser skill mutable ni Playwright/Puppeteer/cliente WebSocket local para inyectar `detect.js`, leer consola `impeccable` y presentar una pestaña `[Human]`. Se uso fallback con Chrome headless y capturas en 390x844 y 1440x900.

## Overall Impression

La home funciona: es clara, sobria, tactil y respeta la regla "chat primero, mapa despues". Pero para el claim "Viaja sin ansiedad de carga", el primer viewport todavia pide confianza antes de ganarsela. El mayor salto de calidad seria convertir la confianza tecnica en confianza de usuario: "no inventamos disponibilidad, precios ni estaciones; si falta una fuente fiable, te lo diremos".

## What's Working

1. **La accion principal esta clara.** El input de `HomePage` en `frontend/src/App.tsx` ofrece una entrada libre y directa, con submit deshabilitado cuando no hay texto.

2. **La IA esta contenida.** El copy en `frontend/src/App.tsx` promete preguntar antes de recomendar, lo que encaja con las reglas del producto.

3. **El shell mobile-first es sobrio.** La navegacion inferior tiene buenos objetivos tactiles, y el ancho maximo movil mantiene foco en la tarea.

## Priority Issues

**[P1] Falta confianza practica antes de pedir input**

Por que importa: en EV, el usuario no solo quiere escribir; quiere saber que el sistema no va a inventar cargadores, disponibilidad, precios o rutas optimistas. La alerta actual aparece despues de los accesos rapidos en movil y usa "A2UI", que habla al equipo, no al conductor.

Fix: mover una garantia operacional cerca del input: "No asumimos disponibilidad ni precios; si falta una fuente fiable, te lo diremos." Reemplazar "A2UI" por lenguaje de usuario y hacer que el cierre emocional sea seguridad practica.

Suggested command: `$impeccable clarify`

**[P2] El H1 es demasiado grande para una herramienta mobile-first**

Por que importa: en la captura movil, `--text-hero: 3rem` y `max-w-hero-width: 11ch` hacen que el H1 domine gran parte del primer viewport. El input sigue visible, pero la prueba de confianza y los accesos rapidos quedan mas abajo de lo necesario.

Fix: bajar la escala hero en movil, por ejemplo a una jerarquia de producto mas compacta, y reservar la energia visual para el modo urgente o una garantia de datos fiable.

Suggested command: `$impeccable typeset`

**[P2] Los accesos rapidos no son suficientemente especificos para ansiedad EV**

Por que importa: "Preparar ruta" es util, pero mezcla muchos datos tecnicos en el prompt. "Hotel" y "Necesito cargar ya" no explican que preguntara Kalmio ni que datos faltan. Un usuario ansioso necesita previsibilidad.

Fix: renombrar con resultados concretos: "Planificar ruta larga", "Cargar cerca del destino", "Buscar opcion urgente". Anadir microcopy de datos esperados y priorizar visualmente el modo urgente.

Suggested command: `$impeccable clarify`

**[P2] La home tiene poca identidad Kalmio**

Por que importa: la pantalla podria pertenecer a muchas apps de productividad. Kalmio necesita senales propias de movilidad, cautela energetica, rutas espanolas y recomendaciones conservadoras sin convertirse en mapa ni dashboard.

Fix: introducir una capa visual contenida: una mini ficha de "plan conservador" con datos desconocidos explicitados, un resumen de estado EV sin valores inventados, o un patron de ruta textual que refuerce el producto.

Suggested command: `$impeccable bolder`

**[P3] La iconografia del primer acceso rapido es ambigua**

Por que importa: el icono de "Cargar cerca de un hotel" no se lee claramente como hotel/carga en la captura. En un area de decision rapida, cada icono debe reducir friccion.

Fix: usar un icono Lucide mas literal o una combinacion visual mas clara dentro del vocabulario existente.

Suggested command: `$impeccable polish`

## Persona Red Flags

**Conductor con 18% de bateria en carretera**: "Necesito cargar ya" existe, pero pesa igual que los otros prompts. No hay senal de urgencia ni explicacion inmediata de si debe dar ubicacion, bateria o conector.

**Familia planificando Cordoba-Valencia**: "Preparar ruta" incluye bateria util, consumo, CCS2 y potencia, pero la UI no distingue datos obligatorios de opcionales. Si no conocen consumo o potencia, pueden bloquearse antes de enviar.

**Usuario esceptico sobre datos de cargadores**: La alerta dice "componentes A2UI permitidos", pero su miedo real es otro: estacion inexistente, disponibilidad falsa, precio incorrecto o una ruta demasiado optimista.

## Minor Observations

- El claim en mono funciona como tono tecnico, pero podria sentirse menos humano que la promesa de calma.
- El placeholder "Ruta, hotel, carga urgente..." es eficiente, aunque algo generico.
- En desktop hay mucho espacio vacio a la derecha; no rompe la UI, pero desaprovecha una oportunidad de mostrar una senal de producto.
- El boton de submit solo con flecha es estandar en chat, pero el disabled gris puede parecer una accion ausente para usuarios menos expertos.
- La composicion shadcn es consistente en la home, aunque otras zonas del archivo usan `space-y-*` y estructura de `CardContent` mas laxa; conviene vigilarlo cuando se pula la pantalla completa.

## Questions to Consider

1. ¿La home debe abrir vendiendo "chat primero" o demostrando "no voy a inventar datos" antes de pedir la primera frase?
2. ¿Que veria un conductor ansioso si solo tuviera 10 segundos para decidir si confia?
3. ¿Kalmio deberia abrir con una pregunta libre, o con tres modos explicitos: ruta, urgencia, destino?
4. ¿Que rasgo visual propio de Kalmio puede existir sin convertirse en mapa, dashboard o decoracion generica?
