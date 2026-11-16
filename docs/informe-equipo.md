# Proyecto final — Gestión Académica

Bases de Datos NoSQL · DynamoDB Single Table Design + Redis · Informe al equipo

## 1. Resumen

El backend está construido y probado; faltan dos pasos que solo se pueden hacer en un computador del equipo: **subir el repositorio a GitHub** y **correr el despliegue en LocalStack con Docker**. Ambos son un comando cada uno y están explicados en las secciones 8 y 9.

| Entregable del enunciado | Estado | Dónde está |
|---|---|---|
| 1. Documento de diseño | Listo | `docs/diseno-dynamodb-gestion-academica.md` y su versión en Word/PDF |
| 2. Código fuente | Listo, falta subirlo | Repositorio `gestion_academica`: Docker Compose, stack CDK, 6 Lambdas y tests |
| 3. Demo funcional | Lista, falta probarla en LocalStack | Frontend en `frontend/`, datos con `scripts/seed.py` |
| 4. Sustentación | Guion y preguntas preparados | `docs/guia-sustentacion.md` y secciones 10 y 11 de este informe |

En números: **23 endpoints** (el mínimo pedido era 10), **6 Lambdas**, **1 tabla** con 1 LSI y 2 GSI, **18 patrones de acceso**, **146 tests unitarios** que pasan, y **9 specs**, cada una con su plan y su rama.

## 2. Qué hace el sistema

Es el backend de matrícula de una universidad. Todo vive en una sola tabla DynamoDB; Redis acelera las lecturas, guarda las sesiones y lleva el ranking de cursos más solicitados.

| Rol | Qué puede hacer |
|---|---|
| Estudiante | Registrarse, ver el catálogo del periodo, matricularse, cambiar de grupo, retirar, ver su horario y sus notas |
| Profesor | Ver las ofertas que dicta, la lista de clase de cada una, aprobar o rechazar solicitudes de sus grupos y calificar |
| Coordinación | Crear cursos y ofertas, abrir o cerrar una oferta, ver la cola de matrículas pendientes del periodo y aprobarlas |

Reglas que el diseño garantiza en la base de datos, no en el código del cliente:

- Un estudiante tiene máximo una matrícula por curso y periodo, sin importar el grupo.
- Nadie se matricula sin cupo: el descuento del cupo y la creación de la matrícula van en la misma transacción.
- Un correo pertenece a un solo usuario, sea estudiante, profesor o coordinación.
- Solo el profesor dueño de la oferta (o coordinación) aprueba y califica; la nota va de 0.0 a 5.0.
- Una matrícula ya calificada no se retira ni cambia de grupo.

## 3. Arquitectura

Es la arquitectura del proyecto base del docente, con las Lambdas del dominio y un contenedor más para la página de la demo.

| Pieza | Qué es | Detalle |
|---|---|---|
| `emulador` | LocalStack 4.14 en el puerto 4566 | API Gateway, Lambda y DynamoDB |
| `redis` | Redis 7 en el puerto 6379 | Caché, sesiones, rate limiting y ranking |
| `cdk-dev` | Contenedor de trabajo | CDK, `cdklocal`, tests y scripts |
| `frontend` | nginx en el puerto 8080 | Sirve la página estática de la demo |
| Tabla DynamoDB | Single Table Design | `PK` + `SK`, `LSI1`, `GSI1` y `GSI2` |
| Lambda `auth` | 4 endpoints | Registro, login, logout y perfil propio |
| Lambda `usuarios` | 2 endpoints | Perfiles de estudiante y profesor |
| Lambda `cursos` | 6 endpoints | Cursos, ofertas y catálogo |
| Lambda `matriculas` | 5 endpoints | Matricular, horario, retirar, cambiar de grupo y demanda |
| Lambda `evaluacion` | 5 endpoints | Lista de clase, pendientes, aprobar, calificar y notas |
| Lambda `health` | 1 endpoint | Estado de DynamoDB y Redis |

Las seis Lambdas comparten el módulo `app/lambdas/comun/`. Ahí está el diseño de llaves (`claves.py`), el acceso a DynamoDB (`db.py`) y todo el manejo de Redis (`cache.py`).

La regla que ordena el diseño: **DynamoDB decide, Redis acelera.** El cupo, los duplicados y los permisos se resuelven con condiciones y lecturas consistentes en DynamoDB. Si Redis se cae, el sistema sigue respondiendo.

