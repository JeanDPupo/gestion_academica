# Diseño DynamoDB (Single Table Design) y Redis — Sistema de Gestión Académica

**Versión 2** — es la versión que está implementada en este repositorio.
Parte del documento de diseño original del equipo (v1) y conserva su modelo de llaves. Los cambios frente a la v1, con su justificación, están en [revision-diseno.md](revision-diseno.md); aquí aparecen marcados con **(v2)**.

## 1. Alcance

Entidades: **Estudiante**, **Profesor**, **Coordinación** **(v2)**, **Curso**, **Oferta** (grupo de un curso en un periodo, con profesor y cupos) y **Matrícula** (relación M:N entre estudiante y oferta).

Los tres roles inician sesión. El estudiante se matricula; el profesor ve las ofertas que dicta, la lista de estudiantes de cada una, aprueba solicitudes y califica; coordinación crea cursos y ofertas y atiende la cola de matrículas pendientes del periodo.

Regla clave: **un estudiante solo puede tener una matrícula por curso y periodo** (no puede estar en dos grupos del mismo curso a la vez). El diseño la garantiza con la propia llave de la matrícula: el grupo (`ofertaId`) va como atributo y no forma parte de la SK.

Ninguna colección crece sin límite: las matrículas por estudiante son decenas, los estudiantes por oferta están acotados por el cupo y las ofertas de un curso son unas pocas por periodo.

---

## 2. Patrones de acceso

Convención:
- **PK / SK**: llaves de la tabla base del ítem que se lee o escribe.
- **LSI SK**: atributo usado como Sort Key del LSI (comparte la PK de la tabla).
- **GSI PK / GSI SK**: llaves del GSI consultado.
- `-` = no aplica.

### 2.1 Lecturas

| # | Patrón | Entidades | PK | SK | Índice | LSI SK | GSI PK | GSI SK | Endpoint |
|---|--------|-----------|----|----|--------|--------|--------|--------|----------|
| 1 | Perfil de un estudiante | Estudiante | `STUDENT#<studentId>` | `PROFILE` | Tabla (GetItem) | - | - | - | `GET /estudiantes/{studentId}` |
| 2 | Perfil de un profesor | Profesor | `PROF#<profesorId>` | `PROFILE` | Tabla (GetItem) | - | - | - | `GET /profesores/{profesorId}` |
| 3 | Matrículas de un estudiante en un periodo | Matrícula | `STUDENT#<studentId>` | `begins_with ENROLL#<periodo>#` | Tabla (Query) | - | - | - | `GET /estudiantes/{studentId}/matriculas?periodo=` |
| 4 | Matrículas de un estudiante ordenadas por nota | Matrícula | `STUDENT#<studentId>` | `ENROLL#<periodo>#<cursoId>` | LSI1 (Query) | `LSI1SK = GRADE#<nota×100, 4 dígitos>#<periodo>#<cursoId>` | - | - | `GET /estudiantes/{studentId}/notas` |
| 5 | Estudiantes matriculados en una oferta (lista de clase) | Matrícula, Estudiante, Oferta | `STUDENT#<studentId>` | `ENROLL#<periodo>#<cursoId>` | GSI1 (Query) | - | `GSI1PK = OFFER#<ofertaId>` | `GSI1SK = STUDENT#<studentId>` | `GET /ofertas/{ofertaId}/estudiantes` |
| 6 | Detalle de un curso y todas sus ofertas activas | Curso, Oferta | `COURSE#<cursoId>` | `METADATA` (curso) y `begins_with OFFER#` (ofertas, filtro `estado = ACTIVA`) | Tabla (Query por PK) | - | - | - | `GET /cursos/{cursoId}` |
| 7 | Catálogo de ofertas de un periodo | Oferta, Curso | `COURSE#<cursoId>` | `OFFER#<periodo>#<ofertaId>` | GSI2 (Query) | - | `GSI2PK = PERIOD#<periodo>` | `GSI2SK = begins_with OFFER#` | `GET /periodos/{periodo}/ofertas` |
| 8 | Ofertas que dicta un profesor | Profesor, Oferta | `COURSE#<cursoId>` | `OFFER#<periodo>#<ofertaId>` | GSI1 (Query) | - | `GSI1PK = PROF#<profesorId>` | `GSI1SK = begins_with PERIOD#<periodo>#` | `GET /profesores/{profesorId}/ofertas?periodo=` |
| 9 | Matrículas pendientes de aprobación de un periodo | Matrícula | `STUDENT#<studentId>` | `ENROLL#<periodo>#<cursoId>` | GSI2 (índice disperso) | - | `GSI2PK = PERIOD#<periodo>` | `GSI2SK = begins_with PENDING#` | `GET /periodos/{periodo}/matriculas/pendientes` |
| 11 | Login por email, con email único (cualquier rol) | Estudiante, Profesor, Coordinación | `EMAIL#<email-normalizado>` | `LOGIN` | Tabla (GetItem; TransactWriteItems al registrar) | - | - | - | `POST /auth/login`, `POST /auth/registro` |
| 12 | Estudiantes inscritos en una oferta que dicta el profesor autenticado | Profesor, Oferta, Matrícula | `COURSE#<cursoId>` (oferta) y `STUDENT#<studentId>` (matrícula) | `OFFER#<periodo>#<ofertaId>` y `ENROLL#<periodo>#<cursoId>` | GSI1 (Query) tras validar con GetItem de la oferta | - | `GSI1PK = OFFER#<ofertaId>` | `GSI1SK = begins_with STUDENT#` | `GET /ofertas/{ofertaId}/estudiantes` |

