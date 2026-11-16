# Spec 005 — Cursos y ofertas

**Rama:** `spec/005-cursos-y-ofertas` · **Estado:** terminada · **Depende de:** 004

## Contexto

Coordinación publica la oferta académica: cursos y, por cada curso y periodo, uno o más grupos con profesor, horario y cupos. Es lo más leído del sistema durante la jornada de matrículas.

## Objetivo

Crear cursos y ofertas y consultarlos por curso, por periodo y por profesor, con caché.

## Patrones de acceso

| # | Patrón | Operación |
|---|--------|-----------|
| 6 | Curso y sus ofertas activas | `Query` por `PK = COURSE#<id>` |
| 7 | Catálogo del periodo | `Query` a `GSI2`: `PERIOD#<periodo>` + `begins_with OFFER#` |
| 8 | Ofertas de un profesor | `Query` a `GSI1`: `PROF#<id>` + `begins_with PERIOD#<periodo>#` |
| 17 | Crear curso | `PutItem` condicional |
| 18 | Crear oferta, abrir o cerrar | `PutItem` / `UpdateItem` condicional |

## Endpoints

| Método | Ruta |
|--------|------|
| `POST` | `/cursos` |
| `GET` | `/cursos/{cursoId}` |
| `POST` | `/cursos/{cursoId}/ofertas` |
| `GET` | `/periodos/{periodo}/ofertas` |
| `GET` | `/profesores/{profesorId}/ofertas` |
| `PUT` | `/ofertas/{ofertaId}/estado` |

## Requisitos

- **R1.** Solo coordinación crea cursos y ofertas y cambia su estado.
- **R2.** La oferta guarda las llaves de la tabla, de `GSI1` y de `GSI2`, y copia nombre del curso, créditos y nombre del profesor.
- **R3.** `ofertaId = <cursoId>-<periodo>-<grupo>`; crear una oferta repetida responde `409`.
- **R4.** El detalle del curso trae curso y ofertas activas en una sola Query.
- **R5.** El catálogo sale ordenado por curso y solo incluye el periodo pedido.
- **R6.** Un profesor solo ve sus propias ofertas.
- **R7.** Catálogo, detalle y ofertas del profesor se cachean con TTL corto (`TTL_CUPOS`, 15 s) porque incluyen `cuposDisponibles`.
- **R8.** Crear una oferta o cambiar su estado invalida esas tres claves.
- **R9.** Un curso inexistente usa negative caching.

## Criterios de aceptación

- [x] R1: `test_crear_curso_exige_coordinacion`, `test_cambiar_estado_valida_y_exige_coordinacion`.
- [x] R2: `test_crear_oferta_guarda_llaves_de_tabla_e_indices`.
- [x] R3: `test_crear_oferta_duplicada_retorna_409`.
- [x] R4: `test_detalle_curso_trae_curso_y_ofertas_en_una_respuesta`, `test_detalle_curso_excluye_ofertas_cerradas`.
- [x] R5: `test_catalogo_lista_solo_ofertas_del_periodo`.
- [x] R6: `test_profesor_no_ve_las_ofertas_de_otro`.
- [x] R7: `test_catalogo_cache_aside_con_ttl_corto`, `test_ttl_de_cupos_es_configurable`.
- [x] R8: `test_crear_oferta_invalida_el_catalogo`.
- [x] R9: `test_detalle_curso_inexistente_retorna_404_con_marca_negativa`.
