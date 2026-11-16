# Plan 005 — Cursos y ofertas

## Enfoque

Una Lambda `cursos`. El punto delicado es la caché: las tres lecturas incluyen el cupo, que cambia con cada matrícula.

## Archivos

| Archivo | Contenido |
|---------|-----------|
| `app/lambdas/cursos/handler.py` | Los seis endpoints |
| `app/infra/stack.py` | Fila de `cursos` en `LAMBDAS` y seis filas en `RUTAS` |
| `app/tests/test_cursos.py` | Tests |

## Tareas

- [x] Crear curso con `attribute_not_exists(PK)`.
- [x] Crear oferta: leer curso y profesor (consistente), copiar sus datos, `PutItem` condicional.
- [x] Detalle del curso: Query por PK con filtro `entityType = COURSE OR estado = ACTIVA`.
- [x] Catálogo por `GSI2` y ofertas del profesor por `GSI1`.
- [x] `_ttl_cupos()` leído del entorno en cada llamada.
- [x] `_invalidar_oferta`: catálogo, curso y ofertas del profesor.
- [x] Cambio de estado con `ReturnValues=ALL_NEW` para saber qué claves invalidar.

## Decisiones

| Decisión | Alternativa descartada | Motivo |
|----------|------------------------|--------|
| TTL de 15 s en lo que muestra cupos | Invalidar el catálogo en cada matrícula | La clave más leída se borraría sin parar en la jornada de matrículas |
| TTL de 15 s | TTL de horas + estructura aparte para cupos | Poblar esa estructura requiere la misma Query del catálogo |
| Filtro en el detalle del curso | Estado dentro de la SK | La partición de un curso es pequeña; cambiar el estado obligaría a reescribir la llave |
| Catálogo y detalle públicos | Exigir sesión | Se consulta la oferta antes de tener cuenta; no expone datos personales |

## Verificación

`python -m pytest tests/test_cursos.py -v`