## 4. Tabla de patrones de acceso

Los patrones 1 a 12 son los del documento original del equipo; del 13 al 18 son las escrituras que se agregaron. Los valores son los de los datos de demo.

| # | Patrón de acceso (¿qué pregunta responde?) | Entidad | PK | SK | Índice | GSI PK | GSI SK |
|---|---|---|---|---|---|---|---|
| 1 | Dame el perfil de un estudiante | Estudiante | `STUDENT#2021114001` | `PROFILE` | Tabla principal | — | — |
| 2 | Dame el perfil de un profesor | Profesor | `PROF#P1001` | `PROFILE` | Tabla principal | — | — |
| 3 | Dame las matrículas de un estudiante en un periodo | Matrícula | `STUDENT#2021114001` | `begins_with ENROLL#2026-1#` | Tabla principal | — | — |
| 4 | Dame las matrículas de un estudiante de la nota más alta a la más baja | Matrícula | `STUDENT#2021114001` | `LSI1SK = GRADE#0460#2025-2#MAT101` | LSI1 | — | — |
| 5 | Dame los estudiantes de una oferta (lista de clase) | Matrícula | `STUDENT#2021114002` | `ENROLL#2026-1#MAT101` | GSI1 | `OFFER#MAT101-2026-1-G1` | `STUDENT#2021114002` |
| 6 | Dame un curso con todas sus ofertas activas | Curso, Oferta | `COURSE#MAT101` | `METADATA` y `begins_with OFFER#` | Tabla principal | — | — |
| 7 | Dame el catálogo de ofertas de un periodo | Oferta | `COURSE#MAT101` | `OFFER#2026-1#MAT101-2026-1-G1` | GSI2 | `PERIOD#2026-1` | `begins_with OFFER#` |
| 8 | Dame las ofertas que dicta un profesor | Oferta | `COURSE#MAT101` | `OFFER#2026-1#MAT101-2026-1-G1` | GSI1 | `PROF#P1001` | `begins_with PERIOD#2026-1#` |
| 9 | Dame las matrículas pendientes de un periodo, en orden de solicitud | Matrícula | `STUDENT#2021114003` | `ENROLL#2026-1#MAT101` | GSI2 (disperso) | `PERIOD#2026-1` | `begins_with PENDING#` |
| 10 | Matricula a un estudiante validando cupo y duplicados | Matrícula, Oferta, Estudiante | `STUDENT#…` y `COURSE#…` | `ENROLL#…` y `OFFER#…` | Tabla (transacción) | — | — |
| 11 | Inicia sesión por correo, con correo único | Email | `EMAIL#ana.perez@campus.example` | `LOGIN` | Tabla principal | — | — |
| 12 | Dame los estudiantes de una oferta que dicta el profesor autenticado | Oferta, Matrícula | `COURSE#MAT101` y `STUDENT#…` | `OFFER#…` y `ENROLL#…` | GSI1, tras un GetItem de la oferta | `OFFER#MAT101-2026-1-G1` | `begins_with STUDENT#` |
| 13 | Retira una matrícula y devuelve el cupo | Matrícula, Oferta | `STUDENT#…` y `COURSE#…` | `ENROLL#…` y `OFFER#…` | Tabla (transacción) | — | — |
| 14 | Cambia de grupo dentro del mismo curso | Matrícula, 2 Ofertas | `STUDENT#…` y `COURSE#…` | `ENROLL#…` y 2 `OFFER#…` | Tabla (transacción) | — | — |
| 15 | Aprueba una matrícula pendiente | Matrícula | `STUDENT#2021114003` | `ENROLL#2026-1#MAT101` | Tabla principal | sale de GSI2 | — |
| 16 | Califica una matrícula aprobada | Matrícula | `STUDENT#2021114002` | `ENROLL#2026-1#MAT101` | Tabla principal | entra a LSI1 | — |
| 17 | Crea un curso | Curso | `COURSE#EST205` | `METADATA` | Tabla principal | — | — |
| 18 | Crea una oferta, o la abre o cierra | Oferta | `COURSE#EST205` | `OFFER#2026-1#EST205-2026-1-G1` | Tabla principal | — | — |

Ninguna operación usa `Scan`.

## 5. Cambios frente al documento de diseño original

