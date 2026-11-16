# Plan 004 — Autenticación y perfiles

## Enfoque

Dos Lambdas: `auth` escribe (registro) y maneja sesiones; `usuarios` solo lee perfiles y recibe permiso de solo lectura sobre la tabla.

## Archivos

| Archivo | Contenido |
|---------|-----------|
| `app/lambdas/auth/handler.py` | Registro, login, logout, `/auth/me`, `construir_usuario` |
| `app/lambdas/usuarios/handler.py` | Perfiles de estudiante y profesor |
| `app/infra/stack.py` | Filas de `auth` y `usuarios` en `LAMBDAS` y `RUTAS` |
| `app/tests/test_auth.py`, `test_usuarios.py` | Tests de ambos handlers |

## Tareas

- [x] `construir_usuario`: arma perfil + ítem de email (la reutiliza el seed de la spec 008).
- [x] Registro con dos `Put` condicionales en una transacción; distinguir email duplicado de id duplicado por el índice de la operación que falló.
- [x] Login: rate limiting → `GetItem` consistente → verificación → token → sesión en Redis.
- [x] Reiniciar el contador de intentos en un login exitoso.
- [x] Borrar la marca negativa del perfil al registrar.
- [x] Perfiles con `cache_aside` y reglas de acceso.

## Decisiones

| Decisión | Motivo |
|----------|--------|
| `GetItem` consistente en el login | Una cuenta recién creada debe poder entrar de inmediato |
| Rate limiting con fail-open | Si Redis cae se prefiere dejar entrar que tumbar el login |
| La primera cuenta de coordinación se siembra por script | Evita un endpoint de arranque sin autenticación |

## Verificación

`python -m pytest tests/test_auth.py tests/test_usuarios.py -v`
