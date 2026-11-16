# Plan 002 — Módulo común

## Enfoque

Empezar por `claves.py`, que es el diseño de la spec 001 convertido en funciones, y construir encima. Cada módulo se prueba solo: `moto` para DynamoDB y `fakeredis` para Redis.

## Archivos

| Archivo | Contenido |
|---------|-----------|
| `app/lambdas/comun/claves.py` | Llaves de tabla e índices, claves de Redis, validación de ids |
| `app/lambdas/comun/db.py` | `get_item`, `query` paginada, `transaccion` y constructores de operaciones |
| `app/lambdas/comun/cache.py` | get/set/delete, `cache_aside`, sesiones, rate limiting, Sorted Set, circuit breaker |
| `app/lambdas/comun/http.py` | `respuesta`, `ErrorApi`, `Enrutador`, lectura del evento |
| `app/lambdas/comun/seguridad.py` | PBKDF2, token HMAC, `autenticar`, autorización por rol |
| `app/scripts/esquema.py` | Definición de la tabla para moto (igual a la del stack) |
| `app/tests/conftest.py`, `util.py` | Fixtures y cliente que invoca handlers como API Gateway |

## Tareas

- [x] `claves.py` con el `ofertaId` compuesto y los prefijos de cada índice.
- [x] `db.py`: transacciones sobre el cliente del recurso (serializa tipos de Python).
- [x] `cache.py`: mantener `_get_client()` como punto de sustitución para los tests, igual que el proyecto base.
- [x] Timeouts de 0.5 s en el cliente Redis y circuit breaker.
- [x] `seguridad.py`: hash con la biblioteca estándar para no añadir dependencias compiladas al paquete de la Lambda.
- [x] `http.py`: enrutador por `event["resource"]`, con respaldo por `path`.
- [x] Tests de cada módulo.

## Riesgos

| Riesgo | Mitigación |
|--------|------------|
| Con Redis caído, cada operación de caché espera el timeout | Circuit breaker: un solo timeout y luego se omite Redis 15 s |
| El recurso de boto3 creado al importar no queda bajo el mock de moto | Se crea en el primer uso y los fixtures lo reinician |
| `redis-py` 8 deprecó `setex` | Se usa `set(..., ex=ttl)` |

## Verificación

`python -m pytest tests/test_claves.py tests/test_cache.py tests/test_seguridad.py tests/test_http.py -v`