El modelo de llaves del documento original es correcto y se implementó tal cual: los 12 patrones, el LSI de notas, los dos GSI sobrecargados, los índices dispersos, el correo único y el grupo fuera de la SK de la matrícula. Cambiaron 11 puntos. El detalle, con el test que respalda cada uno, está en `docs/revision-diseno.md`.

| # | Tipo | Qué pasaba en el original | Qué quedó |
|---|---|---|---|
| 1 | Faltaba | El `ofertaId` no tenía formato, pero `GSI1PK = OFFER#<ofertaId>` exige que sea único en todo el sistema | `ofertaId = <cursoId>-<periodo>-<grupo>`, por ejemplo `MAT101-2026-1-G1`. Con solo el id se lee la oferta con `GetItem` |
| 2 | Faltaba | Nadie creaba cursos ni ofertas y no se decía quién aprueba | Tercer rol: coordinación (`ADMIN#<id>`) |
| 3 | Faltaba | Aprobar, rechazar y calificar no tenían flujo | `UpdateItem` condicional para aprobar y calificar; rechazar es un retiro hecho por el profesor |
| 4 | Faltaba | No se decía de dónde salen los datos que la matrícula copia | El servidor lee oferta y estudiante antes de la transacción; el cliente solo envía `ofertaId` |
| 5 | Faltaba | "Si requiere aprobación" no dependía de nada | Atributo `requiereAprobacion` en la oferta |
| 6 | Error | El retiro no tenía condiciones: dos retiros simultáneos devolvían el cupo dos veces | `Delete` y `Update` con condición; el cupo nunca supera el total |
| 7 | Error | El cambio de grupo aceptaba una oferta de otro curso | Se valida mismo curso y periodo, y se bloquea si ya hay nota |
| 8 | Error | Matricular no verificaba que el estudiante existiera | `ConditionCheck` del perfil dentro de la transacción |
| 9 | Redis | Catálogo con TTL de horas y cupos con TTL de segundos, pero el cupo viaja dentro del catálogo | Todo lo que muestra cupos se cachea 15 s |
| 10 | Redis | Sesiones solo en Redis: si Redis cae, nadie entra | Token firmado más registro en Redis para el logout; con Redis caído se valida la firma |
| 11 | Redis | El ranking se describía como write-behind con un volcado periódico que no existe | Sorted Set que vive solo en Redis; el volcado queda como trabajo futuro |

En el proyecto base del docente había además un detalle que rompía el despliegue: `LAMBDA_DOCKER_NETWORK` dependía del nombre de la carpeta. Quedó fijo con `name: gestion_academica` en `docker-compose.yml`.

## 6. Endpoints del API

E = estudiante, P = profesor, C = coordinación. "Dueño" es el usuario al que pertenece el recurso. La referencia completa, con cuerpos y ejemplos en curl, está en `docs/api.md`.

| # | Método | Ruta | Acceso | Qué hace | Patrón |
|---|---|---|---|---|---|
| 1 | GET | `/health` | Público | Estado de DynamoDB y Redis | — |
| 2 | POST | `/auth/registro` | Público | Crea el usuario con correo único (transacción) | 11 |
| 3 | POST | `/auth/login` | Público | Valida credenciales, rate limiting, abre sesión en Redis | 11 |
| 4 | POST | `/auth/logout` | Autenticado | Cierra la sesión | — |
| 5 | GET | `/auth/me` | Autenticado | Perfil del usuario de la sesión | 1, 2 |
| 6 | GET | `/estudiantes/{studentId}` | Dueño, P, C | Perfil del estudiante | 1 |
| 7 | GET | `/profesores/{profesorId}` | Autenticado | Perfil del profesor | 2 |
| 8 | POST | `/cursos` | C | Crea un curso | 17 |
| 9 | GET | `/cursos/{cursoId}` | Público | Curso y sus ofertas activas | 6 |
| 10 | POST | `/cursos/{cursoId}/ofertas` | C | Crea una oferta | 18 |
| 11 | GET | `/periodos/{periodo}/ofertas` | Público | Catálogo del periodo | 7 |
| 12 | GET | `/profesores/{profesorId}/ofertas` | Dueño, C | Ofertas que dicta un profesor | 8 |
| 13 | PUT | `/ofertas/{ofertaId}/estado` | C | Abre o cierra una oferta | 18 |
| 14 | POST | `/matriculas` | E, C | Matricula validando cupo y duplicados | 10 |
| 15 | GET | `/estudiantes/{studentId}/matriculas` | Dueño, C | Horario del periodo o historial | 3 |
| 16 | DELETE | `/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}` | Dueño, P de la oferta, C | Retira o rechaza y devuelve el cupo | 13 |
| 17 | PUT | `/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/grupo` | Dueño, C | Cambia de grupo | 14 |
| 18 | GET | `/periodos/{periodo}/demanda` | Público | Cursos más solicitados (Redis) | — |
| 19 | GET | `/ofertas/{ofertaId}/estudiantes` | P de la oferta, C | Lista de clase | 5, 12 |
| 20 | GET | `/periodos/{periodo}/matriculas/pendientes` | C | Cola de pendientes | 9 |
| 21 | POST | `/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/aprobar` | P de la oferta, C | Aprueba una matrícula | 15 |
| 22 | PUT | `/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/nota` | P de la oferta, C | Califica | 16 |
| 23 | GET | `/estudiantes/{studentId}/notas` | Dueño, C | Notas de mayor a menor y promedio | 4 |

