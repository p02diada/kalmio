---
target: frontend/src/components/a2ui/a2ui-showcase.tsx
total_score: 27
p0_count: 0
p1_count: 2
timestamp: 2026-06-19T21-33-40Z
slug: frontend-src-components-a2ui-a2ui-showcase-tsx
---
# Revision UX de componentes A2UI

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Los estados de ubicacion y fallback se comunican, pero las acciones demo solo aparecen como una linea pequeña en el header sticky. |
| 2 | Match System / Real World | 3 | El tono es prudente y EV-first, pero aparece jerga como "EVSEs trazados" y nombres tecnicos de componentes en la revision. |
| 3 | User Control and Freedom | 3 | Hay acciones deshabilitadas y fallback, pero "Escribir ubicacion" no abre un campo ni deja claro el siguiente paso dentro del bloque. |
| 4 | Consistency and Standards | 3 | Cards, botones e iconos son consistentes; la galeria introduce card-dentro-de-card y rompe la lectura real del chat. |
| 5 | Error Prevention | 3 | El fallback y el aviso de datos demo previenen malinterpretaciones, pero el mapa esquematico no lo declara en el propio componente. |
| 6 | Recognition Rather Than Recall | 3 | Las piezas principales se entienden sin memoria previa; los labels tecnicos del showcase obligan a traducir catalogo a uso. |
| 7 | Flexibility and Efficiency | 2 | La galeria es una lista lineal de 19 bloques sin filtros, escenarios ni salto rapido. |
| 8 | Aesthetic and Minimalist Design | 2 | La composicion es limpia, pero hay exceso de bordes y wrappers; varios datos se comprimen demasiado en movil. |
| 9 | Error Recovery | 3 | ErrorFallbackCard es claro y LocationRequest maneja fallo de permisos, aunque la recuperacion manual queda fuera del bloque. |
| 10 | Help and Documentation | 2 | Hay un aviso de demo, pero no hay contexto por escenario, estado esperado ni variantes utiles para revisar componentes. |
| **Total** | | **27/40** | **Solido, con deuda clara de adaptacion movil y revision-context.** |

## Anti-Patterns Verdict

No parece un "AI UI" obvio en los componentes de chat: usa una paleta restringida, iconografia consistente, radios razonables y microcopy conservadora. El riesgo no es decoracion generica; es que el showcase se lee como arnes tecnico, no como experiencia Kalmio. La lista de 19 cards con nombre de componente, contador y otro card dentro hace que el reviewer juzgue el contenedor de QA tanto como el componente real.

Deterministic scan: `detect.mjs --json frontend/src/components/a2ui/a2ui-showcase.tsx frontend/src/components/a2ui/a2ui-renderer.tsx` devolvio `[]`. No encontro gradient text, side-stripes, sobre-redondeo, sombras fantasma ni otros patrones prohibidos.

Visual evidence: se revisaron capturas headless Chrome en 390px movil y 1280px desktop. No hubo overlay visible porque esta sesion no expone una API de navegador mutable para inyectar el detector en una pestana humana; la evidencia usada fue screenshot local.

## Overall Impression

La base es fiable y apropiada para Kalmio: sobria, legible y honesta sobre incertidumbre. El mayor salto de calidad esta en dejar de tratar todos los datos como una cuadricula compacta. En movil, los componentes mas importantes para conducir deberian priorizar lectura y decision, no simetria.

## What's Working

- El tono general es calmado y conservador. RiskExplanationCard, ErrorFallbackCard y el banner de datos demo evitan promesas falsas.
- RecommendedStopCard funciona como pico visual: la tarjeta oscura da prioridad clara a la parada principal sin llenar la interfaz de color.
- El renderer ya resiste bloques desconocidos y estados de ubicacion, lo cual es importante para A2UI dinamico.

## Priority Issues

### [P1] Las metric grids comprimen decisiones criticas en movil

Why it matters: En TripSummaryCard, UrgentChargeCard y StayPlanningCard, la cuadricula de 3 columnas obliga a partir palabras y frases. En la captura movil se ve "Conservadora" roto, "Demo Charge Urgente" apilado palabra a palabra y recomendaciones largas convertidas en columnas ilegibles. Para un conductor con bateria baja, esos datos tienen que escanearse en un segundo.

Fix: Cambiar `MetricGridRows` de `grid-cols-3` fijo a una estrategia responsive: 2 columnas en movil, auto-fit con minmax real, o filas label/value para valores largos. Permitir que valores como parada, plan o confirmacion ocupen todo el ancho. Mantener 3 columnas solo en desktop o cuando los valores sean cortos.

