# Spec 002 — Módulo común

**Rama:** `spec/002-modulo-comun` · **Estado:** terminada · **Depende de:** 001

## Contexto

Todas las Lambdas necesitan lo mismo: armar llaves, hablar con DynamoDB, usar Redis sin caerse si falla, responder a API Gateway y saber quién hace la petición. El proyecto base trae un `cache.py` dentro de la Lambda `items`; con cinco Lambdas eso sería código repetido cinco veces.

## Objetivo

Una librería compartida (`app/lambdas/comun/`) que concentre el diseño de llaves y las reglas transversales, probada sin infraestructura.

## Alcance

Incluye los módulos `claves`, `db`, `cache`, `http` y `seguridad`, sus tests y los fixtures compartidos (`conftest.py`, `util.py`, `scripts/esquema.py`).

No incluye: handlers, infraestructura CDK.

## Requisitos

- **R1. Llaves en un solo lugar.** Ningún handler arma un `STUDENT#…` a mano; todo sale de `claves.py`.
- **R2. `ofertaId` reversible.** Del id se obtienen curso, periodo y grupo, y la llave primaria de la oferta.
- **R3. Sin `Scan`.** `db.py` solo expone `GetItem`, `Query` paginada y transacciones.
- **R4. Transacciones con diagnóstico.** Al cancelarse una transacción se sabe qué operación falló su condición.
- **R5. Redis nunca tumba una petición.** Toda función de `cache.py` atrapa `RedisError` y devuelve un valor neutro.
- **R6. Cache-Aside con negative caching** en una sola función reutilizable que informa la fuente (`cache` / `dynamodb`).
- **R7. Circuit breaker.** Tras un fallo de Redis no se reintenta durante `REDIS_PAUSA_FALLO` segundos.
- **R8. Contraseñas con hash y sal**; nunca en texto plano.
- **R9. Sesión verificable sin Redis** (firma + expiración) y revocable con Redis.
- **R10. Enrutador** que resuelve (método, recurso) → función y traduce errores de negocio a respuestas HTTP con CORS.

## Criterios de aceptación

- [x] `GRADE#` ordena igual que el número: `test_lsi_nota_orden_lexicografico_igual_al_numerico`.
- [x] Segunda lectura no toca la fuente: `test_cache_aside_miss_carga_y_luego_hit`.
- [x] Id inexistente no recarga: `test_negative_caching_evita_recargar_ids_inexistentes`.
- [x] Redis caído no lanza excepción: `test_operaciones_no_explotan_si_redis_falla`.
- [x] Tras un fallo no se vuelve a intentar: `test_circuit_breaker_omite_redis_tras_un_fallo`.
- [x] Token alterado o expirado se rechaza: `test_token_alterado_es_rechazado`, `test_token_expirado_es_rechazado`.
- [x] Logout invalida el token; con Redis caído se acepta la firma: `test_autenticar_tras_logout_retorna_401`, `test_autenticar_con_redis_caido_acepta_la_firma`.
- [x] Una excepción no controlada responde 500 sin filtrar el detalle: `test_excepcion_no_controlada_retorna_500_sin_filtrar_detalles`.