Las lecturas devuelven un campo `_fuente` con `"cache"` o `"dynamodb"`. Es lo que se muestra en la demo para probar el cache-aside.

## 7. Redis: qué patrón se usa en cada dato

| Dato | Clave | Patrón | TTL e invalidación |
|---|---|---|---|
| Catálogo, detalle de curso, ofertas de un profesor | `catalogo:<periodo>`, `curso:<id>`, `ofertas-prof:<id>:<periodo>` | Cache-aside | 15 s; se borran al crear una oferta o cambiar su estado |
| Perfiles | `perfil:<rol>:<id>` | Cache-aside | 15 min |
| Horario del estudiante | `horario:<id>:<periodo>` | Cache-aside | 5 min; se borra al matricular, retirar, cambiar de grupo, aprobar o calificar |
| Lista de clase | `clase:<ofertaId>` | Cache-aside | 2 min; se borra con las mismas escrituras |
| Notas | `notas:<id>` | Cache-aside | 5 min; se borra al calificar |
| Ids que no existen | la clave del recurso | Negative caching | 30 s |
| Sesiones | `sesion:<jti>` | Almacén principal | 1 hora; se borra en el logout |
| Intentos de login | `limite:login:<correo>` | Contador (`INCR` + `EXPIRE`) | 5 intentos por minuto |
| Cursos más solicitados | `demanda:<periodo>` | Sorted Set (`ZINCRBY`) | Sin TTL |

Con Redis caído:

| Función | Qué pasa |
|---|---|
| Lecturas | Salen de DynamoDB (`_fuente: "dynamodb"`) |
| Matricular, retirar, aprobar, calificar | Funcionan igual |
| Login | Entra, sin rate limiting |
| Sesión | Se valida solo la firma del token |
| Ranking de demanda | Responde "no disponible" |
| `GET /health` | `200` con estado "degradado" |

Cada llamada a Redis tiene un timeout de 0.5 s y, tras un fallo, un circuit breaker lo omite durante 15 s.

## 8. Cómo correr el proyecto

Requisito: Docker con Docker Compose. Desde la carpeta del repositorio:

1. `docker compose up -d --build` levanta los cuatro contenedores.
2. `docker compose exec cdk-dev bash scripts/desplegar.sh` despliega el stack y carga los datos de demo. Debe terminar con "Todas las llamadas respondieron lo esperado".
3. Abrir `http://localhost:8080`.

Cuentas de demo, todas con la contraseña `Demo2026*`:

| Rol | Correo |
|---|---|
| Coordinación | `coordinacion@campus.example` |
| Profesor | `luis.mendoza@campus.example` |
| Estudiante con historial y notas | `ana.perez@campus.example` |
| Estudiante sin matrículas | `daniel.rojas@campus.example` |

Otros comandos, dentro de `cdk-dev`:

| Comando | Para qué |
|---|---|
| `python -m pytest tests/ -v` | Correr los 146 tests (no necesitan el emulador) |
| `python scripts/seed.py` | Recargar los datos y probar el API de punta a punta |
| `python scripts/ver_tabla.py` | Ver la tabla agrupada por particiones |
| `python scripts/ver_tabla.py --indice GSI1` | Ver la misma tabla desde un índice |

