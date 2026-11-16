# Plan 001 — Diseño de datos

## Enfoque

Recorrer cada flujo del sistema como si ya hubiera que programarlo y anotar qué dato o qué condición falta en la v1. Lo que no se puede programar con lo escrito es un hueco; lo que se puede programar pero produce un dato incorrecto es un error.

## Tareas

- [x] Leer el enunciado del proyecto final y extraer lo que evalúa el docente.
- [x] Contrastar los 12 patrones de la v1 contra las pantallas de cada rol.
- [x] Escribir, para cada flujo de escritura, las operaciones y condiciones exactas.
- [x] Revisar la sección de Redis contra el principio "Redis no es fuente de verdad".
- [x] Redactar la v2 marcando cada cambio con **(v2)**.
- [x] Redactar `revision-diseno.md`.

## Decisiones tomadas en esta spec

| Decisión | Alternativa descartada | Motivo |
|----------|------------------------|--------|
| `ofertaId` compuesto `<curso>-<periodo>-<grupo>` | UUID + ítem de búsqueda por id | El id compuesto permite `GetItem` sin índice ni ítem extra |
| Rol de coordinación como tercer tipo de perfil | Dejar la carga de cursos a un script | Hace falta un actor para la cola de pendientes del periodo |
| TTL de 15 s para todo lo que muestra cupos | Invalidar el catálogo en cada matrícula | En la jornada de matrículas la invalidación dejaría la caché sin efecto |
| Token firmado + sesión en Redis | Sesión solo en Redis | Con Redis caído nadie podría autenticarse |

## Verificación

Lectura cruzada: cada endpoint de `docs/api.md` debe aparecer en la tabla de patrones, y cada condición del documento debe existir en el código de la spec que la implementa.
