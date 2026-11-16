# Referencia del API

23 endpoints en 6 Lambdas. La tabla de rutas vive en `app/infra/stack.py` (`RUTAS`); el test `tests/test_rutas.py` verifica que coincide con lo que cada handler registra.

## Convenciones

- **URL base:** la imprime `cdklocal deploy` (`ApiUrl`) y `scripts/seed.py` la escribe en `frontend/config.js`. Con `localhost`: `http://localhost:4566/restapis/<api-id>/prod/_user_request_`.
- **Autenticación:** `Authorization: Bearer <token>`. El token lo entrega `POST /auth/login`.
- **Cuerpos:** JSON, con `Content-Type: application/json`.
- **`_fuente`:** las lecturas indican de dónde salió la respuesta: `"cache"` (Redis) o `"dynamodb"`. El ranking de demanda responde `"redis"`.
- **Errores:** `{"error": "<mensaje>"}` con el código HTTP correspondiente.

| Código | Significado |
|--------|-------------|
| `400` | Datos inválidos o mal formados |
| `401` | Falta el token, es inválido, expiró o la sesión fue cerrada |
| `403` | El rol o el usuario no tienen permiso sobre ese recurso |
| `404` | El recurso no existe |
| `409` | Conflicto con el estado actual: duplicado, sin cupo, ya aprobada… |
| `429` | Demasiados intentos de login |

Roles: **E** estudiante, **P** profesor, **C** coordinación. "Dueño" = el usuario al que pertenece el recurso.

## Endpoints

### Servicio

| Método | Ruta | Acceso | Qué hace | DynamoDB | Redis |
|--------|------|--------|----------|----------|-------|
| `GET` | `/health` | Público | Estado de DynamoDB y Redis. `200` ok o degradado, `503` si falla DynamoDB | `DescribeTable` | `PING` |

### Autenticación — Lambda `auth`

| Método | Ruta | Acceso | Qué hace | DynamoDB | Redis |
|--------|------|--------|----------|----------|-------|
| `POST` | `/auth/registro` | Público (rol `ADMIN`: solo C) | Crea el usuario con email único | `TransactWriteItems`: 2 Put condicionales (perfil + `EMAIL#`) | Borra la marca negativa del perfil |
| `POST` | `/auth/login` | Público | Valida credenciales y abre sesión | `GetItem` consistente de `EMAIL#<email>` | Rate limiting (`INCR`), sesión (`SET … EX`), perfil cache-aside |
| `POST` | `/auth/logout` | Autenticado | Cierra la sesión | - | `DEL sesion:<jti>` |
| `GET` | `/auth/me` | Autenticado | Perfil del usuario de la sesión | `GetItem` (si miss) | Cache-aside `perfil:<rol>:<id>` |

### Perfiles — Lambda `usuarios`

| Método | Ruta | Acceso | Qué hace | DynamoDB | Redis |
|--------|------|--------|----------|----------|-------|
| `GET` | `/estudiantes/{studentId}` | Dueño, P, C | Perfil del estudiante (patrón 1) | `GetItem` (si miss) | Cache-aside 15 min + negative caching 30 s |
| `GET` | `/profesores/{profesorId}` | Autenticado | Perfil del profesor (patrón 2) | `GetItem` (si miss) | Cache-aside 15 min + negative caching 30 s |

### Cursos y ofertas — Lambda `cursos`

| Método | Ruta | Acceso | Qué hace | DynamoDB | Redis |
|--------|------|--------|----------|----------|-------|
| `POST` | `/cursos` | C | Crea un curso | `PutItem` condicional | Borra `curso:<id>` |
| `GET` | `/cursos/{cursoId}` | Público | Curso y sus ofertas activas (patrón 6) | `Query` por PK | Cache-aside 15 s + negative caching |
| `POST` | `/cursos/{cursoId}/ofertas` | C | Crea una oferta (grupo) | 2 `GetItem` + `PutItem` condicional | Invalida catálogo, curso y ofertas del profesor |
| `GET` | `/periodos/{periodo}/ofertas` | Público | Catálogo del periodo (patrón 7) | `Query` a `GSI2` | Cache-aside 15 s |
| `GET` | `/profesores/{profesorId}/ofertas` | Dueño, C | Ofertas que dicta (patrón 8). `?periodo=` opcional | `Query` a `GSI1` | Cache-aside 15 s |
| `PUT` | `/ofertas/{ofertaId}/estado` | C | Abre o cierra una oferta | `UpdateItem` condicional | Invalida catálogo, curso y ofertas del profesor |

### Matrículas — Lambda `matriculas`

