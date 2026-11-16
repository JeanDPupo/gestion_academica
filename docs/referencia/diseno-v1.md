# Diseño DynamoDB (Single Table Design) y Redis — Sistema de Gestión Académica

## 1. Alcance

Entidades: **Estudiante**, **Profesor**, **Curso**, **Oferta** (grupo de un curso en un periodo, con profesor y cupos) y **Matrícula** (relación M:N entre estudiante y oferta).

Tanto estudiantes como profesores pueden iniciar sesión. El profesor ve las ofertas que dicta y la lista de estudiantes matriculados en ellas.

Regla clave: **un estudiante solo puede tener una matrícula por curso y periodo** (no puede estar en dos grupos del mismo curso a la vez). El diseño la garantiza con la propia llave de la matrícula: el grupo (`ofertaId`) va como atributo y no forma parte de la SK.

Ninguna colección crece sin límite: las matrículas por estudiante son decenas y los estudiantes por oferta están acotados por el cupo.

---

## 2. Patrones de acceso

Convención:
- **PK / SK**: llaves de la tabla base del ítem que se lee o escribe.
- **LSI SK**: atributo usado como Sort Key del LSI (comparte la PK de la tabla).
- **GSI PK / GSI SK**: llaves del GSI consultado.
- `-` = no aplica.

| # | Patrón | Entidades | PK | SK | Índice | LSI SK | GSI PK | GSI SK |
|---|--------|-----------|----|----|--------|--------|--------|--------|
| 1 | Perfil de un estudiante | Estudiante | `STUDENT#<studentId>` | `PROFILE` | Tabla (GetItem) | - | - | - |
| 2 | Perfil de un profesor | Profesor | `PROF#<profesorId>` | `PROFILE` | Tabla (GetItem) | - | - | - |
| 3 | Matrículas de un estudiante en un periodo | Matrícula | `STUDENT#<studentId>` | `begins_with ENROLL#<periodo>#` | Tabla (Query) | - | - | - |
| 4 | Matrículas de un estudiante ordenadas por nota | Matrícula | `STUDENT#<studentId>` | `ENROLL#<periodo>#<cursoId>` | LSI1 (Query) | `LSI1SK = GRADE#<nota×100, 4 dígitos>#<periodo>#<cursoId>` | - | - |
| 5 | Estudiantes matriculados en una oferta (lista de clase) | Matrícula, Estudiante, Oferta | `STUDENT#<studentId>` | `ENROLL#<periodo>#<cursoId>` | GSI1 (Query) | - | `GSI1PK = OFFER#<ofertaId>` | `GSI1SK = STUDENT#<studentId>` |
| 6 | Detalle de un curso y todas sus ofertas activas | Curso, Oferta | `COURSE#<cursoId>` | `METADATA` (curso) y `begins_with OFFER#` (ofertas, filtro `estado = ACTIVA`) | Tabla (Query por PK) | - | - | - |
| 7 | Catálogo de ofertas de un periodo | Oferta, Curso | `COURSE#<cursoId>` | `OFFER#<periodo>#<ofertaId>` | GSI2 (Query) | - | `GSI2PK = PERIOD#<periodo>` | `GSI2SK = begins_with OFFER#` |
| 8 | Ofertas que dicta un profesor | Profesor, Oferta | `COURSE#<cursoId>` | `OFFER#<periodo>#<ofertaId>` | GSI1 (Query) | - | `GSI1PK = PROF#<profesorId>` | `GSI1SK = begins_with PERIOD#<periodo>#` |
| 9 | Matrículas pendientes de aprobación de un periodo | Matrícula | `STUDENT#<studentId>` | `ENROLL#<periodo>#<cursoId>` | GSI2 (índice disperso) | - | `GSI2PK = PERIOD#<periodo>` | `GSI2SK = begins_with PENDING#` |
| 10 | Matricular validando cupo y duplicados | Matrícula, Oferta, Estudiante | `STUDENT#<studentId>` y `COURSE#<cursoId>` | `ENROLL#<periodo>#<cursoId>` y `OFFER#<periodo>#<ofertaId>` | Tabla (TransactWriteItems) | - | - | - |
| 11 | Login por email, con email único (estudiante o profesor) | Estudiante, Profesor | `EMAIL#<email-normalizado>` | `LOGIN` | Tabla (GetItem; TransactWriteItems al registrar) | - | - | - |
| 12 | Estudiantes inscritos en una oferta que dicta el profesor autenticado | Profesor, Oferta, Matrícula | `COURSE#<cursoId>` (oferta) y `STUDENT#<studentId>` (matrícula) | `OFFER#<periodo>#<ofertaId>` y `ENROLL#<periodo>#<cursoId>` | GSI1 (Query) tras validar con GetItem de la oferta | - | `GSI1PK = OFFER#<ofertaId>` | `GSI1SK = begins_with STUDENT#` |