LocalStack no guarda estado: después de reiniciar el contenedor `emulador` hay que repetir el paso 2.

**Plan B sin Docker.** Desde `app/`: `pip install -r requirements.txt` y `python scripts/servidor_local.py`. Abre el mismo frontend en `http://localhost:8000` con DynamoDB y Redis simulados en memoria. Sirve para practicar y como respaldo; no reemplaza el despliegue, que es lo que se evalúa.

## 9. Repositorio, specs y ramas

El trabajo se organizó en 9 specs. Cada una tiene su `spec.md` (qué se construye y cómo se comprueba) y su `plan.md` (cómo se construye) en `docs/specs/`, y se desarrolló en su propia rama, integrada a `main`.

| # | Spec | Rama | Qué entrega |
|---|---|---|---|
| 001 | Diseño de datos | `spec/001-diseno-de-datos` | Documento de diseño v2 y revisión del original |
| 002 | Módulo común | `spec/002-modulo-comun` | Llaves, acceso a DynamoDB, caché, HTTP y seguridad |
| 003 | Infraestructura base | `spec/003-infraestructura-base` | Docker Compose, stack CDK con la tabla y sus índices |
| 004 | Autenticación y perfiles | `spec/004-autenticacion-y-perfiles` | 6 endpoints |
| 005 | Cursos y ofertas | `spec/005-cursos-y-ofertas` | 6 endpoints |
| 006 | Matrículas | `spec/006-matriculas` | 5 endpoints |
| 007 | Aprobación y notas | `spec/007-aprobacion-y-notas` | 5 endpoints |
| 008 | Demo | `spec/008-demo` | Datos iniciales, frontend y modo simulación |
| 009 | Documentación final | `spec/009-documentacion-final` | README, referencia del API y guía de sustentación |

**Falta subirlo a GitHub.** El repositorio quedó completo en la carpeta `ProyectoFinal/gestion_academica`, con `main` y las 9 ramas, pero el envío a GitHub necesita las credenciales de Jean. Se hace con doble clic en `ProyectoFinal/subir_a_github.bat`, o a mano desde esa carpeta con `git push origin --all`.

## 10. Sustentación

**Antes del día.** El despliegue en LocalStack todavía no se ha ejecutado en un equipo con Docker. Hay que hacerlo en el computador que se va a usar:

- Correr los pasos 1 a 3 de la sección 8 y confirmar que la página muestra "DynamoDB ok" y "Redis ok".
- Confirmar que en la traza de la página la segunda lectura del catálogo aparece como CACHÉ.
- Ejecutar `docker compose stop redis`, recargar la página y confirmar que sigue funcionando. Luego `docker compose start redis`.
- Ensayar el guion completo una vez, con cronómetro.

**Guion de la demo (10 a 12 minutos).**

| # | Qué se hace | Qué demuestra |
|---|---|---|
| 1 | `python scripts/ver_tabla.py` en la terminal | Una sola tabla con todas las entidades |
| 2 | Página sin iniciar sesión: ranking de demanda | Redis como contador (Sorted Set) |
| 3 | Entrar como Daniel Rojas, abrir el catálogo dos veces | Cache-aside: primero DynamoDB, luego caché |
| 4 | Matricular Física Mecánica | Transacción: matrícula y cupo juntos |
| 5 | Matricular Cálculo G1, que está lleno | 409: la condición falla y no se escribe nada |
| 6 | Matricular Cálculo G2 y volver a intentar G1 | Una matrícula por curso: lo garantiza la llave |
| 7 | Mi horario: cambiar de grupo o retirar | El grupo es un atributo; invalidación de caché |
| 8 | Entrar como Luis Mendoza: lista de clase | El mismo ítem visto desde el GSI1, sin N+1 |
| 9 | Aprobar y calificar a Daniel | Índices dispersos: sale de GSI2, entra a LSI1 |
| 10 | Entrar como Coordinación: pendientes | GSI sobrecargado |
| 11 | `docker compose stop redis` y seguir navegando | Modo degradado |
| 12 | Entrar como Ana Pérez: mis notas | Orden dado por la llave del LSI |

Si el tiempo aprieta, los pasos que no se pueden saltar son 3, 5, 6, 8 y 11.

**Reparto sugerido**, un bloque por integrante:

