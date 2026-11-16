"""
test_seguridad.py
─────────────────
Tests de contraseñas, tokens de sesión y autorización por rol.
"""
import pytest

from comun import cache, claves, seguridad
from comun.http import ErrorApi


def _evento(token: str | None) -> dict:
    return {"headers": {"authorization": f"Bearer {token}"} if token else {}}


# ── Contraseñas ───────────────────────────────────────────────────────

def test_hash_y_verificacion_de_password():
    almacenado = seguridad.hash_password("clave-segura-1")
    assert almacenado.startswith("pbkdf2_sha256$")
    assert "clave-segura-1" not in almacenado
    assert seguridad.verificar_password("clave-segura-1", almacenado)
    assert not seguridad.verificar_password("otra-clave", almacenado)


def test_dos_hashes_de_la_misma_clave_son_distintos():
    """La sal aleatoria evita que dos usuarios con la misma clave compartan hash."""
    assert seguridad.hash_password("igual") != seguridad.hash_password("igual")


def test_verificar_con_hash_malformado_retorna_false():
    assert not seguridad.verificar_password("x", "no-es-un-hash")


# ── Tokens ────────────────────────────────────────────────────────────

def test_token_valido_devuelve_la_sesion():
    token, sesion = seguridad.crear_token("e1", claves.ROL_ESTUDIANTE, "Ana")
    leida = seguridad.leer_token(token)
    assert leida == sesion
    assert leida["userId"] == "e1" and leida["rol"] == "STUDENT"


def test_token_alterado_es_rechazado():
    token, _ = seguridad.crear_token("e1", claves.ROL_ESTUDIANTE, "Ana")
    contenido, firma = token.split(".")
    otro, _ = seguridad.crear_token("admin", claves.ROL_ADMIN, "X")
    assert seguridad.leer_token(f"{otro.split('.')[0]}.{firma}") is None
    assert seguridad.leer_token("basura") is None


def test_token_expirado_es_rechazado(monkeypatch):
    monkeypatch.setenv("SESION_TTL", "-10")
    token, _ = seguridad.crear_token("e1", claves.ROL_ESTUDIANTE, "Ana")
    assert seguridad.leer_token(token) is None


def test_token_firmado_con_otro_secreto_es_rechazado(monkeypatch):
    token, _ = seguridad.crear_token("e1", claves.ROL_ESTUDIANTE, "Ana")
    monkeypatch.setenv("TOKEN_SECRET", "otro-secreto")
    assert seguridad.leer_token(token) is None


# ── Autenticación de la petición ──────────────────────────────────────

def _sesion_abierta(user_id="e1", rol=claves.ROL_ESTUDIANTE):
    token, sesion = seguridad.crear_token(user_id, rol, "Nombre")
    cache.sesion_guardar(claves.rk_sesion(sesion["jti"]), sesion, 3600)
    return token, sesion


def test_autenticar_con_sesion_activa():
    token, sesion = _sesion_abierta()
    assert seguridad.autenticar(_evento(token))["userId"] == sesion["userId"]


def test_autenticar_sin_cabecera_retorna_401():
    with pytest.raises(ErrorApi) as e:
        seguridad.autenticar(_evento(None))
    assert e.value.status == 401


def test_autenticar_tras_logout_retorna_401():
    """La firma sigue siendo válida, pero la sesión ya no está en Redis."""
    token, sesion = _sesion_abierta()
    cache.sesion_cerrar(claves.rk_sesion(sesion["jti"]))
    with pytest.raises(ErrorApi) as e:
        seguridad.autenticar(_evento(token))
    assert e.value.status == 401


def test_autenticar_con_redis_caido_acepta_la_firma(redis_caido):
    """Degraded mode: sin Redis se pierde la revocación, no el servicio."""
    token, _ = seguridad.crear_token("e1", claves.ROL_ESTUDIANTE, "Ana")
    assert seguridad.autenticar(_evento(token))["userId"] == "e1"


# ── Autorización ──────────────────────────────────────────────────────

def test_exigir_rol():
    _, sesion = seguridad.crear_token("e1", claves.ROL_ESTUDIANTE, "Ana")
    seguridad.exigir_rol(sesion, claves.ROL_ESTUDIANTE, claves.ROL_ADMIN)
    with pytest.raises(ErrorApi) as e:
        seguridad.exigir_rol(sesion, claves.ROL_ADMIN)
    assert e.value.status == 403


def test_exigir_propietario():
    _, ana = seguridad.crear_token("e1", claves.ROL_ESTUDIANTE, "Ana")
    _, admin = seguridad.crear_token("a1", claves.ROL_ADMIN, "Coord")
    _, profe = seguridad.crear_token("e1", claves.ROL_PROFESOR, "Mismo id, otro rol")

    seguridad.exigir_propietario(ana, claves.ROL_ESTUDIANTE, "e1")
    seguridad.exigir_propietario(admin, claves.ROL_ESTUDIANTE, "e1")
    with pytest.raises(ErrorApi):
        seguridad.exigir_propietario(ana, claves.ROL_ESTUDIANTE, "e2")
    # Mismo id pero distinto rol no es el dueño
    with pytest.raises(ErrorApi):
        seguridad.exigir_propietario(profe, claves.ROL_ESTUDIANTE, "e1")
    # …salvo que el rol esté en los roles adicionales permitidos
    seguridad.exigir_propietario(profe, claves.ROL_ESTUDIANTE, "e1", claves.ROL_PROFESOR)
