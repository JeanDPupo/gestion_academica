# Spec 004 — Autenticación y perfiles

**Rama:** `spec/004-autenticacion-y-perfiles` · **Estado:** terminada · **Depende de:** 003

## Contexto

Estudiantes, profesores y coordinación inician sesión con correo y contraseña. El correo debe ser único entre los tres roles y el perfil es el dato más leído por usuario.

## Objetivo

Registro, login, logout y consulta de perfiles, con sesión en Redis y rate limiting del login.

## Patrones de acceso

| # | Patrón | Operación |
|---|--------|-----------|
| 1 | Perfil de un estudiante | `GetItem` `STUDENT#<id>` / `PROFILE` |
| 2 | Perfil de un profesor | `GetItem` `PROF#<id>` / `PROFILE` |
| 11 | Login por email, email único | `GetItem` `EMAIL#<email>` / `LOGIN`; `TransactWriteItems` al registrar |

## Endpoints

| Método | Ruta | Lambda |
|--------|------|--------|
| `POST` | `/auth/registro` | `auth` |
| `POST` | `/auth/login` | `auth` |
| `POST` | `/auth/logout` | `auth` |
| `GET` | `/auth/me` | `auth` |
| `GET` | `/estudiantes/{studentId}` | `usuarios` |
| `GET` | `/profesores/{profesorId}` | `usuarios` |

## Requisitos

- **R1.** Registrar crea perfil e ítem de email en una transacción; si el email o el id existen, no se escribe nada.
- **R2.** Un mismo email no puede pertenecer a dos roles.
- **R3.** La contraseña se guarda como hash PBKDF2 con sal.
- **R4.** El login responde igual ante email inexistente y contraseña incorrecta.
- **R5.** Cinco intentos por minuto y por email; el sexto responde `429`.
- **R6.** La sesión se guarda en Redis con TTL y el logout la elimina.
- **R7.** Crear una cuenta de coordinación exige sesión de coordinación.
- **R8.** Perfiles con Cache-Aside (15 min) y negative caching (30 s).
- **R9.** Un estudiante no ve el perfil de otro; profesores y coordinación sí.
- **R10.** Con Redis caído el login y los perfiles siguen funcionando.

## Criterios de aceptación

- [x] R1–R2: `test_email_duplicado_retorna_409_y_no_crea_el_segundo_perfil`, `test_mismo_email_no_puede_ser_estudiante_y_profesor`.
- [x] R4: `test_login_con_clave_incorrecta_o_email_inexistente_retorna_401`.
- [x] R5: `test_rate_limiting_bloquea_tras_cinco_intentos`.
- [x] R6: `test_login_correcto_abre_sesion_en_redis`, `test_logout_invalida_el_token`.
- [x] R7: `test_registrar_coordinacion_exige_sesion_de_coordinacion`.
- [x] R8: `test_perfil_estudiante_miss_y_luego_hit`, `test_id_inexistente_usa_negative_caching`.
- [x] R9: `test_estudiante_no_puede_ver_el_perfil_de_otro`.
- [x] R10: `test_login_funciona_con_redis_caido`, `test_perfil_se_sirve_con_redis_caido`.