**Resumen de índices:** 1 LSI (`LSI1`, notas) y 2 GSI sobrecargados (`GSI1`, `GSI2`).

---

## 3. Diseño de la tabla

**Tabla base:** `PK` (partition key) y `SK` (sort key).

| Índice | Tipo | PK | SK |
|--------|------|----|----|
| Tabla | - | `PK` | `SK` |
| `LSI1` | LSI | `PK` (la misma de la tabla) | `LSI1SK` |
| `GSI1` | GSI | `GSI1PK` | `GSI1SK` |
| `GSI2` | GSI | `GSI2PK` | `GSI2SK` |

| Item | PK | SK | LSI1 SK | GSI1 PK | GSI1 SK | GSI2 PK | GSI2 SK |
|------|----|----|---------|---------|---------|---------|---------|
| Estudiante | `STUDENT#<studentId>` | `PROFILE` | - | - | - | - | - |
| Profesor | `PROF#<profesorId>` | `PROFILE` | - | - | - | - | - |
| Email (login y unicidad) | `EMAIL#<email>` | `LOGIN` | - | - | - | - | - |
| Curso | `COURSE#<cursoId>` | `METADATA` | - | - | - | - | - |
| Oferta | `COURSE#<cursoId>` | `OFFER#<periodo>#<ofertaId>` | - | `PROF#<profesorId>` | `PERIOD#<periodo>#OFFER#<ofertaId>` | `PERIOD#<periodo>` | `OFFER#<cursoId>#<ofertaId>` |
| Matrícula | `STUDENT#<studentId>` | `ENROLL#<periodo>#<cursoId>` | `GRADE#<nota×100>#<periodo>#<cursoId>` (solo si tiene nota) | `OFFER#<ofertaId>` | `STUDENT#<studentId>` | `PERIOD#<periodo>` (solo si `PENDIENTE`) | `PENDING#<fechaSolicitudISO>#<studentId>#<cursoId>` (solo si `PENDIENTE`) |

### Atributos relevantes (no son keys)

| Item | Atributos principales |
|------|-----------------------|
| Estudiante | `studentId`, `nombre`, `email`, `programa`, `entityType = STUDENT` |
| Profesor | `profesorId`, `nombre`, `email`, `departamento`, `entityType = PROFESSOR` |
| Email | `userId`, `rol` (`STUDENT` / `PROFESSOR`), `passwordHash`, `entityType = EMAIL` |
| Curso | `cursoId`, `codigo`, `nombre`, `creditos`, `entityType = COURSE` |
| Oferta | `ofertaId`, `cursoId`, `nombreCurso`, `periodo`, `profesorId`, `nombreProfesor`, `horario`, `cuposTotales`, `cuposDisponibles`, `estado` (`ACTIVA` / `CERRADA`), `entityType = OFFER` |
| Matrícula | `studentId`, `nombreEstudiante`, `cursoId`, `periodo`, **`ofertaId` (grupo)**, `nombreCurso`, `creditos`, `horario`, `nota`, `estado` (`PENDIENTE` / `APROBADA`), `fechaSolicitud`, `entityType = ENROLLMENT` |

---

## 4. Explicación detallada de las keys

### 4.1 Keys de los Items (tabla base)

Se usa el patrón `ENTIDAD#id` en la PK y un prefijo descriptivo en la SK. Así conviven entidades distintas en una sola tabla sin colisiones, y lo que se consulta junto queda en la misma **item collection** (misma PK).

