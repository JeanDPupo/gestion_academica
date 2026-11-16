"""
Lambda /auth
────────────
Registro, inicio y cierre de sesión para los tres roles.

Rutas soportadas:
  POST /auth/registro   → Crea el usuario con email único (transacción)
  POST /auth/login      → Valida credenciales y abre sesión en Redis
  POST /auth/logout     → Cierra la sesión (borra la clave en Redis)
  GET  /auth/me         → Perfil del usuario autenticado (Cache-Aside)

Modelo de datos (Single Table Design):
  Perfil   PK = STUDENT#<id> | PROF#<id> | ADMIN#<id>    SK = PROFILE
  Email    PK = EMAIL#<email normalizado>                SK = LOGIN

El ítem EMAIL# cumple dos funciones: garantiza que un correo pertenezca
a un solo usuario (un GSI no puede garantizar unicidad) y permite el
login con un GetItem, sin índices.

Redis:
  sesion:<jti>             almacén principal de sesiones (TTL)
  limite:login:<email>     rate limiting de intentos de login
  perfil:<rol>:<id>        Cache-Aside del perfil
"""
import logging
import uuid
from typing import Any

from comun import cache, claves, db, seguridad
from comun.http import (
    Enrutador, ErrorApi, Evento, RespuestaApi, leer_json, respuesta, texto,
)

logger: logging.Logger = logging.getLogger()
logger.setLevel(logging.INFO)

rutas: Enrutador = Enrutador()

TTL_PERFIL: int = 900          # 15 min: se lee mucho y casi no cambia
INTENTOS_LOGIN: int = 5        # intentos permitidos por ventana
VENTANA_LOGIN: int = 60        # segundos

# Atributo propio de cada rol en el perfil
_CAMPO_ROL: dict[str, str] = {
    claves.ROL_ESTUDIANTE: "programa",
    claves.ROL_PROFESOR: "departamento",
    claves.ROL_ADMIN: "dependencia",
}
_ID_ROL: dict[str, str] = {
    claves.ROL_ESTUDIANTE: "studentId",
    claves.ROL_PROFESOR: "profesorId",
    claves.ROL_ADMIN: "adminId",
}


def construir_usuario(
    rol: str, user_id: str, nombre: str, email: str, password: str, detalle: str,
) -> tuple[db.Item, db.Item]:
    """
    Ítems de perfil y de email de un usuario nuevo.
    Lo usa el registro y también el script de datos iniciales (seed).
    """
    email = claves.normalizar_email(email)
    ahora: str = db.ahora_iso()
    perfil: db.Item = {
        "PK": claves.pk_usuario(rol, user_id),
        "SK": claves.SK_PERFIL,
        "entityType": rol,
        _ID_ROL[rol]: user_id,
        "nombre": nombre,
        "email": email,
        _CAMPO_ROL[rol]: detalle,
        "creadoEn": ahora,
    }
    login: db.Item = {
        "PK": claves.pk_email(email),
        "SK": claves.SK_LOGIN,
        "entityType": "EMAIL",
        "userId": user_id,
        "rol": rol,
        "passwordHash": seguridad.hash_password(password),
        "creadoEn": ahora,
    }
    return perfil, login


def cargar_perfil(rol: str, user_id: str) -> tuple[dict[str, Any] | None, str]:
    """Perfil público de un usuario con Cache-Aside y negative caching."""
    def desde_dynamodb() -> dict[str, Any] | None:
        return db.publico(db.get_item(claves.pk_usuario(rol, user_id), claves.SK_PERFIL))

    return cache.cache_aside(claves.rk_perfil(rol, user_id), desde_dynamodb, TTL_PERFIL)


# ── POST /auth/registro ───────────────────────────────────────────────

