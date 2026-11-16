# Revisión del documento de diseño (v1 → v2)

El diseño original del equipo (v1) se contrastó contra tres cosas: el enunciado del proyecto final, lo que el código necesita para implementar cada flujo, y el principio del curso de que Redis complementa a DynamoDB sin reemplazarlo.

**Conclusión: el modelo de llaves de la v1 es correcto y se implementó tal cual.** Los 12 patrones de acceso, el LSI de notas, los dos GSI sobrecargados, los índices dispersos, el ítem de email único y la decisión de dejar el grupo fuera de la SK de la matrícula quedaron como estaban. Los cambios son de tres tipos: huecos que impedían implementar (faltaba definir algo), dos errores de consistencia y dos decisiones de Redis que contradecían el principio rector del propio documento.

La versión vigente es [diseno-dynamodb-gestion-academica.md](diseno-dynamodb-gestion-academica.md).

## Lo que se mantuvo

| Decisión de la v1 | Verificación |
|-------------------|--------------|
| `SK = ENROLL#<periodo>#<cursoId>` sin el grupo | Un segundo `Put` a otro grupo del mismo curso falla la condición. Test: `test_no_se_puede_matricular_dos_veces_el_mismo_curso` |
| `GSI1` invierte la relación matrícula ↔ oferta | La lista de clase sale de una Query, sin leer perfiles. Test: `test_lista_de_clase_sale_del_gsi1_sin_consultar_perfiles` |
| `GSI2` compartido entre catálogo y pendientes | El prefijo de la SK los separa. Test: `test_pendientes_no_incluye_ofertas_del_catalogo` |
| `GSI2` disperso para pendientes | Al aprobar, el ítem sale del índice. Test: `test_aprobar_saca_la_matricula_del_indice_de_pendientes` |
| `LSI1SK = GRADE#<nota×100>` con ceros a la izquierda | Orden lexicográfico = orden numérico. Test: `test_lsi_nota_orden_lexicografico_igual_al_numerico` |
| Email único con ítem `EMAIL#` en transacción | El segundo registro falla y no deja perfil huérfano. Test: `test_email_duplicado_retorna_409_y_no_crea_el_segundo_perfil` |
| Retiro = borrar la matrícula | Tras retirar se puede volver a matricular. Test: `test_tras_retirar_se_puede_volver_a_matricular` |
| Cache-aside por defecto, invalidar en vez de actualizar | Implementado en `comun/cache.py` y `comun/dominio.py` |

## Cambios

### Huecos: la v1 no lo definía y sin eso no se podía implementar

| # | Qué faltaba | Qué se decidió | Dónde |
|---|-------------|----------------|-------|
| 1 | **Unicidad y formato del `ofertaId`.** `GSI1PK = OFFER#<ofertaId>` solo funciona si el id es único en todo el sistema, y varios flujos necesitan leer la oferta teniendo solo su id (la llave de la oferta requiere curso y periodo). | `ofertaId = <cursoId>-<periodo>-<grupo>`, p. ej. `MAT101-2026-1-G1`. Único por construcción y suficiente para reconstruir la llave y hacer `GetItem`. | Diseño §3 · `comun/claves.py` |
| 2 | **Quién crea cursos y ofertas, y quién aprueba.** Solo había estudiante y profesor; el patrón 9 (pendientes de todo un periodo) es una vista que no pertenece a ninguno de los dos. | Tercer rol, coordinación (`ADMIN#<id>` / `PROFILE`). Crea cursos y ofertas y ve la cola del periodo. Aprueban coordinación o el profesor dueño de la oferta. | Diseño §1, §5.6 |
| 3 | **Flujos de aprobar, rechazar y calificar.** La v1 mencionaba el `REMOVE` de las llaves de `GSI2` y el `LSI1SK`, pero no la operación, sus condiciones ni quién la ejecuta. | Aprobar: `UpdateItem` con condición `estado = PENDIENTE`. Calificar: `UpdateItem` con condición `estado = APROBADA`, nota 0.0–5.0. Rechazar = retiro ejecutado por el profesor o coordinación. | Diseño §5.5 · Lambda `evaluacion` |
| 4 | **De dónde salen los datos desnormalizados.** La matrícula copia nombre del curso, créditos, horario y nombre del estudiante, pero el flujo solo decía que el cliente envía `cursoId`, `periodo` y `ofertaId`. | El servidor lee oferta y estudiante (consistente) antes de la transacción. La oferta también guarda `creditos` y `grupo` para que una sola lectura alcance. El cliente solo envía `ofertaId`. | Diseño §5.1 |
| 5 | **Cuándo una matrícula requiere aprobación.** La v1 decía "si requiere aprobación" sin decir de qué depende. | Atributo `requiereAprobacion` en la oferta. Si es falso, la matrícula nace `APROBADA` y no entra a `GSI2`. | Diseño §5.1 |