| Key | Significado |
|-----|-------------|
| `PK = STUDENT#<studentId>` | Agrupa todo lo que pertenece a un estudiante: perfil y matrículas. Una sola Query trae su perfil y su historial académico. |
| `SK = PROFILE` (estudiante) | Perfil del estudiante. Valor fijo porque solo hay uno por partición; permite `GetItem` directo (patrón 1). |
| `SK = ENROLL#<periodo>#<cursoId>` | Identifica una matrícula. Es única por **estudiante, curso y periodo**, y el grupo no forma parte de la llave. Por eso `attribute_not_exists(PK)` en el `Put` impide, por sí solo, matricularse dos veces en el mismo curso y periodo, sin importar el grupo. Ordena cronológicamente por periodo; con `begins_with ENROLL#2026-1#` se obtienen las de un periodo (patrón 3). El grupo se guarda en el atributo `ofertaId`. |
| `PK = PROF#<profesorId>` / `SK = PROFILE` | Perfil del profesor (patrón 2). Es una partición propia, separada de sus ofertas, porque las ofertas pertenecen al curso. Sus ofertas se consultan por `GSI1`. |
| `PK = COURSE#<cursoId>` | Agrupa el curso y todas sus ofertas. |
| `SK = METADATA` | Ítem con el detalle del curso (nombre, créditos). |
| `SK = OFFER#<periodo>#<ofertaId>` | Una oferta (grupo) de ese curso en un periodo. Al compartir PK con el curso, una Query trae el curso y sus ofertas (patrón 6); las activas se filtran por `estado`. |
| `PK = EMAIL#<email>` / `SK = LOGIN` | Ítem de unicidad e inicio de sesión **para ambos roles**. Guarda `userId`, `rol` y `passwordHash`. Al registrar un estudiante o un profesor se hace una transacción: `Put` del perfil + `Put` de este ítem con `attribute_not_exists(PK)`. Si el email ya existe, falla todo. El login es un `GetItem`, y según `rol` se carga el perfil correspondiente. El email se normaliza (minúsculas, sin espacios). |

### 4.2 Key del LSI

Los LSI comparten la PK de la tabla (`STUDENT#<studentId>`) y dan un orden alternativo dentro de la misma partición. Se definen al crear la tabla y no se pueden agregar después. Limitan la item collection a 10 GB por PK, más que suficiente para el historial de un estudiante.

| Índice | Atributo SK | Significado |
|--------|-------------|-------------|
| `LSI1` | `LSI1SK = GRADE#<nota×100 con ceros>#<periodo>#<cursoId>` | Ordena las matrículas del estudiante por nota. La nota se multiplica por 100 y se rellena con ceros (4.50 → `0450`) para que el orden lexicográfico coincida con el numérico. `periodo` y `cursoId` desempatan y garantizan unicidad (coinciden con la SK de la tabla). Con `ScanIndexForward=false` se obtienen de mayor a menor (patrón 4). **Es disperso:** solo las matrículas con nota tienen el atributo, así que entran al índice únicamente las calificadas. |

### 4.3 Keys de los GSI

Los GSI tienen PK y SK propias, independientes de la tabla, y se actualizan de forma asíncrona (consistencia eventual). Se usa **GSI overloading**: los atributos genéricos `GSIxPK` / `GSIxSK` guardan valores distintos según el tipo de ítem, y así dos GSI cubren varios patrones.

| Índice | Key | Significado |
|--------|-----|-------------|
| `GSI1` | `GSI1PK = PROF#<profesorId>` (Oferta) | Agrupa las ofertas que dicta un profesor. |
| | `GSI1SK = PERIOD#<periodo>#OFFER#<ofertaId>` (Oferta) | Ordena por periodo y permite filtrar con `begins_with PERIOD#2026-1#` (patrón 8). |
| | `GSI1PK = OFFER#<ofertaId>` (Matrícula) | Agrupa todas las matrículas de una oferta, invirtiendo la relación de la tabla base. Se alimenta del atributo `ofertaId` de la matrícula. |
| | `GSI1SK = STUDENT#<studentId>` (Matrícula) | Identifica a cada estudiante dentro de la oferta: lista de clase (patrones 5 y 12). |
| `GSI2` | `GSI2PK = PERIOD#<periodo>` | Agrupa por periodo académico, compartido entre ofertas y matrículas pendientes. |
| | `GSI2SK = OFFER#<cursoId>#<ofertaId>` (Oferta) | Catálogo del periodo: `begins_with OFFER#` (patrón 7), ordenado por curso. |
| | `GSI2SK = PENDING#<fechaSolicitudISO>#<studentId>#<cursoId>` (Matrícula) | Cola de pendientes del periodo en orden de solicitud (patrón 9). La llave de la matrícula se reconstruye con `studentId`, `periodo` y `cursoId`. **Es disperso:** al aprobar se hace `REMOVE GSI2PK, GSI2SK` y el ítem sale del índice. |

Como los valores de `GSI1PK` empiezan con prefijos distintos (`PROF#` y `OFFER#`), ambos tipos de ítem conviven en el mismo índice sin mezclarse.

---

## 5. Flujos clave

### 5.1 Matricular (patrón 10)

Una sola `TransactWriteItems` (todo o nada), con dos operaciones:

