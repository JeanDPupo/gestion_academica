# Specs y planes

Cada entrega del proyecto tiene una **spec** (qué se construye y cómo se sabe que está bien) y un **plan** (cómo se construye), y se desarrolló en su propia rama.

| # | Spec | Rama | Qué entrega |
|---|------|------|-------------|
| 001 | [Diseño de datos](001-diseno-de-datos/spec.md) | `spec/001-diseno-de-datos` | Documento de diseño v2 y revisión de la v1 |
| 002 | [Módulo común](002-modulo-comun/spec.md) | `spec/002-modulo-comun` | Llaves, acceso a DynamoDB, caché, HTTP y seguridad |
| 003 | [Infraestructura base](003-infraestructura-base/spec.md) | `spec/003-infraestructura-base` | Docker Compose, stack CDK con la tabla y sus índices, health |
| 004 | [Autenticación y perfiles](004-autenticacion-y-perfiles/spec.md) | `spec/004-autenticacion-y-perfiles` | 6 endpoints: registro, login, logout, perfiles |
| 005 | [Cursos y ofertas](005-cursos-y-ofertas/spec.md) | `spec/005-cursos-y-ofertas` | 6 endpoints: cursos, ofertas, catálogo |
| 006 | [Matrículas](006-matriculas/spec.md) | `spec/006-matriculas` | 5 endpoints: matricular, horario, retirar, cambiar de grupo, demanda |
| 007 | [Aprobación y notas](007-aprobacion-y-notas/spec.md) | `spec/007-aprobacion-y-notas` | 5 endpoints: lista de clase, pendientes, aprobar, calificar, notas |
| 008 | [Demo](008-demo/spec.md) | `spec/008-demo` | Datos iniciales, frontend y modo simulación |
| 009 | [Documentación final](009-documentacion-final/spec.md) | `spec/009-documentacion-final` | README, referencia del API y guía de sustentación |

## Flujo de trabajo

1. **Spec.** Se crea `docs/specs/NNN-nombre/spec.md` con contexto, objetivo, alcance, requisitos numerados y criterios de aceptación verificables. Cada criterio apunta al test que lo comprueba.
2. **Plan.** `plan.md` en la misma carpeta: enfoque, archivos que se tocan, tareas, decisiones con la alternativa descartada, riesgos y cómo se verifica.
3. **Rama.** `git switch -c spec/NNN-nombre` desde `main`. El primer commit de la rama es la spec y el plan; los siguientes, la implementación y sus tests.
4. **Verificación.** `python -m pytest tests/ -q` pasa completo en la rama antes de integrarla.
5. **Integración.** Merge a `main` con `--no-ff`, para que el historial conserve qué commits pertenecen a cada spec.

Mensajes de commit: `tipo(spec-NNN): descripción`, con `docs`, `feat`, `test` o `chore`.

## Para una spec nueva

Copiar la estructura de una existente. Lo mínimo que debe tener:

- **Spec:** requisitos numerados (`R1`, `R2`…) y, por cada uno, un criterio de aceptación que se pueda marcar como cumplido o no.
- **Plan:** las tareas y, por cada decisión que no sea obvia, qué alternativa se descartó y por qué.

Si la spec agrega endpoints: una fila por endpoint en `RUTAS` (`app/infra/stack.py`), su función en el handler y su fila en `docs/api.md`.