| Método | Ruta | Acceso | Qué hace | DynamoDB | Redis |
|--------|------|--------|----------|----------|-------|
| `POST` | `/matriculas` | E (a sí mismo), C | Matricula validando cupo y duplicados (patrón 10) | 2 `GetItem` + `TransactWriteItems` (Put, Update, ConditionCheck) | `ZINCRBY demanda`, invalida horario, notas y lista de clase |
| `GET` | `/estudiantes/{studentId}/matriculas` | Dueño, C | Horario del periodo o historial (patrón 3). `?periodo=` opcional | `Query` por PK + `begins_with` | Cache-aside 5 min |
| `DELETE` | `/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}` | Dueño, P de la oferta, C | Retira o rechaza y devuelve el cupo (patrón 13) | `GetItem` + `TransactWriteItems` (Delete, Update) | Invalida horario, notas y lista de clase |
| `PUT` | `/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/grupo` | Dueño, C | Cambia de grupo (patrón 14) | 2 `GetItem` + `TransactWriteItems` (3 Update) | Invalida horario y las dos listas de clase |
| `GET` | `/periodos/{periodo}/demanda` | Público | Cursos más solicitados. `?top=` (1–50, por defecto 5) | - | `ZREVRANGE … WITHSCORES` |

### Aprobación y notas — Lambda `evaluacion`

| Método | Ruta | Acceso | Qué hace | DynamoDB | Redis |
|--------|------|--------|----------|----------|-------|
| `GET` | `/ofertas/{ofertaId}/estudiantes` | P de la oferta, C | Lista de clase (patrones 5 y 12) | `GetItem` consistente + `Query` a `GSI1` | Cache-aside 2 min |
| `GET` | `/periodos/{periodo}/matriculas/pendientes` | C | Cola de pendientes en orden de solicitud (patrón 9) | `Query` a `GSI2` | No se cachea |
| `POST` | `/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/aprobar` | P de la oferta, C | Aprueba una matrícula pendiente (patrón 15) | 2 `GetItem` + `UpdateItem` condicional | Invalida horario, notas y lista de clase |
| `PUT` | `/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/nota` | P de la oferta, C | Califica una matrícula aprobada (patrón 16) | 2 `GetItem` + `UpdateItem` condicional | Invalida horario, notas y lista de clase |
| `GET` | `/estudiantes/{studentId}/notas` | Dueño, C | Notas de mayor a menor y promedio ponderado (patrón 4) | `Query` a `LSI1` | Cache-aside 5 min |

## Cuerpos de las peticiones

| Endpoint | Cuerpo |
|----------|--------|
| `POST /auth/registro` | `{"rol": "STUDENT"\|"PROFESSOR"\|"ADMIN", "id"?, "nombre", "email", "password" (mín. 8), "programa"\|"departamento"\|"dependencia"?}` |
| `POST /auth/login` | `{"email", "password"}` |
| `POST /cursos` | `{"cursoId", "nombre", "creditos"}` |
| `POST /cursos/{cursoId}/ofertas` | `{"periodo", "grupo", "profesorId", "horario", "cupos", "requiereAprobacion"?}` |
| `PUT /ofertas/{ofertaId}/estado` | `{"estado": "ACTIVA"\|"CERRADA"}` |
| `POST /matriculas` | `{"ofertaId"}` — coordinación agrega `"studentId"` |
| `PUT …/grupo` | `{"ofertaId"}` (la oferta nueva) |
| `PUT …/nota` | `{"nota"}` (0.0 a 5.0) |

## Recorrido con curl

`B` es la URL base. Las cuentas son las que crea `scripts/seed.py` (contraseña `Demo2026*`).

```bash
B=http://localhost:4566/restapis/<api-id>/prod/_user_request_

# Salud del servicio
curl $B/health

# Catálogo: la primera lectura responde "_fuente": "dynamodb", la segunda "cache"
curl $B/periodos/2026-1/ofertas
curl $B/periodos/2026-1/ofertas

# Login de un estudiante sin matrículas
TOKEN=$(curl -s -X POST $B/auth/login -H "Content-Type: application/json" \
  -d '{"email":"daniel.rojas@campus.example","password":"Demo2026*"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# Matricular en un grupo con cupo → 201
curl -X POST $B/matriculas -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"ofertaId":"FIS201-2026-1-G1"}'

# Repetir la matrícula → 409 (la llave no incluye el grupo)
curl -X POST $B/matriculas -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"ofertaId":"FIS201-2026-1-G1"}'

# Grupo lleno → 409, la transacción no escribe nada
curl -X POST $B/matriculas -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"ofertaId":"MAT101-2026-1-G1"}'

# Horario del estudiante
curl "$B/estudiantes/2021114006/matriculas?periodo=2026-1" -H "Authorization: Bearer $TOKEN"

# Ranking de demanda (Sorted Set en Redis)
curl $B/periodos/2026-1/demanda

# Cerrar sesión: el mismo token deja de servir → 401
curl -X POST $B/auth/logout -H "Authorization: Bearer $TOKEN"
curl $B/auth/me -H "Authorization: Bearer $TOKEN"
```

Ver las claves en Redis y la tabla:

```bash
docker compose exec redis redis-cli KEYS '*'
docker compose exec redis redis-cli ZREVRANGE demanda:2026-1 0 -1 WITHSCORES
docker compose exec cdk-dev python scripts/ver_tabla.py STUDENT#2021114006
docker compose exec cdk-dev python scripts/ver_tabla.py --indice GSI2
```