### 2.2 Escrituras

| # | Patrón | Ítems que toca | Operación | Endpoint |
|---|--------|----------------|-----------|----------|
| 10 | Matricular validando cupo y duplicados | Matrícula (Put), Oferta (Update), Estudiante (ConditionCheck) | TransactWriteItems | `POST /matriculas` |
| 13 **(v2)** | Retirar una matrícula (o rechazar la solicitud) devolviendo el cupo | Matrícula (Delete), Oferta (Update) | TransactWriteItems | `DELETE /estudiantes/{studentId}/matriculas/{periodo}/{cursoId}` |
| 14 **(v2)** | Cambiar de grupo dentro del mismo curso y periodo | Matrícula (Update), Oferta anterior (Update), Oferta nueva (Update) | TransactWriteItems | `PUT …/matriculas/{periodo}/{cursoId}/grupo` |
| 15 **(v2)** | Aprobar una matrícula pendiente | Matrícula | UpdateItem condicional (`REMOVE GSI2PK, GSI2SK`) | `POST …/matriculas/{periodo}/{cursoId}/aprobar` |
| 16 **(v2)** | Calificar una matrícula aprobada | Matrícula | UpdateItem condicional (`SET nota, LSI1SK`) | `PUT …/matriculas/{periodo}/{cursoId}/nota` |
| 17 **(v2)** | Crear curso | Curso | PutItem condicional | `POST /cursos` |
| 18 **(v2)** | Crear oferta / abrir o cerrar una oferta | Oferta | PutItem / UpdateItem condicional | `POST /cursos/{cursoId}/ofertas`, `PUT /ofertas/{ofertaId}/estado` |

**Resumen de índices:** 1 LSI (`LSI1`, notas) y 2 GSI sobrecargados (`GSI1`, `GSI2`). **Ninguna operación usa `Scan`.**

---

## 3. Diseño de la tabla

**Tabla base:** `PK` (partition key) y `SK` (sort key).

| Índice | Tipo | PK | SK | Proyección |
|--------|------|----|----|-----------|
| Tabla | - | `PK` | `SK` | - |
| `LSI1` | LSI | `PK` (la misma de la tabla) | `LSI1SK` | ALL |
| `GSI1` | GSI | `GSI1PK` | `GSI1SK` | ALL |
| `GSI2` | GSI | `GSI2PK` | `GSI2SK` | ALL |

