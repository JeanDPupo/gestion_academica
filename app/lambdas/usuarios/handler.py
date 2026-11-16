"""
Lambda /usuarios
────────────────
Consulta de perfiles de estudiantes y profesores.

Rutas soportadas:
  GET /estudiantes/{studentId}   → Perfil del estudiante   (patrón de acceso 1)
  GET /profesores/{profesorId}   → Perfil del profesor     (patrón de acceso 2)

Modelo de datos (Single Table Design):
  PK = STUDENT#<studentId> | PROF#<profesorId>     SK = PROFILE

Caché (Cache-Aside):
  perfil:<rol>:<id> con TTL de 15 minutos: se lee con mucha frecuencia
  y casi nunca cambia. Los ids inexistentes se guardan con una marca
  negativa de 30 s para no consultar DynamoDB en cada intento.
"""
import logging
from typing import Any

from comun import cache, claves, db, seguridad
from comun.http import Enrutador, ErrorApi, Evento, RespuestaApi, param, respuesta

logger: logging.Logger = logging.getLogger()
logger.setLevel(logging.INFO)

rutas: Enrutador = Enrutador()

TTL_PERFIL: int = 900
TTL_NEGATIVO: int = 30


def _perfil(rol: str, user_id: str) -> RespuestaApi:
    if not claves.id_usuario_valido(user_id):
        raise ErrorApi(400, "Identificador de usuario inválido")

    def desde_dynamodb() -> dict[str, Any] | None:
        return db.publico(db.get_item(claves.pk_usuario(rol, user_id), claves.SK_PERFIL))

    perfil, fuente = cache.cache_aside(
        claves.rk_perfil(rol, user_id), desde_dynamodb, TTL_PERFIL, TTL_NEGATIVO,
    )
    if perfil is None:
        raise ErrorApi(404, f"No existe un usuario con id '{user_id}'")
    return respuesta(200, {**perfil, "_fuente": fuente})


@rutas.ruta("GET", "/estudiantes/{studentId}")
def perfil_estudiante(event: Evento) -> RespuestaApi:
    """Lo ven el propio estudiante, los profesores y coordinación."""
    sesion: seguridad.Sesion = seguridad.autenticar(event)
    student_id: str = param(event, "studentId")
    seguridad.exigir_propietario(
        sesion, claves.ROL_ESTUDIANTE, student_id, claves.ROL_PROFESOR,
    )
    return _perfil(claves.ROL_ESTUDIANTE, student_id)


@rutas.ruta("GET", "/profesores/{profesorId}")
def perfil_profesor(event: Evento) -> RespuestaApi:
    """Visible para cualquier usuario autenticado."""
    seguridad.autenticar(event)
    return _perfil(claves.ROL_PROFESOR, param(event, "profesorId"))


def main(event: Evento, context: Any) -> RespuestaApi:
    return rutas.despachar(event)
