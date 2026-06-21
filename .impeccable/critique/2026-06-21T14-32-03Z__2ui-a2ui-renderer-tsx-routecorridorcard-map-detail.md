---
target: detalle del mapa
total_score: 26
p0_count: 0
p1_count: 2
timestamp: 2026-06-21T14-32-03Z
slug: 2ui-a2ui-renderer-tsx-routecorridorcard-map-detail
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | `Mapa orientativo`, estaciones y valores no calculados son visibles, pero el estado de interaccion de pins no queda claro. |
| 2 | Match System / Real World | 3 | Buen lenguaje de conductor: ruta, bateria, estaciones, duracion. "Estaciones cerca de la ruta" no explica si son paradas recomendables o solo puntos trazados. |
| 3 | User Control and Freedom | 2 | El fullscreen tiene `Volver`, pero los markers solapados bloquean clicks/taps y rompen la inspeccion. |
| 4 | Consistency and Standards | 3 | Usa patrones conocidos, shadcn/lucide y tokens coherentes. El mapa introduce labels truncadas y popovers que se comportan distinto al resto del A2UI. |
| 5 | Error Prevention | 2 | Advierte que bateria/energia no estan calculadas, pero el mapa aun puede parecer una ruta inspeccionable completa. No evita confiar en pins ilegibles o no tocables. |
| 6 | Recognition Rather Than Recall | 3 | El resumen de metricas ayuda a no recordar datos del chat. Falta una leyenda clara de marker principal vs alternativas. |
| 7 | Flexibility and Efficiency | 2 | El usuario solo puede ampliar y pinchar; no hay lista/selector dentro del detalle para saltar a una estacion cuando los pins se pisan. |
| 8 | Aesthetic and Minimalist Design | 3 | Visualmente calmado y premium. En desktop el mapa se vuelve demasiado ancho para una ruta concentrada y en movil el resumen consume mucho alto antes del mapa. |
| 9 | Error Recovery | 3 | Tiene fallback estatico y muestra "Vista estatica" si MapLibre falla. No ofrece camino alternativo si el pin no se puede tocar. |
| 10 | Help and Documentation | 2 | Hay cautela de datos en el escenario, pero el detalle de mapa no explica como interpretar pins, precision, o que hacer despues. |
| **Total** | | **26/40** | **Solido visualmente, con riesgo serio en interaccion y toma de decision** |

## Anti-Patterns Verdict

**LLM assessment**: No parece una UI generada por IA de forma obvia. La direccion Agentic Signal se respeta: superficie clara, poco ornamento, buen uso de route/primary/muted y copy honesta sobre datos no calculados. El problema no es estetico; es que la pantalla se comporta como un mapa de inspeccion cuando Kalmio dice que no debe obligar al conductor a interpretar pins manualmente. La decision principal queda fuera del fullscreen y los pins no son fiables como control.

**Deterministic scan**: El CLI sobre `frontend/src/components/a2ui/a2ui-renderer.tsx` devolvio `[]`. La inyeccion en navegador si marco problemas visibles: `text-overflow` en labels de marker (3), `clipped-overflow-container` (3), `cramped-padding` en mapa/control (2), `tiny-text` (1), `nested-cards` (7), `layout-transition` (1), y varias lineas largas. Falsos positivos probables: `overused-font` no aplica en producto porque Geist unico es una decision correcta; varios `nested-cards` pertenecen al showcase y no necesariamente al renderer final.

**Visual overlays**: La inyeccion cargo `detect.js` y dejo overlays visibles en la sesion. La overlay misma intercepto clicks despues, asi que la retire para continuar la inspeccion. Consola confirmo overflow de labels de markers y contenedores recortados.

## Overall Impression

El detalle de mapa es visualmente sobrio y coherente, pero todavia se siente como una ampliacion de cartografia, no como una herramienta de decision para un conductor. La mayor oportunidad es convertir el fullscreen en "corredor + lista seleccionable + accion trazable", dejando el mapa como apoyo visual y no como control principal.

## What's Working

1. La cautela de datos esta bien integrada: `Mapa orientativo`, `Bateria al llegar: No calculado` y `Energia: No calculado` evitan precision falsa.
2. La jerarquia compacta del card funciona en movil: el conductor ve ruta, estaciones, distancia/duracion y puede ampliar sin perder contexto.
3. Los tokens visuales estan alineados con Agentic Signal: calmado, legible, sin decoracion de IA ni gradientes gratuitos.

## Priority Issues

**[P1] Los pins solapados bloquean la interaccion**

Why it matters: En desktop y movil, intentar abrir `Punto de muestra La Plana` fallo porque la label de `Punto de muestra Teruel norte` intercepta el puntero. Para un mapa de carga, un pin no tocable destruye confianza y obliga al conductor a probar varias veces.

