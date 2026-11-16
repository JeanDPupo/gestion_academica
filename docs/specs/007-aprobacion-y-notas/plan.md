# Plan 007 — Aprobación y notas

## Enfoque

Una Lambda `evaluacion`. Aprobar y calificar son escrituras de un solo ítem: basta un `UpdateItem` con condición, sin transacción.

## Archivos

| Archivo | Contenido |
|---------|-----------|
| `app/lambdas/evaluacion/handler.py` | Los cinco endpoints |
| `app/infra/stack.py` | Fila de `evaluacion` y sus rutas |
| `app/tests/test_evaluacion.py` | Tests |

## Tareas

- [x] Lista de clase: `leer_oferta` → `exigir_gestor_oferta` → `cache_aside` sobre la Query a `GSI1`.
- [x] Pendientes: Query a `GSI2` sin caché.
- [x] Aprobar: `SET estado … REMOVE GSI2PK, GSI2SK` con condición `estado = PENDIENTE`.
- [x] Calificar: validar la nota como `Decimal`, cuantizar a dos decimales, escribir `LSI1SK`.
- [x] Notas: Query a `LSI1` descendente y promedio ponderado.
- [x] Invalidar horario, notas y lista de clase tras cada escritura.

## Decisiones

| Decisión | Alternativa descartada | Motivo |
|----------|------------------------|--------|
| `UpdateItem` condicional | Transacción | Un solo ítem: la transacción cuesta el doble sin aportar nada |
| La autorización va antes de la caché | Cachear también la oferta | Un cambio de profesor no debe tardar en aplicarse |
| La cola de pendientes no se cachea | Cache-Aside con TTL corto | Es una cola de trabajo; el índice disperso ya la hace barata |
| Rechazar = retiro de la spec 006 | Estado `RECHAZADA` | Devuelve el cupo y libera la llave con el mismo flujo |

## Verificación

`python -m pytest tests/test_evaluacion.py -v`
