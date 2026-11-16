# Spec 009 — Documentación final

**Rama:** `spec/009-documentacion-final` · **Estado:** terminada · **Depende de:** 008

## Contexto

El repositorio lo va a leer el docente para calificar y el equipo para preparar la sustentación. Ninguno de los dos estuvo en cada decisión.

## Objetivo

Que alguien que clona el repo pueda levantarlo, entender qué hace cada pieza y defenderlo.

## Requisitos

- **R1.** El README explica qué es, cómo se levanta y dónde está cada cosa, en ese orden.
- **R2.** La referencia del API lista todos los endpoints con acceso, operación de DynamoDB y uso de Redis.
- **R3.** La guía de sustentación tiene el guion de la demo, la lista de verificación previa y las preguntas probables con su respuesta.
- **R4.** Queda escrito qué se verificó y qué no.
- **R5.** El flujo de trabajo (spec → plan → rama → merge) queda documentado para las próximas entregas.

## Criterios de aceptación

- [x] Todas las rutas de `infra/stack.py` aparecen en `docs/api.md`.
- [x] Todos los comandos del README existen en el repo.
- [x] El índice de specs lista las nueve con su rama.

## Entregables

- `README.md`
- `docs/api.md`
- `docs/guia-sustentacion.md`
- `docs/specs/README.md`
