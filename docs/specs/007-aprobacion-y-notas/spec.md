# Spec 007 — Aprobación y notas

**Rama:** `spec/007-aprobacion-y-notas` · **Estado:** terminada · **Depende de:** 006

## Contexto

Después de solicitada, una matrícula la aprueba el profesor o coordinación, aparece en la lista de clase y al final recibe una nota. Aquí se usan los tres índices: `GSI1` para la lista de clase, `GSI2` para la cola de pendientes y `LSI1` para las notas.

## Objetivo

Lista de clase, cola de pendientes, aprobación, calificación y consulta de notas, con autorización por oferta.

## Patrones de acceso

| # | Patrón | Operación |
|---|--------|-----------|
| 4 | Matrículas por nota | `Query` a `LSI1`, `ScanIndexForward=false` |
| 5, 12 | Estudiantes de una oferta | `GetItem` de la oferta + `Query` a `GSI1`: `OFFER#<ofertaId>` |
| 9 | Pendientes del periodo | `Query` a `GSI2`: `PERIOD#<periodo>` + `begins_with PENDING#` |
| 15 | Aprobar | `UpdateItem` condicional, `REMOVE GSI2PK, GSI2SK` |
| 16 | Calificar | `UpdateItem` condicional, `SET nota, LSI1SK` |

## Endpoints

| Método | Ruta |
|--------|------|
| `GET` | `/ofertas/{ofertaId}/estudiantes` |
| `GET` | `/periodos/{periodo}/matriculas/pendientes` |
| `POST` | `/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/aprobar` |
| `PUT` | `/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/nota` |
| `GET` | `/estudiantes/{studentId}/notas` |

## Requisitos

- **R1.** Solo el profesor de la oferta o coordinación ven la lista de clase, aprueban y califican.
- **R2.** La autorización lee la oferta de DynamoDB con lectura consistente; no usa la caché.
- **R3.** La lista de clase sale de una Query, sin leer perfiles.
- **R4.** Solo se aprueba una matrícula `PENDIENTE`; al aprobarla sale de `GSI2`.
- **R5.** Solo se califica una matrícula `APROBADA`; la nota va de 0.0 a 5.0.
- **R6.** Calificar escribe `LSI1SK`; recalificar lo reescribe.
- **R7.** Las notas salen de mayor a menor, con promedio ponderado por créditos.
- **R8.** La cola de pendientes va en orden de solicitud y no se cachea.
- **R9.** Lista de clase (2 min) y notas (5 min) con Cache-Aside e invalidación.
- **R10.** Una matrícula calificada no se retira ni cambia de grupo.

## Criterios de aceptación

- [x] R1: `test_solo_el_profesor_de_la_oferta_o_coordinacion_ven_la_lista`, `test_aprobar_exige_ser_el_profesor_de_la_oferta`, `test_calificar_exige_ser_el_profesor_de_la_oferta`.
- [x] R2: `test_la_autorizacion_no_depende_de_la_cache`.
- [x] R3: `test_lista_de_clase_sale_del_gsi1_sin_consultar_perfiles`.
- [x] R4: `test_aprobar_saca_la_matricula_del_indice_de_pendientes`, `test_aprobar_dos_veces_retorna_409`.
- [x] R5: `test_no_se_califica_una_matricula_pendiente`, `test_calificar_valida_el_rango_de_la_nota`.
- [x] R6: `test_calificar_guarda_la_nota_y_la_llave_del_lsi`, `test_recalificar_actualiza_la_posicion_en_el_lsi`.
- [x] R7: `test_notas_ordenadas_de_mayor_a_menor_con_promedio_ponderado`.
- [x] R8: `test_pendientes_del_periodo_en_orden_de_solicitud`.
- [x] R9: `test_lista_de_clase_se_invalida_al_matricular_y_al_retirar`, `test_notas_se_cachean_y_se_invalidan_al_calificar`.
- [x] R10: `test_matricula_calificada_no_se_retira_ni_cambia_de_grupo`.