| Item | PK | SK | LSI1 SK | GSI1 PK | GSI1 SK | GSI2 PK | GSI2 SK |
|------|----|----|---------|---------|---------|---------|---------|
| Estudiante | `STUDENT#<studentId>` | `PROFILE` | - | - | - | - | - |
| Profesor | `PROF#<profesorId>` | `PROFILE` | - | - | - | - | - |
| Coordinación **(v2)** | `ADMIN#<adminId>` | `PROFILE` | - | - | - | - | - |
| Email (login y unicidad) | `EMAIL#<email>` | `LOGIN` | - | - | - | - | - |
| Curso | `COURSE#<cursoId>` | `METADATA` | - | - | - | - | - |
| Oferta | `COURSE#<cursoId>` | `OFFER#<periodo>#<ofertaId>` | - | `PROF#<profesorId>` | `PERIOD#<periodo>#OFFER#<ofertaId>` | `PERIOD#<periodo>` | `OFFER#<cursoId>#<ofertaId>` |
| Matrícula | `STUDENT#<studentId>` | `ENROLL#<periodo>#<cursoId>` | `GRADE#<nota×100>#<periodo>#<cursoId>` (solo si tiene nota) | `OFFER#<ofertaId>` | `STUDENT#<studentId>` | `PERIOD#<periodo>` (solo si `PENDIENTE`) | `PENDING#<fechaSolicitudISO>#<studentId>#<cursoId>` (solo si `PENDIENTE`) |

### Identificadores **(v2)**

| Identificador | Formato | Ejemplo |
|---------------|---------|---------|
| `studentId`, `profesorId`, `adminId` | letras, números, `.` y `_` (máx. 40) | `2021114001`, `P1001` |
| `cursoId` | 2 a 12 letras mayúsculas o números | `MAT101` |
| `periodo` | `AAAA-N` | `2026-1` |
| `grupo` | 1 a 6 letras mayúsculas o números | `G1` |
| `ofertaId` | **`<cursoId>-<periodo>-<grupo>`** | `MAT101-2026-1-G1` |

El `ofertaId` es compuesto y determinístico. Eso resuelve dos cosas que la v1 dejaba abiertas:

- `GSI1PK = OFFER#<ofertaId>` exige que el id sea único en todo el sistema, no solo dentro de un curso. Al incluir curso y periodo, lo es por construcción.
- Con solo el `ofertaId` se reconstruye la llave primaria de la oferta (`COURSE#<cursoId>` / `OFFER#<periodo>#<ofertaId>`) y se lee con `GetItem`. Los flujos de matrícula, lista de clase, aprobación y calificación necesitan leer la oferta y no siempre tienen a mano el curso y el periodo.

Los alfabetos excluyen `#` y `-` donde chocarían con los separadores de las llaves.

### Atributos relevantes (no son keys)

