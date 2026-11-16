# Plan 006 — Matrículas

## Enfoque

Toda escritura es una transacción cuya primera lectura es consistente y cuyas condiciones repiten la validación dentro de DynamoDB. La lectura previa sirve para dar un buen mensaje de error; la condición es la que protege el dato.

## Archivos

| Archivo | Contenido |
|---------|-----------|
| `app/lambdas/matriculas/handler.py` | Los cinco endpoints |
| `app/lambdas/comun/dominio.py` | Lectura de oferta y matrícula, autorización sobre una oferta, invalidación |
| `app/infra/stack.py` | Fila de `matriculas` y sus rutas |
| `app/tests/test_matriculas.py` | Tests |

## Tareas

- [x] `dominio.leer_oferta` y `leer_matricula` con `ConsistentRead`.
- [x] Matricular: transacción de tres operaciones y traducción de `CancellationReasons` a `409` específicos.
- [x] Retirar: condiciones en el `Delete` y en la devolución del cupo.
- [x] Cambiar de grupo: validar curso y periodo; actualizar `GSI1PK`.
- [x] `dominio.invalidar_matricula`: horario (periodo y total), notas y lista de clase.
- [x] Ranking: `ZINCRBY` tras el commit y en el rechazo por cupo; `ZREVRANGE` para leer.
- [x] Invalidar y contar siempre **después** de confirmar la escritura.

## Decisiones

| Decisión | Alternativa descartada | Motivo |
|----------|------------------------|--------|
| El cupo se descuenta al solicitar | Descontarlo al aprobar | Una solicitud pendiente debe reservar su puesto; si no, se aprobarían más de las que caben |
| `ConditionCheck` del estudiante | Confiar en la lectura previa | La lectura y la escritura no son atómicas |
| El retiro borra el ítem | Estado `RETIRADA` | La llave quedaría ocupada (diseño §6) |
| La demanda vive solo en Redis | Contador en DynamoDB | Evita una escritura más en el camino crítico; el dato tolera pérdida |

## Riesgos

| Riesgo | Mitigación |
|--------|------------|
| Todas las matrículas de un grupo popular escriben el mismo ítem | Suficiente para el volumen de una universidad; fragmentar el contador si no (diseño §6) |
| La invalidación falla con Redis caído | Las claves expiran por TTL: horario 5 min, lista de clase 2 min |

## Verificación

`python -m pytest tests/test_matriculas.py -v`
