# Spec 003 — Infraestructura base

**Rama:** `spec/003-infraestructura-base` · **Estado:** terminada · **Depende de:** 002

## Contexto

El docente entregó un proyecto base con tres contenedores (emulador, Redis y `cdk-dev`), un stack CDK con una tabla PK+SK y dos Lambdas de ejemplo. Hay que adaptarlo al modelo de la spec 001 sin cambiar su estructura ni su flujo de trabajo.

## Objetivo

Que `docker compose up` + `cdklocal deploy` dejen desplegada la tabla con sus índices, el API Gateway y el health check, listos para recibir las Lambdas de cada dominio.

## Alcance

Incluye: `docker-compose.yml`, `Dockerfile`, `.env.example`, stack CDK (tabla, LSI1, GSI1, GSI2, layer, API), Lambda `health` y el empaquetado del módulo `comun` dentro de cada Lambda.

No incluye: Lambdas de negocio.

## Requisitos

- **R1.** Se conserva la estructura de carpetas y los pasos del proyecto base.
- **R2.** La tabla declara `LSI1`, `GSI1` y `GSI2` con las llaves de la spec 001. El LSI se define al crear la tabla: no se puede agregar después.
- **R3.** Cada Lambda se empaqueta con su `handler.py` y con `comun/`. En LocalStack además lleva las dependencias, porque la edición Community no monta layers.
- **R4.** Agregar un endpoint es agregar una fila a `RUTAS`.
- **R5.** Mínimo privilegio: solo reciben permiso de escritura las Lambdas que escriben.
- **R6.** El API responde el preflight CORS (`OPTIONS`) de cada recurso.
- **R7.** El nombre de la red de Docker no depende de la carpeta donde se clone el repo.
- **R8.** `GET /health` distingue "degradado" (Redis caído, `200`) de "error" (DynamoDB caído, `503`).

## Criterios de aceptación

- [x] `cdk synth` produce una plantilla con la tabla, 1 LSI y 2 GSI.
- [x] Cada Lambda recibe un asset distinto que contiene `handler.py` y `comun/`.
- [x] Las rutas del stack coinciden con las que registra cada handler: `tests/test_rutas.py`.
- [x] Health degradado y en error: `tests/test_health.py`.
- [ ] `cdklocal deploy` en LocalStack: **pendiente de ejecutar en un equipo con Docker** (ver `docs/guia-sustentacion.md`, lista de verificación).