| Item | Atributos principales |
|------|-----------------------|
| Estudiante | `studentId`, `nombre`, `email`, `programa`, `entityType = STUDENT` |
| Profesor | `profesorId`, `nombre`, `email`, `departamento`, `entityType = PROFESSOR` |
| Coordinación | `adminId`, `nombre`, `email`, `dependencia`, `entityType = ADMIN` |
| Email | `userId`, `rol` (`STUDENT` / `PROFESSOR` / `ADMIN`), `passwordHash`, `entityType = EMAIL` |
| Curso | `cursoId`, `nombre`, `creditos`, `entityType = COURSE` |
| Oferta | `ofertaId`, `cursoId`, `nombreCurso`, `creditos`, `periodo`, `grupo`, `profesorId`, `nombreProfesor`, `horario`, `cuposTotales`, `cuposDisponibles`, `estado` (`ACTIVA` / `CERRADA`), `requiereAprobacion`, `entityType = OFFER` |
| Matrícula | `studentId`, `nombreEstudiante`, `cursoId`, `periodo`, **`ofertaId` (grupo)**, `grupo`, `nombreCurso`, `creditos`, `horario`, `nombreProfesor`, `nota`, `estado` (`PENDIENTE` / `APROBADA`), `fechaSolicitud`, `fechaAprobacion`, `aprobadaPor`, `fechaNota`, `entityType = ENROLLMENT` |

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
| `PK = ADMIN#<adminId>` / `SK = PROFILE` | Perfil de la cuenta de coordinación. **(v2)** |
| `PK = COURSE#<cursoId>` | Agrupa el curso y todas sus ofertas. |
| `SK = METADATA` | Ítem con el detalle del curso (nombre, créditos). |
| `SK = OFFER#<periodo>#<ofertaId>` | Una oferta (grupo) de ese curso en un periodo. Al compartir PK con el curso, una Query trae el curso y sus ofertas (patrón 6); las activas se filtran por `estado`. `METADATA` ordena antes que `OFFER#`, así que el curso llega primero. |
| `PK = EMAIL#<email>` / `SK = LOGIN` | Ítem de unicidad e inicio de sesión **para todos los roles**. Guarda `userId`, `rol` y `passwordHash`. Al registrar un usuario se hace una transacción: `Put` del perfil + `Put` de este ítem, ambos con `attribute_not_exists(PK)`. Si el email ya existe, falla todo. El login es un `GetItem`, y según `rol` se carga el perfil correspondiente. El email se normaliza (minúsculas, sin espacios). |

Sobre el filtro del patrón 6: `FilterExpression` no reduce lo que DynamoDB lee, solo lo que devuelve. Aquí es aceptable porque la partición de un curso es pequeña y acotada; no es un `Scan` con filtro sobre toda la tabla.

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

Como los valores de `GSI1PK` empiezan con prefijos distintos (`PROF#` y `OFFER#`), ambos tipos de ítem conviven en el mismo índice sin mezclarse. En `GSI2` comparten la partición del periodo y los separa el prefijo de la SK (`OFFER#` / `PENDING#`).

---

## 5. Flujos clave

### 5.1 Matricular (patrón 10)

Antes de escribir se leen, con `ConsistentRead`, la oferta y el perfil del estudiante **(v2)**: de ahí salen los datos que la matrícula copia (`nombreCurso`, `creditos`, `horario`, `grupo`, `nombreProfesor`, `nombreEstudiante`) y si la oferta requiere aprobación.

Luego una sola `TransactWriteItems` (todo o nada), con tres operaciones:

1. **Put** de la matrícula `STUDENT#<studentId>` / `ENROLL#<periodo>#<cursoId>`, con el grupo en el atributo `ofertaId` y la condición `attribute_not_exists(PK)` → evita matricular el mismo curso dos veces en el periodo, en cualquier grupo.
2. **Update** de la oferta `COURSE#<cursoId>` / `OFFER#<periodo>#<ofertaId>`: `SET cuposDisponibles = cuposDisponibles - :uno` con condición `cuposDisponibles > :cero AND estado = :activa` → protege el cupo sin condiciones de carrera.
3. **ConditionCheck** del perfil del estudiante: `attribute_exists(PK)` **(v2)** → no se crea una matrícula de un usuario que dejó de existir entre la lectura y la escritura.

Si una condición falla, no se escribe nada y `CancellationReasons` indica cuál fue: la primera se responde como "ya matriculado" y la segunda como "sin cupo u oferta cerrada" (ambas `409`). El cliente solo envía el `ofertaId`, que viene del catálogo (patrón 7).

La matrícula nace `PENDIENTE` y con `GSI2PK` / `GSI2SK` si la oferta tiene `requiereAprobacion = true`; si no, nace `APROBADA` y nunca entra a `GSI2` **(v2)**. El cupo se descuenta al solicitar, no al aprobar: una solicitud pendiente reserva su puesto.

### 5.2 Retirar una matrícula (patrón 13)

`TransactWriteItems` con dos operaciones:

1. **Delete** de la matrícula con condición `attribute_exists(PK) AND ofertaId = :oferta AND attribute_not_exists(nota)` **(v2)**.
2. **Update** de la oferta: `cuposDisponibles + 1` con condición `attribute_exists(PK) AND cuposDisponibles < cuposTotales` **(v2)**.

