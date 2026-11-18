"""
Lambda /health
──────────────
Health check del servicio.
Verifica conectividad con DynamoDB y Redis
y retorna el estado de cada componente.

Rutas soportadas:
  GET    /health         → Estado de DynamoDB y Redis
                           200 si DynamoDB responde (con Redis caído el
                           servicio sigue operando en modo degradado),
                           503 si DynamoDB no está disponible.
"""
import logging
import os
from typing import Any, TypeAlias

import boto3
from botocore.exceptions import ClientError

from comun import cache
from comun.http import Evento, RespuestaApi, respuesta

# Estado de un componente: {"estado": "ok" | "error", ...}
EstadoComponente: TypeAlias = dict[str, str]

logger: logging.Logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME: str = os.environ["TABLE_NAME"]


def _check_dynamodb() -> EstadoComponente:
    try:
        tabla: Any = boto3.resource("dynamodb").Table(TABLE_NAME)
        tabla.load()   # describe la tabla; falla si no existe
        return {"estado": "ok", "tabla": TABLE_NAME}
    except ClientError as e:
        return {"estado": "error", "detalle": str(e)}
    except Exception as e:
        return {"estado": "error", "detalle": str(e)}


def _check_redis() -> EstadoComponente:
    host: str = os.environ.get("REDIS_HOST", "redis")
    # cache.ping() usa la resolución DNS acotada del módulo común; con
    # Redis caído responde en ~1 s en vez de colgar la Lambda.
    if cache.ping():
        return {"estado": "ok", "host": host}
    return {"estado": "error", "detalle": f"sin respuesta de Redis ({host})"}


def main(event: Evento, context: Any) -> RespuestaApi:
    logger.info("Health check solicitado")
    if event.get("httpMethod") == "OPTIONS":
        return respuesta(204)

    db_status: EstadoComponente    = _check_dynamodb()
    redis_status: EstadoComponente = _check_redis()

    db_ok: bool = db_status["estado"] == "ok"
    redis_ok: bool = redis_status["estado"] == "ok"

    # DynamoDB es la fuente de verdad: sin ella no hay servicio (503).
    # Redis es una optimización: sin él el servicio responde, más lento.
    if db_ok and redis_ok:
        estado = "ok"
    elif db_ok:
        estado = "degradado"
    else:
        estado = "error"

    return respuesta(200 if db_ok else 503, {
        "estado":   estado,
        "dynamodb": db_status,
        "redis":    redis_status,
    })