| Bloque | Tema | Pasos del guion | Qué estudiar |
|---|---|---|---|
| 1 | Problema, alcance y patrones de acceso | 1 | Diseño §1 y §2 |
| 2 | Modelo de tabla, llaves e índices | 8, 10 y 12 | Diseño §3 y §4 |
| 3 | Transacciones y reglas de negocio | 4 a 7 | Diseño §5 y `matriculas/handler.py` |
| 4 | Redis: patrones y modo degradado | 2, 3 y 11 | Diseño §7 y `comun/cache.py` |
| 5 | Infraestructura, tests y cierre | 9 | `infra/stack.py`, `tests/` y la revisión del diseño |

## 11. Preguntas probables

### 1. ¿Por qué una sola tabla y no una por entidad?

Porque se diseñó desde las consultas. El curso con sus ofertas y el estudiante con sus matrículas se leen juntos, así que viven en la misma partición y salen en una sola Query. Con una tabla por entidad habría que hacer varias lecturas y unirlas en código.

### 2. ¿Cómo garantizan que un estudiante no quede en dos grupos del mismo curso?

Con la llave. La SK de la matrícula es `ENROLL#<periodo>#<cursoId>` y el grupo es un atributo. Un segundo `Put` con `attribute_not_exists(PK)` falla aunque sea a otro grupo. No hay una validación en código que se pueda saltar.

### 3. ¿Qué pasa si dos estudiantes piden el último cupo al mismo tiempo?

Los dos llegan a la transacción, pero la condición `cuposDisponibles > 0` se evalúa de forma atómica en DynamoDB. Uno escribe; al otro se le cancela la transacción completa y recibe un 409.

### 4. ¿Por qué un GSI para la lista de clase y un LSI para las notas?

El LSI comparte la partición de la tabla: sirve para reordenar lo que ya está bajo la misma PK. Las notas son del mismo estudiante y solo cambia el orden. La lista de clase agrupa matrículas de muchos estudiantes, o sea otra partición, y eso es un GSI.

### 5. ¿Qué patrón de caché usan y por qué?

Cache-aside. La aplicación busca en Redis; si no está, lee DynamoDB y guarda con TTL. Es el patrón que tolera la caída de Redis sin cambiar nada. Al escribir se borra la clave en vez de actualizarla, porque dos escrituras simultáneas podrían dejar el valor viejo.

### 6. El cupo que muestra el catálogo, ¿es real?

Puede ir hasta 15 segundos atrasado. Se prefirió un TTL corto a invalidar en cada matrícula, porque en la jornada de inscripciones la clave más leída se borraría sin parar. Ese atraso no produce sobrecupo: quien decide es la transacción.

### 7. ¿Qué pasa si Redis se cae?

Las lecturas salen de DynamoDB, las escrituras funcionan, el login entra sin rate limiting y el ranking responde "no disponible". Se puede mostrar en vivo deteniendo el contenedor.

### 8. ¿Usan Scan en algún lado?

Ninguna Lambda. Solo `scripts/ver_tabla.py`, que es una herramienta para mostrar la tabla en la sustentación.

El resto de las preguntas, con el archivo que respalda cada respuesta, está en `docs/guia-sustentacion.md`.

## 12. Pendientes y riesgos

| # | Pendiente | Quién | Por qué importa |
|---|---|---|---|
| 1 | Subir el repositorio a GitHub | Jean | Es el entregable 2; hoy solo está en su computador |
| 2 | Correr el despliegue en LocalStack | Quien tenga Docker | Es lo único que no se ha ejecutado de verdad |
| 3 | Confirmar los integrantes en la portada de los documentos | Todos | Se tomaron del laboratorio de modelado |
| 4 | Ensayar la demo completa | Todos | El primer arranque de cada Lambda tarda varios segundos |
| 5 | Decidir quién presenta cada bloque | Todos | El reparto de la sección 10 es una sugerencia |

Lo que está probado: reglas de negocio, llaves, índices, caché y modo degradado con 146 tests; la plantilla de CloudFormation con `cdk synth`; el API por HTTP y el frontend en modo simulación. Lo que no: el despliegue en LocalStack. Si falla, lo más probable es CORS entre la página y el emulador o el nombre de la red de Docker; `docs/guia-sustentacion.md` tiene qué revisar en cada caso.

Fuera del alcance de esta versión: edición de perfiles, paginación del API y volcado del ranking de demanda a DynamoDB.
