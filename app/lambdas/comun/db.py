"""
db.py
─────
Acceso a DynamoDB: una sola tabla (Single Table Design).

Reúne lo que todos los handlers necesitan:
  · lecturas puntuales (GetItem) y consultas paginadas (Query)
  · transacciones (TransactWriteItems) con el detalle de qué condición falló
  · conversión Decimal → int/float y limpieza de llaves para el API

No hay ningún Scan: todas las lecturas van por llave o por índice.
"""
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, TypeAlias

import boto3
from botocore.exceptions import ClientError

from comun import claves

logger: logging.Logger = logging.getLogger(__name__)

# Ítem tal como se guarda en DynamoDB
Item: TypeAlias = dict[str, Any]
# Operación de una transacción: {"Put": {...}} | {"Update": {...}} | ...
Operacion: TypeAlias = dict[str, dict[str, Any]]

# boto3 lee AWS_ENDPOINT_URL del entorno y redirige al emulador local.
# El recurso se crea en el primer uso y se reutiliza entre invocaciones.
_recurso: Any = None


def _dynamodb() -> Any:
    global _recurso
    if _recurso is None:
        _recurso = boto3.resource("dynamodb")
    return _recurso


def reiniciar_conexion() -> None:
    """Descarta el recurso en caché (usado por los tests con moto)."""
    global _recurso
    _recurso = None


def nombre_tabla() -> str:
    return os.environ["TABLE_NAME"]


def tabla() -> Any:
    # boto3 genera la clase Table en tiempo de ejecución; sin los stubs
    # de mypy-boto3-dynamodb no hay un tipo estático más preciso.
    return _dynamodb().Table(nombre_tabla())


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Conversión ────────────────────────────────────────────────────────

def desde_dynamo(valor: Any) -> Any:
    """
    DynamoDB devuelve los números como Decimal, que json.dumps no serializa.
    Los convierte a int (si son enteros) o float, recursivamente.
    """
    if isinstance(valor, Decimal):
        return int(valor) if valor == valor.to_integral_value() else float(valor)
    if isinstance(valor, dict):
        return {k: desde_dynamo(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [desde_dynamo(v) for v in valor]
    return valor


def publico(item: Item | None, *ocultar: str) -> Item | None:
    """
    Vista de un ítem para el API: sin las llaves del modelo (PK, SK, GSI…)
    ni los atributos indicados en `ocultar`, y con los Decimal convertidos.
    """
    if item is None:
        return None
    return {
        k: desde_dynamo(v)
        for k, v in item.items()
        if k not in claves.ATRIBUTOS_LLAVE and k not in ocultar
    }


# ── Lecturas ──────────────────────────────────────────────────────────

def get_item(pk: str, sk: str, consistente: bool = False) -> Item | None:
    """
    GetItem por llave primaria completa.
    `consistente=True` fuerza lectura fuertemente consistente: se usa en
    las decisiones críticas (autorización, validaciones previas a escribir).
    """
    respuesta: dict[str, Any] = tabla().get_item(
        Key={"PK": pk, "SK": sk}, ConsistentRead=consistente
    )
    item: Item | None = respuesta.get("Item")
    logger.info("DynamoDB GET PK=%s SK=%s → %s", pk, sk, "ok" if item else "no existe")
    return item


def query(**parametros: Any) -> list[Item]:
    """
    Query que sigue LastEvaluatedKey hasta traer todas las páginas.
    Las colecciones del modelo están acotadas (matrículas de un estudiante,
    estudiantes de una oferta, ofertas de un periodo), así que es seguro.
    """
    items: list[Item] = []
    while True:
        respuesta: dict[str, Any] = tabla().query(**parametros)
        items.extend(respuesta.get("Items", []))
        ultima: dict[str, Any] | None = respuesta.get("LastEvaluatedKey")
        if not ultima:
            break
        parametros["ExclusiveStartKey"] = ultima
    logger.info(
        "DynamoDB QUERY indice=%s → %d ítems",
        parametros.get("IndexName", "tabla"), len(items),
    )
    return items


# ── Transacciones ─────────────────────────────────────────────────────

class TransaccionCancelada(Exception):
    """
    La transacción no se aplicó porque falló al menos una condición.
    `fallidas` trae los índices (según el orden de las operaciones) cuya
    condición no se cumplió.
    """

    def __init__(self, codigos: list[str]) -> None:
        super().__init__(f"Transacción cancelada: {codigos}")
        self.codigos: list[str] = codigos
        self.fallidas: set[int] = {
            i for i, codigo in enumerate(codigos) if codigo == "ConditionalCheckFailed"
        }

    def fallo(self, indice: int) -> bool:
        return indice in self.fallidas


def _con_expresiones(
    cuerpo: dict[str, Any],
    condicion: str | None,
    valores: dict[str, Any] | None,
    nombres: dict[str, str] | None,
) -> dict[str, Any]:
    if condicion:
        cuerpo["ConditionExpression"] = condicion
    if valores:
        cuerpo["ExpressionAttributeValues"] = valores
    if nombres:
        cuerpo["ExpressionAttributeNames"] = nombres
    return cuerpo


def op_put(
    item: Item,
    condicion: str | None = None,
    valores: dict[str, Any] | None = None,
) -> Operacion:
    return {"Put": _con_expresiones(
        {"TableName": nombre_tabla(), "Item": item}, condicion, valores, None,
    )}


def op_update(
    llave: dict[str, str],
    actualizacion: str,
    condicion: str | None = None,
    valores: dict[str, Any] | None = None,
    nombres: dict[str, str] | None = None,
) -> Operacion:
    return {"Update": _con_expresiones(
        {"TableName": nombre_tabla(), "Key": llave, "UpdateExpression": actualizacion},
        condicion, valores, nombres,
    )}


def op_delete(
    llave: dict[str, str],
    condicion: str | None = None,
    valores: dict[str, Any] | None = None,
) -> Operacion:
    return {"Delete": _con_expresiones(
        {"TableName": nombre_tabla(), "Key": llave}, condicion, valores, None,
    )}


def op_check(
    llave: dict[str, str],
    condicion: str,
    valores: dict[str, Any] | None = None,
) -> Operacion:
    return {"ConditionCheck": _con_expresiones(
        {"TableName": nombre_tabla(), "Key": llave}, condicion, valores, None,
    )}


def transaccion(operaciones: list[Operacion]) -> None:
    """
    TransactWriteItems: todo o nada.
    Si alguna condición falla no se escribe nada y se lanza
    TransaccionCancelada indicando cuáles operaciones fallaron.
    """
    # El cliente del recurso serializa los tipos de Python (str, int,
    # Decimal, bool) al formato de DynamoDB automáticamente.
    cliente: Any = _dynamodb().meta.client
    try:
        cliente.transact_write_items(TransactItems=operaciones)
    except ClientError as e:
        if e.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        razones: list[dict[str, Any]] = e.response.get("CancellationReasons", [])
        codigos: list[str] = [r.get("Code", "None") for r in razones]
        logger.info("DynamoDB TRANSACT cancelada: %s", codigos)
        raise TransaccionCancelada(codigos) from e
    logger.info("DynamoDB TRANSACT ok (%d operaciones)", len(operaciones))


def es_condicion_fallida(error: ClientError) -> bool:
    return error.response["Error"]["Code"] == "ConditionalCheckFailedException"