Las condiciones existen porque, sin ellas, dos retiros simultáneos de la misma matrícula (o un retiro repetido) devolverían el cupo dos veces y `cuposDisponibles` superaría a `cuposTotales`. `ofertaId = :oferta` asegura que el cupo vuelve al grupo donde la matrícula sigue estando, aunque un cambio de grupo concurrente se haya confirmado justo antes.

Al borrar la matrícula, el estudiante puede volver a matricular ese curso en el periodo sin que la llave lo bloquee. Una matrícula calificada no se retira. El mismo flujo sirve para **rechazar** una solicitud pendiente: lo ejecuta el profesor de la oferta o coordinación.

### 5.3 Cambiar de grupo (patrón 14)

Como el grupo es un atributo, cambiarlo no crea ni borra la matrícula. Se valida que la oferta nueva sea del mismo curso y periodo **(v2)** y se ejecuta una `TransactWriteItems` con tres operaciones:

1. **Update** de la matrícula: `SET ofertaId = :nueva, GSI1PK = OFFER#<nueva>, grupo, horario, nombreProfesor`, con condición `ofertaId = :actual AND attribute_not_exists(nota)` (evita cambios concurrentes y cambios sobre un curso ya calificado).
2. **Update** de la oferta anterior: `cuposDisponibles + 1`, con la misma condición de devolución del retiro.
3. **Update** de la oferta nueva: `cuposDisponibles - 1` con condición `cuposDisponibles > 0 AND estado = ACTIVA`.

`GSI1SK` (`STUDENT#<studentId>`) no cambia: la matrícula simplemente pasa de la lista de clase de un grupo a la del otro.

### 5.4 Registro y login (patrón 11)

- **Registro:** transacción con `Put` del perfil (`STUDENT#`, `PROF#` o `ADMIN#`) + `Put` de `EMAIL#<email>`, ambos con `attribute_not_exists(PK)`. El mismo email no puede existir con dos roles. Crear una cuenta de coordinación exige la sesión de otra cuenta de coordinación; la primera se siembra con el script de datos iniciales.
- **Contraseña:** se guarda el hash PBKDF2-HMAC-SHA256 con sal aleatoria, nunca el texto.
- **Login:** rate limiting por email → `GetItem` consistente de `EMAIL#<email>` → verificación del hash → según `rol`, carga del perfil → emisión de la sesión (sección 7).

### 5.5 Flujo del profesor (patrones 2, 8, 12, 15, 16)

1. Tras el login, `GetItem` de `PROF#<profesorId>` / `PROFILE`.
2. **Mis ofertas:** Query `GSI1` con `GSI1PK = PROF#<profesorId>` y `GSI1SK begins_with PERIOD#<periodo>#`.
3. **Lista de clase:** al elegir una oferta, se hace `GetItem` consistente de la oferta y se verifica que `profesorId` coincida con el profesor autenticado (autorización). Luego Query `GSI1` con `GSI1PK = OFFER#<ofertaId>`. Como la matrícula guarda `nombreEstudiante`, la lista sale sin consultar cada perfil.
4. **Aprobar (v2):** `UpdateItem` de la matrícula: `SET estado = APROBADA, fechaAprobacion, aprobadaPor REMOVE GSI2PK, GSI2SK`, con condición `estado = PENDIENTE`. Una segunda aprobación falla la condición (`409`).
5. **Calificar (v2):** `UpdateItem`: `SET nota, LSI1SK = GRADE#…, fechaNota`, con condición `estado = APROBADA`. La nota va de 0.0 a 5.0 con dos decimales. Recalificar reescribe `LSI1SK` y la matrícula cambia de posición en el índice.

Aprobar, calificar y rechazar repiten la autorización del punto 3: se lee la matrícula, de ella el `ofertaId`, y la oferta de DynamoDB.

### 5.6 Flujo de coordinación **(v2)**