@rutas.ruta("POST", "/auth/registro")
def registrar(event: Evento) -> RespuestaApi:
    """
    Crea el perfil y el ítem de email en una sola transacción:
    si el email o el id ya existen, no se escribe ninguno de los dos.
    """
    datos: dict[str, Any] = leer_json(event)
    rol: str = (texto(datos, "rol", obligatorio=False) or claves.ROL_ESTUDIANTE).upper()
    if rol not in claves.ROLES:
        raise ErrorApi(400, f"Rol inválido. Valores permitidos: {', '.join(claves.ROLES)}")

    # Solo coordinación puede crear otra cuenta de coordinación
    if rol == claves.ROL_ADMIN:
        seguridad.exigir_rol(seguridad.autenticar(event), claves.ROL_ADMIN)

    nombre: str = texto(datos, "nombre")
    email: str = claves.normalizar_email(texto(datos, "email"))
    password: str = texto(datos, "password")
    user_id: str = texto(datos, "id", obligatorio=False) or uuid.uuid4().hex[:10]
    detalle: str = texto(datos, _CAMPO_ROL[rol], obligatorio=False)

    if not claves.email_valido(email):
        raise ErrorApi(400, "El email no tiene un formato válido")
    if not claves.id_usuario_valido(user_id):
        raise ErrorApi(400, "El id solo admite letras, números, punto y guion bajo (máx. 40)")
    if len(password) < 8:
        raise ErrorApi(400, "La contraseña debe tener al menos 8 caracteres")

    perfil, login = construir_usuario(rol, user_id, nombre, email, password, detalle)

    try:
        db.transaccion([
            db.op_put(perfil, "attribute_not_exists(PK)"),
            db.op_put(login, "attribute_not_exists(PK)"),
        ])
    except db.TransaccionCancelada as e:
        if e.fallo(1):
            raise ErrorApi(409, f"El email '{email}' ya está registrado")
        raise ErrorApi(409, f"Ya existe un usuario con id '{user_id}'")

    # El id pudo haberse consultado antes de existir (marca negativa en caché)
    cache.cache_delete(claves.rk_perfil(rol, user_id))
    return respuesta(201, db.publico(perfil))


# ── POST /auth/login ──────────────────────────────────────────────────

@rutas.ruta("POST", "/auth/login")
def iniciar_sesion(event: Evento) -> RespuestaApi:
    """
    1. Rate limiting por email (Redis)
    2. GetItem EMAIL#<email> y verificación del hash
    3. Token firmado + sesión en Redis con TTL
    """
    datos: dict[str, Any] = leer_json(event)
    email: str = claves.normalizar_email(texto(datos, "email"))
    password: str = texto(datos, "password")

    clave_limite: str = claves.rk_limite_login(email)
    if cache.limite_excedido(clave_limite, INTENTOS_LOGIN, VENTANA_LOGIN):
        raise ErrorApi(429, "Demasiados intentos de inicio de sesión. Espera un minuto")

    # Lectura consistente: una cuenta recién creada debe poder entrar
    login: db.Item | None = db.get_item(claves.pk_email(email), claves.SK_LOGIN, consistente=True)
    if login is None or not seguridad.verificar_password(password, login["passwordHash"]):
        # Mismo mensaje en ambos casos: no revela si el email existe
        raise ErrorApi(401, "Email o contraseña incorrectos")

    rol: str = login["rol"]
    user_id: str = login["userId"]
    perfil, _ = cargar_perfil(rol, user_id)
    nombre: str = (perfil or {}).get("nombre", "")

    token, sesion = seguridad.crear_token(user_id, rol, nombre)
    sesion_en_redis: bool = cache.sesion_guardar(
        claves.rk_sesion(sesion["jti"]), sesion, seguridad.duracion_sesion(),
    )
    cache.limite_reiniciar(clave_limite)

    return respuesta(200, {
        "token": token,
        "expiraEn": seguridad.duracion_sesion(),
        "usuario": {"userId": user_id, "rol": rol, "nombre": nombre},
        # False indica que Redis no estaba disponible (degraded mode)
        "sesionEnRedis": sesion_en_redis,
    })


# ── POST /auth/logout ─────────────────────────────────────────────────

@rutas.ruta("POST", "/auth/logout")
def cerrar_sesion(event: Evento) -> RespuestaApi:
    sesion: seguridad.Sesion = seguridad.autenticar(event)
    cache.sesion_cerrar(claves.rk_sesion(sesion["jti"]))
    return respuesta(200, {"mensaje": "Sesión cerrada"})


# ── GET /auth/me ──────────────────────────────────────────────────────

@rutas.ruta("GET", "/auth/me")
def perfil_propio(event: Evento) -> RespuestaApi:
    sesion: seguridad.Sesion = seguridad.autenticar(event)
    perfil, fuente = cargar_perfil(sesion["rol"], sesion["userId"])
    if perfil is None:
        raise ErrorApi(404, "El usuario de la sesión ya no existe")
    return respuesta(200, {**perfil, "rol": sesion["rol"], "_fuente": fuente})


# ── Entrada principal ─────────────────────────────────────────────────

def main(event: Evento, context: Any) -> RespuestaApi:
    return rutas.despachar(event)
