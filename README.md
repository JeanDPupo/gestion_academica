# Gestión Académica

Proyecto final del curso de Bases de Datos No Relacionales (DynamoDB y Redis).

Backend serverless de matrícula universitaria: estudiantes que se inscriben en grupos de cursos, profesores que ven su lista de clase y califican, y una coordinación que publica la oferta y aprueba solicitudes. Todo en **una sola tabla DynamoDB**, con **Redis** como caché, almacén de sesiones y contador en tiempo real.

| | |
|---|---|
| Base de datos | DynamoDB, Single Table Design: 6 tipos de ítem, 1 LSI y 2 GSI sobrecargados |
| Caché | Redis: cache-aside, negative caching, sesiones, rate limiting y Sorted Set |
| API | 23 endpoints en API Gateway, 6 Lambdas en Python 3.11 |
| Infraestructura | AWS CDK en Python, desplegado en LocalStack con Docker Compose |
| Tests | 146 tests unitarios con pytest, moto y fakeredis |

## Arquitectura

```
Navegador ──▶ frontend (nginx :8080)          página estática de la demo
    │
    └──────▶ emulador (LocalStack :4566)
                 API Gateway ──▶ Lambda auth         registro, login, sesiones
                             ──▶ Lambda usuarios     perfiles
                             ──▶ Lambda cursos       cursos, ofertas, catálogo
                             ──▶ Lambda matriculas   matricular, retirar, cambiar de grupo
                             ──▶ Lambda evaluacion   aprobar, lista de clase, notas
                             ──▶ Lambda health       estado del servicio
                                    │        │
                              DynamoDB     redis (:6379)
                          fuente de verdad  caché, sesiones, ranking

cdk-dev   contenedor de trabajo: CDK, cdklocal, tests y scripts
```

Las seis Lambdas comparten el módulo `app/lambdas/comun/`, que el stack copia dentro del paquete de cada una. Ahí vive el diseño de llaves (`claves.py`) y el acceso a DynamoDB y Redis.

Regla que ordena todo el diseño: **DynamoDB decide, Redis acelera.** El cupo, los duplicados y los permisos se resuelven con condiciones y lecturas consistentes en DynamoDB. Si Redis se cae, el sistema sigue respondiendo desde DynamoDB.

## Puesta en marcha

Requisitos: Docker con Docker Compose.

```bash
# 1. Levantar los contenedores (emulador, redis, cdk-dev, frontend)
docker compose up -d --build

# 2. Desplegar el stack y cargar los datos de demo
docker compose exec cdk-dev bash scripts/desplegar.sh
```

`desplegar.sh` ejecuta `cdklocal bootstrap`, `cdklocal deploy` y `python scripts/seed.py`. El seed crea las cuentas, cursos, ofertas y matrículas llamando al API y verifica el código de cada respuesta, así que también sirve como prueba de punta a punta. Al terminar deja la URL del API en `frontend/config.js`.

Después:

- **Demo:** http://localhost:8080
- **API:** la URL que imprime el despliegue en `ApiUrl`. Ver [docs/api.md](docs/api.md).

Cuentas de demo (contraseña `Demo2026*`):

| Rol | Correo |
|-----|--------|
| Coordinación | `coordinacion@campus.example` |
| Profesor | `luis.mendoza@campus.example` |
| Estudiante con historial | `ana.perez@campus.example` |
| Estudiante sin matrículas | `daniel.rojas@campus.example` |

> LocalStack Community no guarda estado. Después de reiniciar el contenedor `emulador` hay que volver a ejecutar el paso 2; el `api-id` cambia y el seed actualiza `config.js`.

### Comandos útiles

Dentro de `cdk-dev` (`docker compose exec cdk-dev bash`):

```bash
python -m pytest tests/ -v                 # tests unitarios (no necesitan el emulador)
python scripts/seed.py                     # recargar datos y probar el API
python scripts/ver_tabla.py                # la tabla agrupada por particiones
python scripts/ver_tabla.py STUDENT#       # solo las particiones de estudiantes
python scripts/ver_tabla.py --indice GSI1  # la misma tabla vista desde un índice
cdklocal deploy                            # redesplegar tras un cambio
```

Desde la máquina:

```bash
docker compose exec redis redis-cli KEYS '*'
docker compose exec redis redis-cli ZREVRANGE demanda:2026-1 0 -1 WITHSCORES
docker compose stop redis                  # probar el modo degradado
docker compose start redis
```

### Sin Docker: modo simulación

Para probar cambios rápido, o como respaldo si el emulador no levanta:

```bash
cd app
pip install -r requirements.txt
python scripts/servidor_local.py           # http://localhost:8000
```

Levanta el API y el frontend en un solo proceso, con DynamoDB y Redis en memoria (moto y fakeredis). Los handlers son los mismos; lo simulado es la infraestructura. No reemplaza el despliegue con CDK, que es el entregable.

## Estructura

```
gestion_academica/
├── docker-compose.yml          # emulador, redis, cdk-dev y frontend
├── Dockerfile                  # imagen de cdk-dev
├── .env.example
├── app/
│   ├── cdk.json
│   ├── requirements.txt        # desarrollo y tests
│   ├── layers/dependencias/requirements.txt   # dependencias de las Lambdas
│   ├── infra/
│   │   ├── app.py              # punto de entrada CDK
│   │   └── stack.py            # tabla + índices + Lambdas + API (LAMBDAS y RUTAS)
│   ├── lambdas/
│   │   ├── comun/              # código compartido por todas las Lambdas
│   │   │   ├── claves.py       #   llaves de DynamoDB y de Redis
│   │   │   ├── db.py           #   GetItem, Query, transacciones
│   │   │   ├── cache.py        #   cache-aside, sesiones, rate limiting, ranking
│   │   │   ├── http.py         #   respuestas, errores, enrutador
│   │   │   ├── seguridad.py    #   contraseñas, tokens, autorización
│   │   │   └── dominio.py      #   reglas compartidas de matrícula
│   │   ├── auth/handler.py
│   │   ├── usuarios/handler.py
│   │   ├── cursos/handler.py
│   │   ├── matriculas/handler.py
│   │   ├── evaluacion/handler.py
│   │   └── health/handler.py
│   ├── scripts/                # seed, ver_tabla, desplegar, servidor_local
│   └── tests/
├── frontend/index.html         # demo
└── docs/
```

Para agregar un endpoint: una fila en `RUTAS` (`infra/stack.py`) y una función con `@rutas.ruta(...)` en el handler. `tests/test_rutas.py` falla si las dos listas no coinciden.

## Documentación

| Documento | Contenido |
|-----------|-----------|
| [docs/api.md](docs/api.md) | Los 23 endpoints: acceso, operación de DynamoDB, uso de Redis y ejemplos con curl |
| [docs/referencia/](docs/referencia/) | Currículo y proyecto base entregados por el docente |

## Estado de la verificación

| Qué | Cómo se verificó |
|-----|------------------|
| Reglas de negocio, llaves, índices, caché y modo degradado | 146 tests unitarios con moto y fakeredis |
| Plantilla de CloudFormation | `cdk synth` en modo AWS y en modo LocalStack |
| Paquete de cada Lambda | Importado de forma aislada desde `cdk.out` |
| API de punta a punta por HTTP | `seed.py` contra el servidor de simulación |
| Frontend | Recorrido automatizado de los tres roles en navegador |