- **Crear curso:** `PutItem` con `attribute_not_exists(PK)`.
- **Crear oferta:** se leen el curso y el profesor (para copiar `nombreCurso`, `creditos` y `nombreProfesor`) y se hace `PutItem` condicional. `cuposDisponibles` nace igual a `cuposTotales`.
- **Abrir o cerrar oferta:** `UpdateItem` de `estado`. Una oferta `CERRADA` deja de aparecer en el detalle del curso y rechaza matrículas.
- **Pendientes del periodo:** Query `GSI2` con `GSI2SK begins_with PENDING#`; se aprueban o rechazan con los flujos anteriores.

---

## 6. Decisiones de diseño

- **Grupo como atributo, sin ítem auxiliar.** La SK de la matrícula es `ENROLL#<periodo>#<cursoId>`, de modo que la propia llave garantiza "un grupo por curso y periodo". Es más simple que un ítem "candado" aparte. El costo es que la llave no dice el grupo (vive en `ofertaId`) y cambiar de grupo es un `Update` transaccional (flujo 5.3).
- **Retiro = borrar la matrícula.** Si la matrícula retirada se conservara con `estado = RETIRADA`, la llave seguiría ocupada y el estudiante no podría volver a matricular el curso. Para conservar historial de retiros habría que permitir el `Put` con `attribute_not_exists(PK) OR estado = :retirada` y quitar `GSI1PK`/`GSI1SK` de la matrícula retirada, para que no aparezca en la lista de clase.
- **Una sola matrícula, no dos copias.** `GSI1` invierte la relación M:N: el mismo ítem sirve para "matrículas del estudiante" (tabla) y "estudiantes de la oferta" (`GSI1`). La alternativa es duplicar el ítem (uno por lado) escribiéndolos en una transacción: da lecturas fuertemente consistentes en ambos lados, pero duplica el costo de escritura y obliga a mantener ambas copias sincronizadas. Para una lista de clase, la consistencia eventual del GSI es aceptable.
- **Desnormalización contra el N+1.** DynamoDB no tiene joins, así que la matrícula guarda `nombreCurso`, `creditos`, `horario`, `nombreProfesor` y `nombreEstudiante`. El horario completo del estudiante y la lista de clase salen de **una sola Query**. Es una instantánea al momento de matricular, correcta para un registro histórico (si cambia el grupo, se actualiza). La oferta guarda `nombreCurso`, `creditos` y `nombreProfesor` por la misma razón.
- **Índices dispersos.** `LSI1` (solo matrículas con nota) y las llaves de pendientes en `GSI2` (solo mientras `PENDIENTE`) mantienen los índices pequeños y baratos.
- **Email único.** Un GSI no puede garantizar unicidad; por eso existe el ítem `EMAIL#<email>` creado con condición dentro de una transacción.
- **Transacciones solo donde hay dos ítems que deben cambiar juntos.** Matricular, retirar, cambiar de grupo y registrar. Aprobar, calificar y crear son escrituras de un solo ítem con condición: una transacción costaría el doble de capacidad sin aportar nada.
- **Sin LSI de semestre.** El orden por semestre se descartó; la SK de la tabla ya ordena las matrículas por periodo.
- **Proyección ALL en los tres índices (v2).** La lista de clase, el catálogo, la cola de pendientes y las notas muestran casi todos los atributos del ítem. Proyectar solo algunos ahorraría almacenamiento y costo de escritura en los índices, a cambio de mantener la lista de atributos en sincronía con el API. Para el volumen de un curso universitario se prefirió la simplicidad; es el primer ajuste si el costo de escritura llegara a importar.
- **Límite de un ítem caliente.** Todas las matrículas a una sección popular actualizan el mismo ítem (`cuposDisponibles`), y un ítem admite del orden de 1000 escrituras por segundo. Para una universidad suele sobrar; si no, se fragmenta el contador o se encolan las solicitudes (SQS).
- **Hot partition en `GSI2`.** `PERIOD#<periodo>` concentra catálogo y pendientes de un periodo. Si el volumen crece, se particiona la key (`PERIOD#2026-1#<0-9>`) y se consultan los shards en paralelo.
- **Consistencia.** Las lecturas de GSI son eventualmente consistentes; las de tabla y LSI pueden ser fuertemente consistentes (`ConsistentRead=true`). Las decisiones críticas (cupo, duplicados, autorización del profesor, login recién registrado) usan la tabla con lectura consistente o una condición de escritura.