1. **Put** de la matrícula `STUDENT#<studentId>` / `ENROLL#<periodo>#<cursoId>`, con el grupo en el atributo `ofertaId` y la condición `attribute_not_exists(PK)` → evita matricular el mismo curso dos veces en el periodo, en cualquier grupo.
2. **Update** de la oferta `COURSE#<cursoId>` / `OFFER#<periodo>#<ofertaId>`: `SET cuposDisponibles = cuposDisponibles - :uno` con condición `cuposDisponibles > :cero AND estado = :activa` → protege el cupo sin condiciones de carrera.

Si una condición falla, no se escribe nada y `CancellationReasons` indica cuál fue. El cliente necesita `cursoId`, `periodo` y `ofertaId`, que ya vienen del catálogo (patrón 7). La matrícula nace con `estado = PENDIENTE` y con `GSI2PK` / `GSI2SK` si requiere aprobación.

### 5.2 Retirar una matrícula

`TransactWriteItems` con dos operaciones: `Delete` de la matrícula y `Update` de la oferta (`cuposDisponibles + 1`). Al borrar la matrícula, el estudiante puede volver a matricular ese curso en el periodo sin que la llave lo bloquee.

### 5.3 Cambiar de grupo

Como el grupo es un atributo, cambiarlo no crea ni borra la matrícula. Es una `TransactWriteItems` con tres operaciones:

1. **Update** de la matrícula: `SET ofertaId = :nueva, GSI1PK = OFFER#<nueva>, horario = :nuevoHorario`, con condición `ofertaId = :actual` (evita cambios concurrentes).
2. **Update** de la oferta anterior: `cuposDisponibles + 1`.
3. **Update** de la oferta nueva: `cuposDisponibles - 1` con condición `cuposDisponibles > 0 AND estado = ACTIVA`.

### 5.4 Registro y login de estudiante o profesor (patrón 11)

- **Registro:** transacción con `Put` del perfil (`STUDENT#` o `PROF#`) + `Put` de `EMAIL#<email>` con `attribute_not_exists(PK)`. El mismo email no puede existir como estudiante y como profesor a la vez.
- **Login:** `GetItem` de `EMAIL#<email>` → valida `passwordHash` → según `rol`, carga el perfil con `GetItem` y emite la sesión (en Redis).

### 5.5 Flujo del profesor (patrones 2, 8, 12)

1. Tras el login, `GetItem` de `PROF#<profesorId>` / `PROFILE`.
2. **Mis ofertas:** Query `GSI1` con `GSI1PK = PROF#<profesorId>` y `GSI1SK begins_with PERIOD#<periodo>#`.
3. **Lista de clase:** al elegir una oferta, se hace `GetItem` de la oferta y se verifica que `profesorId` coincida con el profesor autenticado (autorización). Luego Query `GSI1` con `GSI1PK = OFFER#<ofertaId>`. Como la matrícula guarda `nombreEstudiante`, la lista sale sin consultar cada perfil.

---

## 6. Decisiones de diseño

- **Grupo como atributo, sin ítem auxiliar.** La SK de la matrícula es `ENROLL#<periodo>#<cursoId>`, de modo que la propia llave garantiza "un grupo por curso y periodo". Es más simple que un ítem "candado" aparte. El costo es que la llave no dice el grupo (vive en `ofertaId`) y cambiar de grupo es un `Update` transaccional (flujo 5.3).
- **Retiro = borrar la matrícula.** Si la matrícula retirada se conservara con `estado = RETIRADA`, la llave seguiría ocupada y el estudiante no podría volver a matricular el curso. Para conservar historial de retiros habría que permitir el `Put` con `attribute_not_exists(PK) OR estado = :retirada` y quitar `GSI1PK`/`GSI1SK` de la matrícula retirada, para que no aparezca en la lista de clase.
- **Una sola matrícula, no dos copias.** `GSI1` invierte la relación M:N: el mismo ítem sirve para "matrículas del estudiante" (tabla) y "estudiantes de la oferta" (`GSI1`). La alternativa es duplicar el ítem (uno por lado) escribiéndolos en una transacción: da lecturas fuertemente consistentes en ambos lados, pero duplica el costo de escritura y obliga a mantener ambas copias sincronizadas. Para una lista de clase, la consistencia eventual del GSI es aceptable.
- **Desnormalización contra el N+1.** DynamoDB no tiene joins, así que la matrícula guarda `nombreCurso`, `creditos`, `horario` y `nombreEstudiante`. El horario completo del estudiante y la lista de clase salen de **una sola Query**. Es una instantánea al momento de matricular, correcta para un registro histórico (si cambia el grupo, se actualiza `horario`). La oferta guarda `nombreCurso` y `nombreProfesor` por la misma razón.
- **Índices dispersos.** `LSI1` (solo matrículas con nota) y las llaves de pendientes en `GSI2` (solo mientras `PENDIENTE`) mantienen los índices pequeños y baratos.
- **Email único.** Un GSI no puede garantizar unicidad; por eso existe el ítem `EMAIL#<email>` creado con condición dentro de una transacción.
- **Sin LSI de semestre.** El orden por semestre se descartó; la SK de la tabla ya ordena las matrículas por periodo.
- **Límite de un ítem caliente.** Todas las matrículas a una sección popular actualizan el mismo ítem (`cuposDisponibles`), y un ítem admite del orden de 1000 escrituras por segundo. Para una universidad suele sobrar; si no, se fragmenta el contador o se encolan las solicitudes (SQS).
- **Hot partition en `GSI2`.** `PERIOD#<periodo>` concentra catálogo y pendientes de un periodo. Si el volumen crece, se particiona la key (`PERIOD#2026-1#<0-9>`) y se consultan los shards en paralelo.
- **Consistencia.** Las lecturas de GSI son eventualmente consistentes; las de tabla y LSI pueden ser fuertemente consistentes (`ConsistentRead=true`). Las decisiones críticas (cupo, duplicados, autorización del profesor) usan tabla.
- **Proyección.** `LSI1` y los GSI pueden proyectar solo los atributos necesarios (`nota`, `estado`, `ofertaId`, `nombreEstudiante`, `nombreCurso`, `horario`) para reducir costo.

