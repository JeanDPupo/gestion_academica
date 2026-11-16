# Plan 003 — Infraestructura base

## Enfoque

Partir de los archivos del docente y cambiar lo mínimo. El stack pasa de declarar cada Lambda y cada ruta a mano a recorrer dos tablas (`LAMBDAS` y `RUTAS`): las specs siguientes solo agregan filas.

## Archivos

| Archivo | Cambio frente al proyecto base |
|---------|-------------------------------|
| `docker-compose.yml` | `name: gestion_academica`, red fija para las Lambdas, puertos y secretos por variable |
| `.env.example` | Nuevo (figuraba en la estructura del enunciado pero no existía) |
| `app/infra/stack.py` | Índices de la tabla, tablas `LAMBDAS` y `RUTAS`, empaquetado con `comun/`, `OPTIONS` por recurso |
| `app/infra/app.py` | Stack renombrado a `GestionAcademicaStack` |
| `app/lambdas/health/handler.py` | Estado "degradado"; respuestas con CORS |
| `docs/referencia/` | README y manual originales del docente, como referencia |

## Tareas

- [x] Fijar el nombre del proyecto Compose y `LAMBDA_DOCKER_NETWORK`.
- [x] Declarar LSI1, GSI1 y GSI2 con proyección ALL.
- [x] Extender el bundling local para copiar `lambdas/comun/` a cada paquete.
- [x] Recorrer `RUTAS` con `resource_for_path` y agregar `OPTIONS` una vez por recurso.
- [x] `grant_read_data` / `grant_read_write_data` según la Lambda.
- [x] Tests de health y de consistencia stack ↔ handlers.
- [x] `cdk synth` en modo AWS y en modo LocalStack; importar cada paquete generado de forma aislada.

## Riesgos

| Riesgo | Mitigación |
|--------|------------|
| CDK reutiliza el resultado del bundling entre assets con el mismo origen: todas las Lambdas recibirían el mismo código | Cada Lambda usa su propia carpeta como origen del asset. Detectado al revisar `cdk.out` |
| El preflight CORS con integración MOCK puede comportarse distinto en el emulador | El `OPTIONS` va por integración Lambda proxy, la más probada en LocalStack |
| El `api-id` cambia en cada despliegue del emulador | Output `ApiId` y `scripts/seed.py` escribe la URL para el frontend (spec 008) |

## Verificación

`cdk synth -q` (dentro de `app/`) y `python -m pytest tests/test_health.py tests/test_rutas.py -v`.
El despliegue real se verifica con `bash scripts/desplegar.sh` dentro de `cdk-dev`.
