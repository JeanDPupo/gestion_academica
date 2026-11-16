# Guía de sustentación

Guion de la demo, lista de verificación previa y las preguntas que es probable que haga el docente, con la respuesta y el lugar del repo que la respalda.

Criterios de evaluación del enunciado: diseño NoSQL, implementación funcional, patrón de caché justificado y funcional, calidad del código y tests, y defensa oral.

## 1. Lista de verificación previa

El despliegue en LocalStack **no se ha ejecutado todavía en un equipo con Docker**. Todo lo demás está probado (ver el README). Esto hay que hacerlo antes del día de la sustentación, en el equipo que se va a usar:

- [ ] `docker compose up -d --build` termina con los cuatro contenedores arriba (`docker compose ps`).
- [ ] `docker compose exec cdk-dev python -m pytest tests/ -q` pasa completo.
- [ ] `docker compose exec cdk-dev bash scripts/desplegar.sh` termina con "Todas las llamadas respondieron lo esperado".
- [ ] http://localhost:8080 carga, muestra "DynamoDB ok" y "Redis ok", y se puede entrar con las cuentas de demo.
- [ ] En la traza de la página, la segunda lectura del catálogo aparece como `CACHÉ`.
- [ ] `docker compose stop redis`, recargar la página: sigue funcionando y la píldora dice "Redis caído". Luego `docker compose start redis`.
- [ ] Ensayar el guion completo una vez, con cronómetro.

Si algo falla, la sección 4 tiene los problemas más probables. Como respaldo está el modo simulación (`python scripts/servidor_local.py`), que muestra el mismo frontend y los mismos handlers sin Docker; si se usa, hay que decirlo.

## 2. Guion de la demo (10 a 12 minutos)

Dejar abiertas dos ventanas: el navegador en http://localhost:8080 y una terminal.

| # | Qué se hace | Qué se dice | Qué demuestra |
|---|-------------|-------------|---------------|
| 1 | Terminal: `python scripts/ver_tabla.py` dentro de `cdk-dev` | "Una sola tabla. Estudiantes, profesores, cursos, ofertas y matrículas conviven separados por el prefijo de la llave." | Single Table Design |
| 2 | `python scripts/ver_tabla.py COURSE#MAT101` | "El curso y sus grupos comparten partición: una Query trae todo." | Item collection, patrón 6 |
| 3 | Navegador, sin iniciar sesión: ranking de demanda | "Esto no está en DynamoDB. Es un Sorted Set de Redis que suma cada solicitud de matrícula." | Redis como contador |
| 4 | Entrar como **Daniel Rojas** → Catálogo. Cambiar de pestaña y volver | "Primera lectura: DynamoDB, por el GSI2. Segunda: caché. Miren la traza." | Cache-aside, patrón 7 |
| 5 | Matricular **Física Mecánica** | "Una transacción: crea la matrícula y descuenta el cupo, o no hace nada." | Patrón 10 |
| 6 | Matricular **Cálculo G1** (lleno) | "409. La condición `cuposDisponibles > 0` falló dentro de DynamoDB y no se escribió nada." | Transacción, cupo sin carreras |
| 7 | Matricular **Cálculo G2**, luego intentar **G1** otra vez | "Ya no deja: la llave de la matrícula es estudiante + periodo + curso, sin el grupo." | Unicidad por diseño de llave |
| 8 | Pestaña **Mi horario** → cambiar de grupo o retirar | "El grupo es un atributo. Cambiarlo mueve un cupo de una oferta a otra en una transacción de tres operaciones." | Patrones 13 y 14, invalidación |
| 9 | Salir. Entrar como **Luis Mendoza** → lista de clase de Cálculo G2 | "Mismo ítem de matrícula, visto desde el GSI1. El nombre del estudiante viene copiado: no hay N+1." | GSI invertido, desnormalización |
| 10 | Aprobar a Daniel y ponerle nota | "Al aprobar sale del índice de pendientes; al calificar entra al LSI de notas. Son índices dispersos." | Patrones 15 y 16 |
| 11 | Entrar como **Coordinación** → Pendientes | "Esta cola es el GSI2 con otro prefijo. Solo contiene lo pendiente." | GSI overloading, patrón 9 |
| 12 | Terminal: `docker compose stop redis`. Recargar y navegar | "Redis caído. Todo responde desde DynamoDB; solo se pierde el ranking." Después `docker compose start redis` | Modo degradado |
| 13 | Entrar como **Ana Pérez** → Mis notas | "De mayor a menor sin ordenar en código: el orden lo da la llave `GRADE#`." | LSI, patrón 4 |

Si el tiempo aprieta, los pasos que no se pueden saltar son 4, 6, 7, 9 y 12.

Comandos de apoyo para la terminal:

