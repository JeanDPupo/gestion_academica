"""
http.py
───────
Utilidades HTTP para Lambdas detrás de API Gateway (integración proxy):
respuestas JSON con CORS, errores de negocio y un enrutador mínimo.

Cada Lambda atiende varias rutas de su dominio. El enrutador resuelve
(método, recurso) → función usando `event["resource"]`, que es la
plantilla de la ruta tal como se declaró en el stack
(p. ej. "/estudiantes/{studentId}/matriculas").
"""
import json
import logging
import re
from decimal import Decimal
from typing import Any, Callable, TypeAlias

from botocore.exceptions import ClientError

logger: logging.Logger = logging.getLogger(__name__)

# Respuesta en formato proxy de API Gateway
RespuestaApi: TypeAlias = dict[str, Any]
Evento: TypeAlias = dict[str, Any]
Manejador: TypeAlias = Callable[[Evento], RespuestaApi]

# El frontend de la demo se sirve desde otro origen (localhost:8080),
# así que todas las respuestas llevan cabeceras CORS.
CABECERAS: dict[str, str] = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
}


class ErrorApi(Exception):
    """Error de negocio que se traduce directamente a una respuesta HTTP."""

    def __init__(self, status: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.status: int = status
        self.mensaje: str = mensaje


def respuesta(status: int, body: dict[str, Any] | None = None) -> RespuestaApi:
    return {
        "statusCode": status,
        "headers": dict(CABECERAS),
        "body": json.dumps(body, default=str, ensure_ascii=False) if body is not None else "",
    }


def respuesta_error(status: int, mensaje: str) -> RespuestaApi:
    return respuesta(status, {"error": mensaje})


# ── Lectura de la petición ────────────────────────────────────────────

def leer_json(event: Evento) -> dict[str, Any]:
    """
    Cuerpo de la petición como dict.
    Los decimales se leen como Decimal porque DynamoDB no acepta float.
    """
    try:
        datos: Any = json.loads(event.get("body") or "{}", parse_float=Decimal)
    except json.JSONDecodeError:
        raise ErrorApi(400, "El cuerpo de la petición no es JSON válido")
    if not isinstance(datos, dict):
        raise ErrorApi(400, "El cuerpo de la petición debe ser un objeto JSON")
    return datos


def texto(datos: dict[str, Any], campo: str, obligatorio: bool = True) -> str:
    """Campo de texto del cuerpo, sin espacios sobrantes."""
    valor: Any = datos.get(campo)
    if valor is None or str(valor).strip() == "":
        if obligatorio:
            raise ErrorApi(400, f"El campo '{campo}' es obligatorio")
        return ""
    return str(valor).strip()


def param(event: Evento, nombre: str) -> str:
    valor: str | None = (event.get("pathParameters") or {}).get(nombre)
    if not valor:
        raise ErrorApi(400, f"Falta el parámetro de ruta '{nombre}'")
    return valor


def query_param(event: Evento, nombre: str) -> str | None:
    valor: str | None = (event.get("queryStringParameters") or {}).get(nombre)
    return valor or None


def cabecera(event: Evento, nombre: str) -> str | None:
    """Cabecera sin distinguir mayúsculas (API Gateway no las normaliza)."""
    for clave, valor in (event.get("headers") or {}).items():
        if clave.lower() == nombre.lower():
            return valor
    return None


# ── Enrutador ─────────────────────────────────────────────────────────

class Enrutador:
    """
    Registro de rutas de una Lambda:

        rutas = Enrutador()

        @rutas.ruta("GET", "/cursos/{cursoId}")
        def detalle_curso(event): ...

        def main(event, context):
            return rutas.despachar(event)
    """

    def __init__(self) -> None:
        self._rutas: dict[tuple[str, str], Manejador] = {}

    def ruta(self, metodo: str, recurso: str) -> Callable[[Manejador], Manejador]:
        def registrar(funcion: Manejador) -> Manejador:
            self._rutas[(metodo, recurso)] = funcion
            return funcion
        return registrar

    def _resolver(self, event: Evento) -> Manejador | None:
        metodo: str = event.get("httpMethod", "")
        recurso: str | None = event.get("resource")
        if recurso and (metodo, recurso) in self._rutas:
            return self._rutas[(metodo, recurso)]

        # Respaldo: si el evento no trae `resource`, se compara la ruta
        # real contra cada plantilla y se extraen los parámetros.
        camino: str = event.get("path") or ""
        for (m, plantilla), funcion in self._rutas.items():
            if m != metodo:
                continue
            patron: str = "^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", plantilla) + "/?$"
            encontrado = re.search(patron, camino)
            if encontrado:
                event["pathParameters"] = {
                    **(event.get("pathParameters") or {}), **encontrado.groupdict(),
                }
                return funcion
        return None

    def despachar(self, event: Evento) -> RespuestaApi:
        metodo: str = event.get("httpMethod", "")
        logger.info("REQUEST %s %s", metodo, event.get("path") or event.get("resource"))

        # Preflight CORS: el navegador pregunta antes de enviar Authorization
        if metodo == "OPTIONS":
            return respuesta(204)

        manejador: Manejador | None = self._resolver(event)
        if manejador is None:
            return respuesta_error(405, f"Método '{metodo}' no soportado en esta ruta")

        try:
            return manejador(event)
        except ErrorApi as e:
            return respuesta_error(e.status, e.mensaje)
        except ClientError as e:
            logger.error("Error DynamoDB: %s", e)
            return respuesta_error(500, "Error al acceder a la base de datos")
        except Exception:
            logger.exception("Error no controlado")
            return respuesta_error(500, "Error interno del servicio")