---

## 7. Redis: qué patrón, dónde y por qué

### Principio rector

Redis es **una optimización de lectura, nunca la fuente de verdad**. Las decisiones de negocio (¿hay cupo?, ¿ya está matriculado?, ¿esta oferta es del profesor?) las toma DynamoDB con condiciones o lecturas consistentes. Un cupo leído de Redis puede estar desactualizado: es aceptable para mostrarlo, no para decidir.

### Patrones por tipo de dato

| Dato | Patrón | TTL / invalidación | Por qué |
|------|--------|--------------------|---------|
| Catálogo de ofertas del periodo y detalle de curso (patrones 6 y 7) | **Cache-aside** + precalentamiento antes de abrir matrículas | TTL largo (horas) y borrar la clave al editar | Es lo más leído y casi no cambia |
| Perfil de estudiante y de profesor (patrones 1 y 2) | **Cache-aside** | TTL de 15 a 30 min y borrar al actualizar | Lectura frecuente, cambios raros |
| Horario / matrículas del estudiante (patrón 3) | **Cache-aside** con TTL corto | Borrar la clave tras el commit de la matrícula, el retiro o el cambio de grupo | Se consulta constantemente y cambia en momentos puntuales |
| Ofertas que dicta el profesor (patrón 8) | **Cache-aside** | TTL medio; borrar al cambiar una oferta | Cambia solo al editar ofertas |
| Lista de clase de una oferta (patrones 5 y 12) | **Cache-aside** con TTL corto | Borrar la clave al matricular, retirar o cambiar de grupo | Se consulta mucho, sobre todo al inicio del periodo |
| Cupos disponibles (visualización) | **Cache-aside** con TTL de pocos segundos | Expira solo | Es volátil y se tolera cierta desactualización |
| Notas | **Cache-aside** | Invalidar al publicarlas (idealmente por evento) | Pico de lecturas cuando se publican |
| IDs inexistentes | **Negative caching** | TTL de 30 a 60 s | Evita que consultas a IDs falsos golpeen siempre DynamoDB |
| Sesiones y tokens (estudiante y profesor), rate limiting del login | Redis como **almacén principal** | TTL | No es caché, es el dato mismo |
| Contadores de demanda (cursos más solicitados) | **Write-behind** con `ZINCRBY` y volcado periódico | - | Dato no crítico que tolera pérdida |

### Por qué estos y no otros

- **Cache-aside como patrón por defecto.** Es simple, tolera la caída de Redis (si falla, se lee de DynamoDB) y solo cachea lo que realmente se pide.
- **Invalidar (borrar) en vez de actualizar la caché al escribir.** Si dos escrituras concurrentes actualizan la caché, puede quedar el valor viejo. Borrar es seguro: la siguiente lectura repuebla.
- **No usar write-behind para matrículas ni notas.** Si Redis cae antes de volcar a DynamoDB, se pierden datos críticos. Solo sirve para métricas.
- **Write-through casi no aplica.** Tendría sentido si se escribe y se lee de inmediato el mismo dato (por ejemplo, preferencias del perfil), pero añade latencia a cada escritura. Con invalidación basta.
- **Autorización siempre contra DynamoDB.** La verificación de que una oferta pertenece al profesor (flujo 5.5) no debe apoyarse en una caché que pueda estar desactualizada.