```bash
docker compose exec redis redis-cli KEYS '*'
docker compose exec redis redis-cli TTL catalogo:2026-1
docker compose exec redis redis-cli ZREVRANGE demanda:2026-1 0 -1 WITHSCORES
docker compose exec cdk-dev python scripts/ver_tabla.py --indice GSI2
```

## 3. Preguntas probables

### Diseño NoSQL

**¿Por qué una sola tabla y no una por entidad?**
Porque se diseñó desde las consultas. El curso con sus ofertas y el estudiante con sus matrículas se leen juntos, así que viven en la misma partición y salen en una Query. Con una tabla por entidad habría que hacer varias lecturas y unirlas en código. → Diseño §4.1.

**¿Cómo garantizan que un estudiante no quede en dos grupos del mismo curso?**
Con la llave. La SK de la matrícula es `ENROLL#<periodo>#<cursoId>` y el grupo es un atributo. Un segundo `Put` con `attribute_not_exists(PK)` falla aunque sea a otro grupo. No hay validación en código que se pueda saltar. → `matriculas/handler.py`, `test_no_se_puede_matricular_dos_veces_el_mismo_curso`.

**¿Qué pasa si dos estudiantes piden el último cupo al mismo tiempo?**
Los dos llegan a la transacción, pero la condición `cuposDisponibles > 0` se evalúa de forma atómica en DynamoDB. Uno escribe; al otro se le cancela la transacción completa y recibe `409`. → Diseño §5.1.

**¿Por qué GSI y no LSI para la lista de clase? ¿Y por qué LSI para las notas?**
El LSI comparte la partición de la tabla: sirve para reordenar lo que ya está en la misma PK. Las notas son del mismo estudiante, solo cambia el orden → LSI. La lista de clase agrupa matrículas de muchos estudiantes, o sea otra partición → GSI. → Diseño §4.2 y §4.3.

**¿Qué es un índice disperso y dónde lo usan?**
Un ítem solo entra a un índice si tiene los atributos de la llave de ese índice. Las pendientes tienen `GSI2PK`/`GSI2SK`; al aprobar se eliminan y el ítem sale del índice. Igual con `LSI1SK`, que solo existe si hay nota. El índice queda pequeño y la Query lee exactamente lo que devuelve. → `evaluacion/handler.py`.

**¿Qué es GSI overloading?**
Usar atributos genéricos (`GSI1PK`, `GSI1SK`) con valores distintos según el tipo de ítem. `GSI1` sirve para "ofertas de un profesor" (`PROF#…`) y para "estudiantes de una oferta" (`OFFER#…`). Dos índices cubren cinco patrones. → Diseño §4.3.

**¿Usan Scan en algún lado?**
Ninguna Lambda. Solo `scripts/ver_tabla.py`, que es una herramienta para mostrar la tabla. `db.py` ni siquiera expone `Scan`.

**¿Por qué desnormalizan? ¿Y si cambia el nombre del curso?**
DynamoDB no tiene joins. La matrícula copia nombre del curso, créditos, horario y nombre del estudiante para que el horario y la lista de clase salgan de una Query. Es una foto del momento de matricular, que es lo correcto para un registro académico. → Diseño §6.

**¿Cuándo usan transacciones y cuándo no?**
Solo cuando dos ítems deben cambiar juntos: matricular, retirar, cambiar de grupo y registrar. Aprobar y calificar tocan un solo ítem: `UpdateItem` con condición. Una transacción cuesta el doble de capacidad. → Diseño §6.

**¿Dónde hay consistencia eventual y por qué es aceptable?**
En los GSI: la lista de clase, el catálogo y la cola de pendientes pueden tardar un instante en reflejar una escritura. Las decisiones (cupo, duplicados, permisos) usan la tabla con lectura consistente o una condición de escritura. → Diseño §6.

**¿Hay hot partitions?**
Dos puntos identificados y no resueltos, porque para el volumen de una universidad no hace falta: el ítem de una oferta muy pedida (todas las matrículas actualizan su contador) y la partición `PERIOD#<periodo>` de `GSI2`. La salida sería fragmentar el contador y particionar la llave del periodo. → Diseño §6.

### Redis

**¿Qué patrón de caché usan y por qué ese?**
Cache-aside. La aplicación busca en Redis; si no está, lee DynamoDB y guarda con TTL. Es el único que tolera la caída de Redis sin cambios: si falla, se lee de DynamoDB. → `comun/cache.py`, `cache_aside`.

**¿Por qué borran la clave en vez de actualizarla?**
Si dos escrituras concurrentes actualizan la caché, puede quedar el valor de la que terminó primero. Borrar es seguro: la siguiente lectura repuebla desde la fuente de verdad. → Diseño §7.