Suggested command: `$impeccable adapt frontend/src/components/a2ui/a2ui-renderer.tsx`

### [P1] La galeria evalua wrappers, no solo componentes

Why it matters: El showcase envuelve cada bloque en un Card y muchos bloques ya son Card. Eso crea card-dentro-de-card, exceso de bordes y padding, y una impresion mas pesada que el chat real. En desktop parece una documentacion tecnica; en movil alarga mucho el scroll.

Fix: Separar el modo QA del modo experiencia. Para revision visual, renderizar grupos de componentes en un rail de chat real o en secciones sin card exterior. Mantener metadatos del catalogo como una etiqueta ligera, no como marco principal.

Suggested command: `$impeccable layout frontend/src/components/a2ui/a2ui-showcase.tsx`

### [P2] Los nombres tecnicos dominan la revision

Why it matters: `AssistantMessage`, `TripSummaryCard`, `A2UI local renderer` y `1/19` son utiles para dev, pero no para revisar si la UI tranquiliza a un conductor. Empujan al reviewer a pensar en catalogo, no en escenarios: carga urgente, ruta, destino, riesgo.

Fix: Agrupar por escenarios visibles: "Conversacion", "Ruta", "Parada recomendada", "Riesgo", "Ubicacion", "Acciones". Añadir un toggle de "mostrar IDs" para QA. Por defecto, revisar como experiencia.

Suggested command: `$impeccable clarify frontend/src/components/a2ui/a2ui-showcase.tsx`

### [P2] El mapa esquematico puede parecer mas factual de lo que es

Why it matters: MapPreviewCard pinta una ruta y puntos, pero el propio componente no muestra que es esquema/no navegacion; solo la galeria advierte de datos demo arriba. En un producto que no debe inventar coordenadas ni ruta, el bloque necesita su propia trazabilidad visual.

Fix: Mostrar dentro del componente una etiqueta como "Esquema, no navegacion" o "Vista orientativa", y hacer visible `source` cuando exista. Si faltan coordenadas o proveedor, reducir el mapa a diagrama de pasos en vez de linea tipo mapa.

Suggested command: `$impeccable harden frontend/src/components/a2ui/a2ui-renderer.tsx`

### [P2] La recuperacion manual de ubicacion no cierra el loop

Why it matters: LocationRequestCard ofrece "Escribir ubicacion", pero en el bloque aislado solo cambia un texto auxiliar. En el chat puede funcionar si enfoca el composer, pero visualmente el usuario no ve campo, foco ni accion enviada.

Fix: Al pulsar manual, enfocar el composer y mostrar microcopy de handoff claro, o renderizar un mini input local si el contrato A2UI lo permite. Si no lo permite, emitir evento y mostrar "Escribe tu ciudad en el mensaje de abajo".

Suggested command: `$impeccable harden frontend/src/components/a2ui/a2ui-renderer.tsx`

## Persona Red Flags

**Conductor con bateria baja**: La tarjeta urgente muestra bateria, parada y distancia, pero el nombre del cargador se parte en varias lineas y compite con datos menos urgentes. No queda bastante clara la accion siguiente dentro de la propia tarjeta.

**Familia planificando ruta en movil**: Los servicios estan bien priorizados, pero el listado de alternativas mezcla estacion, potencia, desvio, EVSEs y servicios en una sola linea densa. Cuesta comparar comodidad rapidamente.

**Product reviewer en telefono**: La ruta `/a2ui` obliga a recorrer 19 bloques en una sola columna con etiquetas tecnicas. Es dificil juzgar el flujo emocional completo porque los componentes aparecen atomizados y enmarcados.

## Minor Observations

- La demo usa texto sin acentos en varios sitios (`critico`, `pedire`, `ubicacion`). Aunque sea demo, para un producto en espanol conviene revisar con copy final.
- `EVSEs trazados` es preciso para equipo tecnico, pero probablemente no para conductores. "Conectores registrados" o "puntos registrados" seria mas humano.
- Los textos secundarios en `text-xs` funcionan en desktop, pero en movil largo empiezan a parecer notas legales.
- El badge con solo `19` en el header no dice "componentes"; es compacto pero demasiado abstracto.

## Questions to Consider

- Queremos que `/a2ui` sea una galeria tecnica de catalogo o una mesa de revision de experiencia?
- Que dato debe ganar siempre en una tarjeta EV: margen de bateria, siguiente accion, distancia o confianza?
- Los componentes deberian tener variantes explicitas de "dato fiable", "dato estimado" y "dato no disponible" en la galeria?
