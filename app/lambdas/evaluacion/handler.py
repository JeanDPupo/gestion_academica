"""
Lambda /evaluacion
──────────────────
Lo que ocurre con una matrícula después de solicitarla: aprobación,
lista de clase y calificación.

Rutas soportadas:
  GET  /ofertas/{ofertaId}/estudiantes              → Lista de clase           (patrones 5 y 12)
  GET  /periodos/{periodo}/matriculas/pendientes    → Cola de pendientes       (patrón 9)
  POST /estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/aprobar → Aprobar
  PUT  /estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/nota    → Calificar
  GET  /estudiantes/{studentId}/notas               → Notas de mayor a menor   (patrón 4)

Índices que usa:
  GSI1  GSI1PK = OFFER#<ofertaId>, GSI1SK = STUDENT#<id>
        Invierte la relación de la tabla base: la misma matrícula sirve
        para "matrículas del estudiante" y "estudiantes de la oferta".
  GSI2  GSI2PK = PERIOD#<periodo>, GSI2SK = PENDING#<fecha>#...
        Disperso: al aprobar se eliminan los dos atributos y el ítem
        sale del índice. La cola queda ordenada por fecha de solicitud.
  LSI1  LSI1SK = GRADE#<nota×100>#<periodo>#<cursoId>
        Disperso: solo existe en matrículas calificadas.

Autorización: aprobar, calificar y ver la lista de clase exigen ser el
profesor de la oferta o coordinación. Se verifica leyendo la oferta de
DynamoDB con ConsistentRead, nunca desde Redis.

Redis (Cache-Aside):
  clase:<ofertaId>     TTL 2 min + invalidación al matricular/retirar/aprobar/calificar
  notas:<studentId>    TTL 5 min + invalidación al calificar
"""
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from comun import cache, claves, db, dominio, seguridad
from comun.http import (
    Enrutador, ErrorApi, Evento, RespuestaApi, leer_json, param, respuesta,
)

logger: logging.Logger = logging.getLogger()
logger.setLevel(logging.INFO)

rutas: Enrutador = Enrutador()

TTL_CLASE: int = 120
TTL_NOTAS: int = 300
NOTA_MINIMA: Decimal = Decimal("0")
NOTA_MAXIMA: Decimal = Decimal("5")


def _exigir_periodo(periodo: str) -> str:
    if not claves.periodo_valido(periodo):
        raise ErrorApi(400, "El periodo debe tener el formato AAAA-N, por ejemplo 2026-1")
    return periodo


def _matricula_de_la_ruta(event: Evento) -> tuple[str, str, str, db.Item]:
    student_id: str = param(event, "studentId")
    periodo: str = _exigir_periodo(param(event, "periodo"))
    curso_id: str = param(event, "cursoId").upper()
    return student_id, periodo, curso_id, dominio.leer_matricula(student_id, periodo, curso_id)


# ── GET /ofertas/{ofertaId}/estudiantes ───────────────────────────────

@rutas.ruta("GET", "/ofertas/{ofertaId}/estudiantes")
def lista_de_clase(event: Evento) -> RespuestaApi:
    """
    1. GetItem de la oferta (consistente) → autoriza al profesor
    2. Query a GSI1 con GSI1PK = OFFER#<ofertaId>
    La matrícula guarda nombreEstudiante, así que la lista sale sin
    consultar el perfil de cada estudiante (evita el N+1).
    """
    sesion: seguridad.Sesion = seguridad.autenticar(event)
    oferta: db.Item = dominio.leer_oferta(param(event, "ofertaId"))
    dominio.exigir_gestor_oferta(sesion, oferta)
    id_oferta: str = oferta["ofertaId"]

    def desde_dynamodb() -> dict[str, Any]:
        items: list[db.Item] = db.query(
            IndexName=claves.INDICE_GSI1,
            KeyConditionExpression=(
                Key("GSI1PK").eq(claves.gsi1pk_oferta(id_oferta))
                & Key("GSI1SK").begins_with("STUDENT#")
            ),
        )
        return {"estudiantes": [dominio.vista_lista_clase(i) for i in items]}

    resultado, fuente = cache.cache_aside(claves.rk_clase(id_oferta), desde_dynamodb, TTL_CLASE)
    estudiantes: list[dict[str, Any]] = (resultado or {}).get("estudiantes", [])
    return respuesta(200, {
        "oferta": db.publico(oferta),
        "total": len(estudiantes),
        "estudiantes": estudiantes,
        "_fuente": fuente,
    })


# ── GET /periodos/{periodo}/matriculas/pendientes ─────────────────────

@rutas.ruta("GET", "/periodos/{periodo}/matriculas/pendientes")
def pendientes_periodo(event: Evento) -> RespuestaApi:
    """
    Cola de trabajo de coordinación: no se cachea, debe verse al día.
    El índice solo contiene las pendientes, así que la Query lee
    exactamente lo que devuelve.
    """
    seguridad.exigir_rol(seguridad.autenticar(event), claves.ROL_ADMIN)
    periodo: str = _exigir_periodo(param(event, "periodo"))

    items: list[db.Item] = db.query(
        IndexName=claves.INDICE_GSI2,
        KeyConditionExpression=(
            Key("GSI2PK").eq(claves.gsi2pk_periodo(periodo))
            & Key("GSI2SK").begins_with(claves.PREFIJO_GSI2SK_PENDIENTE)
        ),
    )
    return respuesta(200, {
        "periodo": periodo,
        "total": len(items),
        "pendientes": [db.publico(i) for i in items],
        "_fuente": cache.FUENTE_DYNAMODB,
    })


