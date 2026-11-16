"""
seguridad.py
────────────
Autenticación y autorización.

Contraseñas
  PBKDF2-HMAC-SHA256 con sal aleatoria (biblioteca estándar: no añade
  dependencias compiladas al paquete de la Lambda).

Sesiones
  El login emite un token firmado con HMAC-SHA256 que lleva usuario, rol
  y expiración, y registra la sesión en Redis (`sesion:<jti>`, con TTL).

  Validación de cada petición:
    1. Firma y expiración del token     → sin Redis, sin DynamoDB
    2. La sesión existe en Redis        → permite logout / revocación

  Si Redis no está disponible se acepta el token con firma válida
  (degraded mode): se pierde la revocación inmediata, no el servicio.
  La autorización de negocio (¿esta oferta es de este profesor?) nunca
  depende de Redis: siempre se verifica contra DynamoDB.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from typing import Any, TypeAlias

from comun import cache, claves
from comun.http import ErrorApi, Evento, cabecera

# Datos de la sesión: {"userId", "rol", "nombre", "jti", "exp"}
Sesion: TypeAlias = dict[str, Any]

_ALGORITMO: str = "pbkdf2_sha256"


def _iteraciones() -> int:
    return int(os.environ.get("PBKDF2_ITERACIONES", 100_000))


def _secreto() -> bytes:
    return os.environ.get("TOKEN_SECRET", "solo-para-desarrollo-local").encode()


def duracion_sesion() -> int:
    return int(os.environ.get("SESION_TTL", 3600))


# ── Contraseñas ───────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Retorna 'pbkdf2_sha256$<iteraciones>$<sal>$<hash>'."""
    sal: str = secrets.token_hex(16)
    iteraciones: int = _iteraciones()
    derivada: bytes = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(sal), iteraciones
    )
    return f"{_ALGORITMO}${iteraciones}${sal}${derivada.hex()}"


def verificar_password(password: str, almacenado: str) -> bool:
    try:
        algoritmo, iteraciones, sal, esperado = almacenado.split("$")
    except ValueError:
        return False
    if algoritmo != _ALGORITMO:
        return False
    derivada: bytes = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(sal), int(iteraciones)
    )
    # compare_digest evita filtrar información por tiempo de comparación
    return hmac.compare_digest(derivada.hex(), esperado)


# ── Tokens ────────────────────────────────────────────────────────────

def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def _desde_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _firmar(contenido: str) -> str:
    return _b64(hmac.new(_secreto(), contenido.encode(), hashlib.sha256).digest())


def crear_token(user_id: str, rol: str, nombre: str) -> tuple[str, Sesion]:
    """Emite el token y retorna también los datos de sesión que contiene."""
    sesion: Sesion = {
        "userId": user_id,
        "rol": rol,
        "nombre": nombre,
        "jti": uuid.uuid4().hex,
        "exp": int(time.time()) + duracion_sesion(),
    }
    contenido: str = _b64(json.dumps(sesion, separators=(",", ":")).encode())
    return f"{contenido}.{_firmar(contenido)}", sesion


def leer_token(token: str) -> Sesion | None:
    """Retorna la sesión si la firma es válida y no ha expirado."""
    try:
        contenido, firma = token.split(".")
        if not hmac.compare_digest(firma, _firmar(contenido)):
            return None
        sesion: Sesion = json.loads(_desde_b64(contenido))
    except (ValueError, json.JSONDecodeError):
        return None
    if sesion.get("exp", 0) < time.time():
        return None
    return sesion


# ── Autenticación de la petición ──────────────────────────────────────

def autenticar(event: Evento) -> Sesion:
    """
    Sesión del usuario que hace la petición.
    Lanza ErrorApi(401) si no hay token válido o la sesión fue cerrada.
    """
    autorizacion: str = cabecera(event, "Authorization") or ""
    if not autorizacion.lower().startswith("bearer "):
        raise ErrorApi(401, "Falta el token de sesión (Authorization: Bearer <token>)")

    sesion: Sesion | None = leer_token(autorizacion[7:].strip())
    if sesion is None:
        raise ErrorApi(401, "Token inválido o expirado")

    # False = Redis respondió que la sesión no existe → fue cerrada.
    # None  = Redis caído → se acepta la firma (degraded mode).
    if cache.sesion_activa(claves.rk_sesion(sesion["jti"])) is False:
        raise ErrorApi(401, "La sesión fue cerrada o expiró")
    return sesion


# ── Autorización ──────────────────────────────────────────────────────

def exigir_rol(sesion: Sesion, *roles: str) -> None:
    if sesion["rol"] not in roles:
        raise ErrorApi(403, "Tu rol no tiene permiso para esta operación")


def es_admin(sesion: Sesion) -> bool:
    return sesion["rol"] == claves.ROL_ADMIN


def es_el_usuario(sesion: Sesion, rol: str, user_id: str) -> bool:
    return sesion["rol"] == rol and sesion["userId"] == user_id


def exigir_propietario(sesion: Sesion, rol: str, user_id: str, *roles_extra: str) -> None:
    """
    Permite al dueño del recurso (rol + id) y a los roles adicionales.
    La coordinación (ADMIN) siempre puede.
    """
    if es_admin(sesion) or es_el_usuario(sesion, rol, user_id):
        return
    if sesion["rol"] in roles_extra:
        return
    raise ErrorApi(403, "No puedes acceder a recursos de otro usuario")