---

## 7. Redis: qué patrón, dónde y por qué

### Principio rector

Redis es **una optimización de lectura, nunca la fuente de verdad**. Las decisiones de negocio (¿hay cupo?, ¿ya está matriculado?, ¿esta oferta es del profesor?) las toma DynamoDB con condiciones o lecturas consistentes. Un cupo leído de Redis puede estar desactualizado: es aceptable para mostrarlo, no para decidir.

### Patrones por tipo de dato

| Dato | Clave en Redis | Patrón | TTL / invalidación | Por qué |
|------|----------------|--------|--------------------|---------|
| Catálogo del periodo, detalle de curso, ofertas de un profesor (patrones 6, 7, 8) | `catalogo:<periodo>`, `curso:<cursoId>`, `ofertas-prof:<id>:<periodo>` | **Cache-aside** | TTL de 15 s (`TTL_CUPOS`); además se borran al crear una oferta o cambiar su estado | Es lo más leído. Las tres respuestas incluyen `cuposDisponibles` **(v2, ver abajo)** |
| Perfil de estudiante y de profesor (patrones 1 y 2) | `perfil:<rol>:<id>` | **Cache-aside** | TTL de 15 min | Lectura frecuente, cambios raros |
| Horario / matrículas del estudiante (patrón 3) | `horario:<studentId>:<periodo>` | **Cache-aside** | TTL de 5 min; se borra tras el commit de matricular, retirar, cambiar de grupo, aprobar o calificar | Se consulta constantemente y cambia en momentos puntuales |
| Lista de clase de una oferta (patrones 5 y 12) | `clase:<ofertaId>` | **Cache-aside** | TTL de 2 min; se borra con las mismas escrituras | Se consulta mucho, sobre todo al inicio del periodo |
| Notas (patrón 4) | `notas:<studentId>` | **Cache-aside** | TTL de 5 min; se borra al calificar | Pico de lecturas cuando se publican |
| IDs inexistentes (perfiles, cursos) | la misma clave del recurso | **Negative caching** | TTL de 30 s; se borra al crear el recurso | Evita que consultas a IDs falsos golpeen siempre DynamoDB |
| Sesiones | `sesion:<jti>` | Redis como **almacén principal** | TTL de 1 h (`SESION_TTL`); se borra en el logout | Revocación inmediata de un token firmado **(v2)** |
| Rate limiting del login | `limite:login:<email>` | Contador con ventana fija (`INCR` + `EXPIRE`) | 5 intentos por minuto; se borra en un login exitoso | Frena fuerza bruta sin tocar DynamoDB |
| Cursos más solicitados | `demanda:<periodo>` | **Sorted Set** (`ZINCRBY`, `ZREVRANGE`) | Sin TTL | Métrica en tiempo real que tolera pérdida **(v2)** |
| Cola de pendientes (patrón 9) | no se cachea | - | - | Es una cola de trabajo: debe verse al día |

### El cupo y el catálogo **(v2)**

La v1 proponía cachear el catálogo con TTL de horas y, aparte, los cupos con TTL de segundos. Pero el cupo no es un dato aparte: `cuposDisponibles` es un atributo del mismo ítem de oferta que compone el catálogo. Un catálogo cacheado por horas mostraría cupos de hace horas.

Las opciones eran:

1. **Invalidar el catálogo en cada matrícula.** Correcto, pero en la jornada de matrículas la clave más leída se borraría sin parar: justo cuando más se necesita la caché, casi todas las lecturas serían miss.
2. **Separar el cupo en otra estructura** (un hash `cupos:<periodo>`) y componer la respuesta. Para poblarla hay que hacer la misma Query del catálogo, así que no ahorra nada y agrega una segunda fuente de inconsistencia.
3. **TTL corto en todo lo que muestra cupos.** Es la elegida. Con 15 s, por más lecturas que lleguen hay como máximo una Query a DynamoDB cada 15 s por periodo, y el cupo mostrado nunca va más de 15 s atrasado.

