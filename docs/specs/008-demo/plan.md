# Plan 008 — Demo

## Enfoque

El seed usa el API en vez de escribir en la tabla: así los cupos, los índices y los contadores quedan como los dejaría el uso real, y cada despliegue se prueba solo. La única escritura directa es la cuenta de coordinación.

## Archivos

| Archivo | Contenido |
|---------|-----------|
| `app/scripts/seed.py` | Datos de demo y prueba de punta a punta |
| `app/scripts/ver_tabla.py` | Vista de la tabla por particiones (única parte que usa `Scan`) |
| `app/scripts/desplegar.sh` | `bootstrap` + `deploy` + seed |
| `app/scripts/servidor_local.py` | Modo simulación |
| `frontend/index.html` | Página única con las vistas de los tres roles y la traza |
| `docker-compose.yml` | Servicio `frontend` (nginx) y montaje de `./frontend` en `cdk-dev` |

## Tareas

- [x] Datos: 1 coordinación, 3 profesores, 6 estudiantes, 5 cursos, 8 ofertas en dos periodos.
- [x] Escenarios sembrados: un grupo lleno, solicitudes rechazadas por cupo, pendientes, aprobadas e historial con notas.
- [x] Descubrir el `api-id` con `apigateway.get_rest_apis` y la tabla con los outputs del stack.
- [x] Frontend: cliente del API con traza, vistas por rol, textos explicativos.
- [x] Escapar todo dato dinámico que entre al HTML.
- [x] Servidor de simulación con las rutas que registran los handlers.
- [x] Recorrido automatizado en navegador y revisión de capturas.

## Decisiones

| Decisión | Motivo |
|----------|--------|
| Frontend en un cuarto contenedor | No toca los tres contenedores del enunciado; solo sirve archivos estáticos |
| `ver_tabla.py` usa `Scan` | Es una herramienta de inspección para la sustentación, no un patrón de acceso; ninguna Lambda hace `Scan` |
| Modo simulación | Plan B si el emulador no levanta el día de la sustentación, y ciclo corto al desarrollar. No reemplaza el despliegue |

## Verificación

`python scripts/servidor_local.py` (desde `app/`) y abrir `http://localhost:8000`.