# ── POST .../matriculas/{periodo}/{cursoId}/aprobar ───────────────────

@rutas.ruta("POST", "/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/aprobar")
def aprobar(event: Evento) -> RespuestaApi:
    """
    Update condicional: solo una matrícula PENDIENTE pasa a APROBADA.
    REMOVE de GSI2PK/GSI2SK la saca de la cola de pendientes.
    """
    sesion: seguridad.Sesion = seguridad.autenticar(event)
    student_id, periodo, curso_id, matricula = _matricula_de_la_ruta(event)
    dominio.exigir_gestor_oferta(sesion, dominio.leer_oferta(matricula["ofertaId"]))

    try:
        aprobada: db.Item = db.tabla().update_item(
            Key=claves.llave_matricula(student_id, periodo, curso_id),
            UpdateExpression=(
                "SET estado = :aprobada, fechaAprobacion = :ahora, aprobadaPor = :quien "
                "REMOVE GSI2PK, GSI2SK"
            ),
            ConditionExpression="estado = :pendiente",
            ExpressionAttributeValues={
                ":aprobada": claves.MATRICULA_APROBADA,
                ":pendiente": claves.MATRICULA_PENDIENTE,
                ":ahora": db.ahora_iso(),
                ":quien": sesion["userId"],
            },
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except ClientError as e:
        if db.es_condicion_fallida(e):
            raise ErrorApi(409, "La matrícula ya estaba aprobada o fue retirada")
        raise

    dominio.invalidar_matricula(student_id, periodo, matricula["ofertaId"])
    return respuesta(200, db.publico(aprobada))


# ── PUT .../matriculas/{periodo}/{cursoId}/nota ───────────────────────

@rutas.ruta("PUT", "/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/nota")
def calificar(event: Evento) -> RespuestaApi:
    """
    Guarda la nota y la llave del LSI en la misma escritura:
    LSI1SK = GRADE#<nota×100 con ceros>#<periodo>#<cursoId>.
    Solo se califica una matrícula APROBADA.
    """
    sesion: seguridad.Sesion = seguridad.autenticar(event)
    student_id, periodo, curso_id, matricula = _matricula_de_la_ruta(event)
    dominio.exigir_gestor_oferta(sesion, dominio.leer_oferta(matricula["ofertaId"]))

    try:
        nota: Decimal = Decimal(str(leer_json(event).get("nota")))
    except InvalidOperation:
        raise ErrorApi(400, "El campo 'nota' debe ser un número")
    if not nota.is_finite() or not NOTA_MINIMA <= nota <= NOTA_MAXIMA:
        raise ErrorApi(400, "La nota debe estar entre 0.0 y 5.0")
    nota = nota.quantize(Decimal("0.01"))

    try:
        calificada: db.Item = db.tabla().update_item(
            Key=claves.llave_matricula(student_id, periodo, curso_id),
            UpdateExpression="SET nota = :nota, LSI1SK = :lsi, fechaNota = :ahora",
            ConditionExpression="estado = :aprobada",
            ExpressionAttributeValues={
                ":nota": nota,
                ":lsi": claves.lsi1sk_nota(nota, periodo, curso_id),
                ":ahora": db.ahora_iso(),
                ":aprobada": claves.MATRICULA_APROBADA,
            },
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except ClientError as e:
        if db.es_condicion_fallida(e):
            raise ErrorApi(409, "Solo se puede calificar una matrícula aprobada")
        raise

    dominio.invalidar_matricula(student_id, periodo, matricula["ofertaId"])
    return respuesta(200, db.publico(calificada))


# ── GET /estudiantes/{studentId}/notas ────────────────────────────────

@rutas.ruta("GET", "/estudiantes/{studentId}/notas")
def notas_estudiante(event: Evento) -> RespuestaApi:
    """
    Query al LSI1 (misma PK del estudiante, ordenado por nota) con
    ScanIndexForward=False: de la nota más alta a la más baja.
    """
    sesion: seguridad.Sesion = seguridad.autenticar(event)
    student_id: str = param(event, "studentId")
    seguridad.exigir_propietario(sesion, claves.ROL_ESTUDIANTE, student_id)

    def desde_dynamodb() -> dict[str, Any]:
        items: list[db.Item] = db.query(
            IndexName=claves.INDICE_NOTAS,
            KeyConditionExpression=(
                Key("PK").eq(claves.pk_estudiante(student_id))
                & Key("LSI1SK").begins_with("GRADE#")
            ),
            ScanIndexForward=False,
        )
        return {"notas": [db.publico(i) for i in items]}

    resultado, fuente = cache.cache_aside(claves.rk_notas(student_id), desde_dynamodb, TTL_NOTAS)
    notas: list[dict[str, Any]] = (resultado or {}).get("notas", [])

    creditos: int = sum(n.get("creditos", 0) for n in notas)
    ponderado: float = sum(n["nota"] * n.get("creditos", 0) for n in notas)
    return respuesta(200, {
        "studentId": student_id,
        "total": len(notas),
        "creditosCalificados": creditos,
        # Promedio ponderado por créditos
        "promedio": round(ponderado / creditos, 2) if creditos else None,
        "notas": notas,
        "_fuente": fuente,
    })


def main(event: Evento, context: Any) -> RespuestaApi:
    return rutas.despachar(event)