El atraso no produce sobrecupo: quien decide es la condición `cuposDisponibles > 0` dentro de la transacción. En el peor caso un estudiante ve "1 libre", solicita y recibe un `409`.

### Sesiones y modo degradado **(v2)**

La v1 guardaba la sesión solo en Redis. Con ese diseño, si Redis cae ningún usuario puede autenticarse: la optimización se vuelve un punto único de falla, lo contrario del principio rector.

En la v2 el login emite un **token firmado** (HMAC-SHA256) con usuario, rol y expiración, y además registra la sesión en Redis:

1. Cada petición valida firma y expiración del token, sin ir a ningún almacén.
2. Luego consulta `sesion:<jti>` en Redis. Si Redis responde que no existe, la sesión fue cerrada → `401`.
3. Si Redis no responde, se acepta el token válido.

Así Redis conserva su papel (permite logout y revocación inmediata) y su caída solo quita esa capacidad durante el incidente. La autorización de negocio nunca pasa por Redis.

### Comportamiento si Redis no está disponible

| Función | Con Redis caído |
|---------|-----------------|
| Lecturas con cache-aside | Se sirven desde DynamoDB (`_fuente: "dynamodb"`) |
| Escrituras (matricular, retirar…) | Funcionan igual; la invalidación se omite y las claves viejas expiran por TTL |
| Login | Funciona sin rate limiting (fail-open) y sin registro de sesión |
| Validación de sesión | Solo firma y expiración |
| Ranking de demanda | El endpoint responde `disponible: false`, sin datos |
| `GET /health` | `200` con `estado: "degradado"` (`503` solo si falla DynamoDB) |

Todas las llamadas a Redis tienen timeout de 0.5 s. Tras un fallo, un **circuit breaker** omite Redis durante 15 s: sin él, una petición que hace varias operaciones de caché pagaría el timeout una vez por operación.

### Por qué estos y no otros

- **Cache-aside como patrón por defecto.** Es simple, tolera la caída de Redis (si falla, se lee de DynamoDB) y solo cachea lo que realmente se pide.
- **Invalidar (borrar) en vez de actualizar la caché al escribir.** Si dos escrituras concurrentes actualizan la caché, puede quedar el valor viejo. Borrar es seguro: la siguiente lectura repuebla. La invalidación ocurre después de confirmar la escritura en DynamoDB.
- **No usar write-behind para matrículas ni notas.** Si Redis cae antes de volcar a DynamoDB, se pierden datos críticos.
- **El contador de demanda no es write-behind (v2).** La v1 lo describía como write-behind con volcado periódico a DynamoDB. Lo implementado es más simple: el Sorted Set es el único lugar donde vive el dato. No hay proceso de volcado; si se quisiera historial duradero, el paso siguiente sería una Lambda programada (EventBridge) que copie el ranking a un ítem `PERIOD#<periodo>` / `DEMAND`.
- **Write-through casi no aplica.** Tendría sentido si se escribe y se lee de inmediato el mismo dato, pero añade latencia a cada escritura. Con invalidación basta.
- **Autorización siempre contra DynamoDB.** La verificación de que una oferta pertenece al profesor (flujo 5.5) no se apoya en una caché que pueda estar desactualizada, aunque la lista de clase sí esté cacheada.

---

## 8. Fuera del alcance de esta versión

- Edición de perfiles y cambio de email (requeriría mover el ítem `EMAIL#` en una transacción).
- Paginación en el API: las colecciones están acotadas y se devuelven completas.
- Protección contra *cache stampede* al expirar una clave muy leída.
- Particionado de `GSI2` y fragmentación del contador de cupos (sección 6): descritos, no implementados.
- DynamoDB Streams, TTL de DynamoDB y volcado del ranking de demanda.
