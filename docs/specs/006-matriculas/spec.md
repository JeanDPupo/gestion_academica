# Spec 006 — Matrículas

**Rama:** `spec/006-matriculas` · **Estado:** terminada · **Depende de:** 005

## Contexto

Es el núcleo del sistema y donde están las reglas que no pueden fallar: no pasarse del cupo y no matricular dos veces el mismo curso. Varios estudiantes compiten por los mismos cupos al mismo tiempo.

## Objetivo

Matricular, consultar el horario, retirar y cambiar de grupo, con las reglas garantizadas por DynamoDB.

## Patrones de acceso

| # | Patrón | Operación |
|---|--------|-----------|
| 3 | Matrículas de un estudiante en un periodo | `Query` `STUDENT#<id>` + `begins_with ENROLL#<periodo>#` |
| 10 | Matricular validando cupo y duplicados | `TransactWriteItems`: Put + Update + ConditionCheck |
| 13 | Retirar devolviendo el cupo | `TransactWriteItems`: Delete + Update |
| 14 | Cambiar de grupo | `TransactWriteItems`: 3 Update |

## Endpoints

| Método | Ruta |
|--------|------|
| `POST` | `/matriculas` |
| `GET` | `/estudiantes/{studentId}/matriculas` |
| `DELETE` | `/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}` |
| `PUT` | `/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/grupo` |
| `GET` | `/periodos/{periodo}/demanda` |

## Requisitos

- **R1.** Una matrícula por estudiante, curso y periodo, sin importar el grupo.
- **R2.** `cuposDisponibles` nunca baja de 0 ni supera `cuposTotales`.
- **R3.** Si falla una condición no se escribe nada (ni matrícula ni cupo).
- **R4.** Una oferta cerrada no admite matrículas.
- **R5.** El estudiante se matricula a sí mismo; coordinación puede matricular a cualquiera.
- **R6.** La matrícula copia curso, créditos, horario, profesor y nombre del estudiante.
- **R7.** Nace `PENDIENTE` y en `GSI2` si la oferta requiere aprobación; si no, `APROBADA` y fuera de `GSI2`.
- **R8.** Retirar libera la llave: el estudiante puede volver a matricular el curso.
- **R9.** Cambiar de grupo conserva la matrícula y mueve un cupo de una oferta a la otra; solo dentro del mismo curso y periodo.
- **R10.** El horario se cachea 5 min y se invalida con cada escritura sobre la matrícula.
- **R11.** Cada solicitud válida suma a la demanda del curso (Sorted Set), haya cupo o no.
- **R12.** Con Redis caído, matricular funciona.

## Criterios de aceptación

- [x] R1: `test_no_se_puede_matricular_dos_veces_el_mismo_curso`.
- [x] R2–R3: `test_sin_cupo_retorna_409_y_no_crea_la_matricula`, `test_retirar_matricula_inexistente_no_infla_los_cupos`.
- [x] R4: `test_oferta_cerrada_no_admite_matriculas`.
- [x] R5: `test_estudiante_siempre_se_matricula_a_si_mismo`, `test_coordinacion_matricula_a_un_estudiante`.
- [x] R6–R7: `test_matricular_crea_la_matricula_y_descuenta_el_cupo`, `test_oferta_sin_aprobacion_nace_aprobada_y_fuera_de_gsi2`.
- [x] R8: `test_tras_retirar_se_puede_volver_a_matricular`.
- [x] R9: `test_cambiar_de_grupo_mueve_cupos_y_actualiza_gsi1`, `test_cambiar_a_grupo_sin_cupo_no_modifica_nada`.
- [x] R10: `test_horario_se_cachea_y_se_invalida_al_matricular`.
- [x] R11: `test_ranking_de_demanda_cuenta_solicitudes_incluso_sin_cupo`.
- [x] R12: `test_matricular_funciona_con_redis_caido`.