### Errores de consistencia

| # | Problema en la v1 | Consecuencia | Corrección |
|---|-------------------|--------------|------------|
| 6 | **El retiro no tenía condiciones.** `Delete` de la matrícula + `cuposDisponibles + 1`, sin `ConditionExpression`. | `DeleteItem` sobre un ítem que no existe no falla. Dos retiros simultáneos, o un reintento, devuelven el cupo dos veces: `cuposDisponibles` supera a `cuposTotales` y el grupo acepta más estudiantes de los que caben. | `Delete` con `attribute_exists(PK) AND ofertaId = :oferta AND attribute_not_exists(nota)`; `Update` con `cuposDisponibles < cuposTotales`. Test: `test_retirar_matricula_inexistente_no_infla_los_cupos` |
| 7 | **El cambio de grupo no validaba el destino ni la oferta de origen.** | Se podía pedir un "cambio" a una oferta de otro curso (la matrícula quedaría apuntando a un grupo que no corresponde a su llave) y la devolución del cupo anterior tenía el mismo problema del punto 6. | Se exige mismo curso y periodo, se bloquea si hay nota y la oferta anterior lleva la condición de devolución. Test: `test_cambiar_de_grupo_valida_curso_periodo_y_grupo_actual` |
| 8 | **Matricular no verificaba que el estudiante existiera.** | Si el perfil deja de existir entre la lectura y la escritura, o coordinación envía un id inexistente, quedaría una matrícula sin estudiante. | `ConditionCheck` del perfil dentro de la transacción. |

### Redis: decisiones que contradecían el principio rector

| # | Problema en la v1 | Consecuencia | Corrección |
|---|-------------------|--------------|------------|
| 9 | **Catálogo con TTL de horas y cupos con TTL de segundos, como si fueran datos separados.** `cuposDisponibles` es un atributo del ítem de oferta, que es justo lo que compone el catálogo. | El catálogo mostraría cupos de hace horas. Y si se invalidara en cada matrícula, la clave más leída se borraría sin parar en plena jornada. | Todo lo que muestra cupos (catálogo, detalle de curso, ofertas del profesor) usa TTL de 15 s (`TTL_CUPOS`). Máximo una Query cada 15 s por periodo y máximo 15 s de atraso; el cupo real lo decide la transacción. Diseño §7. |
| 10 | **Sesiones solo en Redis.** | Si Redis cae, nadie puede autenticarse. El enunciado pide definir el comportamiento con Redis caído y el propio documento decía que Redis no es fuente de verdad. | Token firmado (HMAC) + registro en Redis para logout y revocación. Con Redis caído se valida solo la firma. Tests: `test_autenticar_tras_logout_retorna_401`, `test_autenticar_con_redis_caido_acepta_la_firma` |
| 11 | **Contador de demanda descrito como write-behind con volcado periódico.** | No existe el proceso que vuelca: describirlo como write-behind prometía algo que no está. | Se documenta como lo que es: un Sorted Set que vive solo en Redis. El volcado queda como trabajo futuro. |

### Ajustes menores

- **Proyección de índices:** la v1 sugería proyectar solo algunos atributos; se usa `ALL` y se explica el costo (Diseño §6).
- **Modo degradado explícito:** tabla de qué hace cada función con Redis caído, timeout de 0.5 s y circuit breaker de 15 s (Diseño §7).
- **`GET /health`:** con Redis caído responde `200` y `estado: "degradado"`; `503` solo si falla DynamoDB. En el proyecto base cualquiera de los dos devolvía `503`.
- **Numeración de patrones:** se conservan los números 1–12 de la v1; las escrituras nuevas son los patrones 13–18.