**El cupo que muestra el catálogo, ¿es real?**
Puede ir hasta 15 segundos atrasado. Se prefirió un TTL corto a invalidar en cada matrícula, porque en la jornada de inscripciones la clave más leída se borraría sin parar. Ese atraso no produce sobrecupo: decide la transacción. → Diseño §7, "El cupo y el catálogo".

**¿Qué pasa si Redis se cae?**
Las lecturas salen de DynamoDB, las escrituras funcionan, el login entra sin rate limiting y el ranking responde "no disponible". Hay timeout de 0.5 s y un circuit breaker de 15 s para no pagar el timeout en cada operación. Se puede mostrar en vivo. → Diseño §7.

**Si las sesiones están en Redis, ¿cómo entra alguien con Redis caído?**
El token va firmado y lleva su expiración, así que se puede validar sin Redis. Redis guarda la sesión para poder cerrarla (logout). Con Redis caído se valida solo la firma. → `comun/seguridad.py`.

**¿Qué es el negative caching?**
Cachear que algo no existe. Sin eso, pedir un id inventado golpearía DynamoDB cada vez. La marca dura 30 s y se borra si el recurso se crea. → `test_id_inexistente_usa_negative_caching`.

**¿Por qué el ranking no está en DynamoDB?**
Es una métrica que tolera pérdida y que se actualiza en cada solicitud. Ponerla en DynamoDB sería una escritura más en el camino crítico de la matrícula. El Sorted Set da el ranking ordenado con un comando.

**¿Qué otras estructuras de Redis usan además de String?**
String con TTL (caché y sesiones), contador con `INCR` + `EXPIRE` (rate limiting) y Sorted Set con `ZINCRBY` / `ZREVRANGE` (ranking).

### Implementación

**¿Por qué varias Lambdas y no una?**
Una por dominio. Permite mínimo privilegio (`usuarios` y `health` solo leen la tabla) y que un cambio en matrículas no redespliegue el login. El código común va empaquetado en cada una. → `infra/stack.py`.

**¿Cómo se agrega un endpoint?**
Una fila en `RUTAS` y una función con `@rutas.ruta`. Un test compara las dos listas. → `tests/test_rutas.py`.

**¿Cómo prueban sin AWS?**
`moto` simula DynamoDB con la misma tabla e índices, y `fakeredis` simula Redis. Los tests invocan los handlers con eventos iguales a los de API Gateway. 146 tests, incluyendo los casos con Redis caído.

**¿Cómo guardan las contraseñas?**
Hash PBKDF2-HMAC-SHA256 con sal aleatoria por usuario. El login responde lo mismo si el correo no existe o la clave es incorrecta.

## 4. Si algo falla en el equipo de la demo

| Síntoma | Causa probable | Qué hacer |
|---------|----------------|-----------|
| El contenedor `emulador` se cae al arrancar | Imagen distinta de `localstack/localstack:4.14` (las posteriores piden token) | Revisar la línea `image:` de `docker-compose.yml` |
| `cdklocal deploy` falla tras reiniciar el emulador | LocalStack no guarda estado: falta el bootstrap | `bash scripts/desplegar.sh`, que lo incluye |
| `GET /health` dice Redis en error desde las Lambdas | La red de las Lambdas no es la de Compose | `docker network ls` debe mostrar `gestion_academica_default`; debe coincidir con `LAMBDA_DOCKER_NETWORK` |
| La página no conecta con el API | `config.js` viejo: el `api-id` cambió | `python scripts/seed.py` de nuevo, recargar con Ctrl+F5 |
| El navegador bloquea las peticiones por CORS | El preflight `OPTIONS` no llega a la Lambda | Probar `curl -i -X OPTIONS <ApiUrl>matriculas`; si no responde 204, usar la URL con `localhost` (opción B del README del docente) en `config.js` |
| La primera petición tarda varios segundos | Arranque en frío de la Lambda en el emulador | Hacer un recorrido de calentamiento antes de presentar |
| Puerto 4566, 6379 u 8080 ocupado | Otro servicio en la máquina | Cambiar el puerto en `.env` (ver `.env.example`) |

## 5. Reparto sugerido

Cinco bloques, uno por integrante. Cada uno defiende lo suyo y maneja su parte de la demo.

| Bloque | Tema | Pasos del guion | Material |
|--------|------|-----------------|----------|
| 1 | Problema, alcance y patrones de acceso | 1 y 2 | Diseño §1 y §2 |
| 2 | Modelo de tabla, llaves e índices | 9, 11 y 13 | Diseño §3 y §4 |
| 3 | Transacciones y reglas de negocio | 5 a 8 | Diseño §5, `matriculas/handler.py` |
| 4 | Redis: patrones y modo degradado | 3, 4 y 12 | Diseño §7, `comun/cache.py` |
| 5 | Infraestructura, tests y cierre | 10 | `infra/stack.py`, `tests/`, revisión del diseño |