Fix: Hacer las labels no interactivas (`pointer-events: none`) o separar hitbox y label con z-index/control de colision. Mejor aun: en fullscreen, seleccionar estaciones desde una lista inferior/lateral sincronizada con el mapa, y que los pins sean secundarios.

Suggested command: `$impeccable harden detalle del mapa`

**[P1] El fullscreen no completa la decision**

Why it matters: Al abrir "Detalle de ruta", el usuario ve metricas y mapa, pero no ve de inmediato la parada principal, por que conviene, ni una accion primaria como "Usar esta parada" o "Abrir en Maps". La decision queda repartida entre el card anterior, la lista de alternativas y el bloque de coste.

Fix: Reestructurar el detalle en tres zonas: resumen superior compacto, mapa, y una bandeja de estaciones con parada principal primero, alternativas despues, cautelas y accion. En desktop, lista lateral; en movil, bottom sheet colapsable.

Suggested command: `$impeccable shape detalle del mapa`

**[P2] El mapa compacto no prioriza la informacion que reduce ansiedad**

Why it matters: El bloque dice "Bateria de llegada no validada", pero esa cautela aparece debajo del mapa, despues de un lienzo que visualmente domina. En un contexto de bateria baja o plan incierto, el conductor necesita primero riesgo/margen/confianza, luego inspeccion.

Fix: En el card compacto, mover el estado critico arriba o superponer una banda breve sobre el mapa: "Llegada no validada" / "3 estaciones trazadas" / "Mapa orientativo". Mantener el mapa como preview, no como protagonista.

Suggested command: `$impeccable layout detalle del mapa`

**[P2] La densidad del resumen fullscreen es alta en movil**

Why it matters: En 390x844, el header mas resumen consumen 305px antes de que empiece el mapa. Eso reduce el area util de inspeccion y hace que el usuario vea mucho dato antes de poder orientarse.

Fix: Compactar el resumen movil a una fila de chips o dos metricas prioritarias, con "Ver datos de ruta" expandible. Priorizar `Mapa orientativo`, estaciones y bateria; mover distancia/duracion/energia a detalle secundario.

Suggested command: `$impeccable adapt detalle del mapa`

**[P2] La codificacion visual de markers no explica roles**

Why it matters: Los markers 1/2/3, origen/destino y colores no comunican con suficiente claridad cual es parada principal, alternativa, origen o destino. En el mapa ampliado hay labels truncadas a 80px, asi que el usuario depende de memoria o ensayo.

Fix: Agregar una leyenda minima o, mejor, una lista sincronizada donde cada item repita numero, rol, nombre y metrica clave. Mantener labels del mapa solo para origen/destino y estacion seleccionada.

Suggested command: `$impeccable clarify detalle del mapa`

## Persona Red Flags

**Marta, conductora con bateria baja**: Abre el detalle esperando una decision clara. Ve un mapa grande con pins, pero no una accion inmediata ni la parada recomendada en el fullscreen. Si toca el pin principal y no abre, pierde confianza justo en el momento de mas estres.

**Diego, planificador familiar**: Quiere comparar parada comoda, servicios y desvio. En el detalle de mapa no tiene lista de estaciones ni servicios visibles; debe volver al card/lista anterior. El mapa ampliado no mejora la comparacion.

**Alex, usuario experto**: Espera que el mapa permita inspeccion rapida. Los markers tienen labels truncadas, colisionan y no hay selector por teclado visible dentro del mapa. La experiencia rompe el modelo mental de mapa interactivo.

## Minor Observations

- El boton de ampliar solo muestra icono; tiene `aria-label`, pero visualmente no comunica si abre mapa, detalle de ruta o inspeccion de estaciones.
- `Mapa orientativo` funciona, pero podria estar unido a una explicacion corta de precision cuando `geometryPrecision` no es provider.
- El copy "estaciones cerca de la ruta" es honesto, pero no distingue "viables", "trazadas" y "recomendadas".
- En desktop, el mapa ocupa 1280px de ancho aunque la geometria/pins quedan concentrados; una columna lateral daria mejor uso al espacio.
- Los warnings WebGL `ReadPixels` aparecieron en consola; no son un hallazgo UX directo, pero conviene vigilar performance si el mapa se abre con frecuencia.

## Questions to Consider

- Que deberia poder decidir el conductor sin tocar ningun pin?
- El fullscreen existe para inspeccionar una ruta o para confirmar una parada?
- Cual es el minimo resumen que reduce ansiedad antes de mostrar el mapa?
- Si MapLibre falla o los pins se solapan, que alternativa visual sigue permitiendo elegir una estacion?
