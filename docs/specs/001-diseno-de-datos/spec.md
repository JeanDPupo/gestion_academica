# Spec 001 — Diseño de datos

**Rama:** `spec/001-diseno-de-datos` · **Estado:** terminada · **Depende de:** —

## Contexto

El equipo tenía un documento de diseño (v1) con los patrones de acceso, el modelo de tabla y los patrones de Redis. Antes de escribir código hay que confirmar que ese diseño alcanza para implementar cada flujo y que cumple el enunciado del proyecto final.

## Objetivo

Dejar en el repositorio el documento de diseño que el código va a implementar, y un registro de qué se cambió frente a la v1 y por qué.

## Alcance

Incluye:
- Documento de diseño v2: patrones de acceso (lecturas y escrituras), modelo de tabla, explicación de llaves, flujos, decisiones y patrones de Redis.
- Documento de revisión: qué se mantuvo, qué se cambió y los hallazgos sobre el proyecto base.

No incluye: código.

## Requisitos

- **R1.** Cada patrón de acceso indica PK, SK, índice y el endpoint que lo expone.
- **R2.** Ningún patrón usa `Scan`.
- **R3.** Cada escritura que toca más de un ítem define sus operaciones y sus condiciones.
- **R4.** Cada dato cacheado indica clave, patrón, TTL y cuándo se invalida.
- **R5.** Queda definido el comportamiento del sistema cuando Redis no está disponible.
- **R6.** Los cambios frente a la v1 están justificados uno por uno.

## Criterios de aceptación

- [x] El documento cubre los cuatro puntos del entregable 1 del enunciado: patrones de acceso, modelo de tabla, justificación del patrón de caché.
- [x] Todo flujo de escritura del sistema tiene su sección en el documento (§5).
- [x] La revisión enumera cada cambio con problema, consecuencia y corrección.

## Entregables

- `docs/diseno-dynamodb-gestion-academica.md`
- `docs/revision-diseno.md`
