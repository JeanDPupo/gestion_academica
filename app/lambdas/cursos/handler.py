"""
Lambda /cursos
──────────────
Cursos, ofertas (grupos de un curso en un periodo) y catálogo.

Rutas soportadas:
  POST /cursos                          → Crear curso                      (coordinación)
  GET  /cursos/{cursoId}                → Curso + sus ofertas activas      (patrón 6)
  POST /cursos/{cursoId}/ofertas        → Crear oferta                     (coordinación)
  GET  /periodos/{periodo}/ofertas      → Catálogo del periodo             (patrón 7)
  GET  /profesores/{profesorId}/ofertas → Ofertas que dicta un profesor    (patrón 8)
  PUT  /ofertas/{ofertaId}/estado       → Abrir o cerrar una oferta        (coordinación)

Modelo de datos (Single Table Design):
  Curso    PK = COURSE#<cursoId>   SK = METADATA
  Oferta   PK = COURSE#<cursoId>   SK = OFFER#<periodo>#<ofertaId>
           GSI1PK = PROF#<profesorId>   GSI1SK = PERIOD#<periodo>#OFFER#<ofertaId>
           GSI2PK = PERIOD#<periodo>    GSI2SK = OFFER#<cursoId>#<ofertaId>

  El curso y sus ofertas comparten PK: una sola Query trae ambos.
  ofertaId = <cursoId>-<periodo>-<grupo> (único en todo el sistema).

Caché (Cache-Aside):
  catalogo:<periodo>, curso:<cursoId>, ofertas-prof:<id>:<periodo>
      Las tres respuestas incluyen cuposDisponibles, que cambia con cada
      matrícula. Se cachean con un TTL corto (TTL_CUPOS, 15 s por defecto)
      en lugar de invalidarlas en cada matrícula: en plena jornada de
      inscripciones la clave más leída se borraría sin parar y la caché
      no serviría de nada. Con el TTL, por más lecturas que lleguen hay
      como máximo una Query a DynamoDB cada 15 s por periodo.
      Además se invalidan al crear una oferta o cambiar su estado.
  El cupo mostrado puede ir hasta 15 s atrasado; el cupo real lo decide
  la transacción de matrícula contra DynamoDB.
"""
import logging
import os
from typing import Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from comun import cache, claves, db, seguridad
from comun.http import (
    Enrutador, ErrorApi, Evento, RespuestaApi,
    leer_json, param, query_param, respuesta, texto,
)

logger: logging.Logger = logging.getLogger()
logger.setLevel(logging.INFO)

rutas: Enrutador = Enrutador()



def _ttl_cupos() -> int:
    """TTL de todo lo que muestra cuposDisponibles (catálogo, curso, ofertas)."""
    return int(os.environ.get("TTL_CUPOS", 15))


def _entero(datos: dict[str, Any], campo: str, minimo: int, maximo: int) -> int:
    try:
        valor: int = int(datos.get(campo))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ErrorApi(400, f"El campo '{campo}' debe ser un número entero")
    if not minimo <= valor <= maximo:
        raise ErrorApi(400, f"El campo '{campo}' debe estar entre {minimo} y {maximo}")
    return valor


def _exigir_periodo(periodo: str) -> str:
    if not claves.periodo_valido(periodo):
        raise ErrorApi(400, "El periodo debe tener el formato AAAA-N, por ejemplo 2026-1")
    return periodo


# ── POST /cursos ──────────────────────────────────────────────────────

@rutas.ruta("POST", "/cursos")
def crear_curso(event: Evento) -> RespuestaApi:
    seguridad.exigir_rol(seguridad.autenticar(event), claves.ROL_ADMIN)
    datos: dict[str, Any] = leer_json(event)

    curso_id: str = texto(datos, "cursoId").upper()
    if not claves.curso_valido(curso_id):
        raise ErrorApi(400, "cursoId admite de 2 a 12 letras mayúsculas o números, p. ej. MAT101")

    curso: db.Item = {
        "PK": claves.pk_curso(curso_id),
        "SK": claves.SK_CURSO,
        "entityType": "COURSE",
        "cursoId": curso_id,
        "nombre": texto(datos, "nombre"),
        "creditos": _entero(datos, "creditos", 1, 20),
        "creadoEn": db.ahora_iso(),
    }
    try:
        db.tabla().put_item(Item=curso, ConditionExpression="attribute_not_exists(PK)")
    except ClientError as e:
        if db.es_condicion_fallida(e):
            raise ErrorApi(409, f"El curso '{curso_id}' ya existe")
        raise

    # Borra una posible marca negativa de consultas previas al curso
    cache.cache_delete(claves.rk_curso(curso_id))
    return respuesta(201, db.publico(curso))


# ── GET /cursos/{cursoId} ─────────────────────────────────────────────

@rutas.ruta("GET", "/cursos/{cursoId}")
def detalle_curso(event: Evento) -> RespuestaApi:
    """
    Una sola Query por PK trae el curso (SK = METADATA) y sus ofertas
    (SK = OFFER#...). Se descartan las ofertas cerradas.
    """
    curso_id: str = param(event, "cursoId").upper()
    if not claves.curso_valido(curso_id):
        raise ErrorApi(400, "Identificador de curso inválido")

    def desde_dynamodb() -> dict[str, Any] | None:
        items: list[db.Item] = db.query(
            KeyConditionExpression=Key("PK").eq(claves.pk_curso(curso_id)),
            FilterExpression=(
                Attr("entityType").eq("COURSE") | Attr("estado").eq(claves.OFERTA_ACTIVA)
            ),
        )
        curso: db.Item | None = next(
            (i for i in items if i["SK"] == claves.SK_CURSO), None,
        )
        if curso is None:
            return None
        ofertas: list[Any] = [
            db.publico(i) for i in items if i["SK"].startswith(claves.PREFIJO_SK_OFERTA)
        ]
        return {"curso": db.publico(curso), "ofertas": ofertas}

    detalle, fuente = cache.cache_aside(claves.rk_curso(curso_id), desde_dynamodb, _ttl_cupos())
    if detalle is None:
        raise ErrorApi(404, f"El curso '{curso_id}' no existe")
    return respuesta(200, {**detalle, "_fuente": fuente})


# ── POST /cursos/{cursoId}/ofertas ────────────────────────────────────

@rutas.ruta("POST", "/cursos/{cursoId}/ofertas")
def crear_oferta(event: Evento) -> RespuestaApi:
    """
    Crea un grupo del curso en un periodo. Guarda una copia del nombre del
    curso, los créditos y el nombre del profesor (desnormalización): el
    catálogo y la matrícula salen sin lecturas adicionales.
    """
    seguridad.exigir_rol(seguridad.autenticar(event), claves.ROL_ADMIN)
    datos: dict[str, Any] = leer_json(event)

    curso_id: str = param(event, "cursoId").upper()
    periodo: str = _exigir_periodo(texto(datos, "periodo"))
    grupo: str = texto(datos, "grupo").upper()
    profesor_id: str = texto(datos, "profesorId")
    if not claves.curso_valido(curso_id):
        raise ErrorApi(400, "Identificador de curso inválido")
    if not claves.grupo_valido(grupo):
        raise ErrorApi(400, "grupo admite de 1 a 6 letras mayúsculas o números, p. ej. G1")
    cupos: int = _entero(datos, "cupos", 1, 500)

    curso: db.Item | None = db.get_item(claves.pk_curso(curso_id), claves.SK_CURSO, consistente=True)
    if curso is None:
        raise ErrorApi(404, f"El curso '{curso_id}' no existe")
    profesor: db.Item | None = db.get_item(
        claves.pk_profesor(profesor_id), claves.SK_PERFIL, consistente=True,
    )
    if profesor is None:
        raise ErrorApi(404, f"El profesor '{profesor_id}' no existe")

    id_oferta: str = claves.oferta_id(curso_id, periodo, grupo)
    oferta: db.Item = {
        "PK": claves.pk_curso(curso_id),
        "SK": claves.sk_oferta(periodo, id_oferta),
        "GSI1PK": claves.gsi1pk_profesor(profesor_id),
        "GSI1SK": claves.gsi1sk_oferta(periodo, id_oferta),
        "GSI2PK": claves.gsi2pk_periodo(periodo),
        "GSI2SK": claves.gsi2sk_oferta(curso_id, id_oferta),
        "entityType": "OFFER",
        "ofertaId": id_oferta,
        "cursoId": curso_id,
        "nombreCurso": curso["nombre"],
        "creditos": curso["creditos"],
        "periodo": periodo,
        "grupo": grupo,
        "profesorId": profesor_id,
        "nombreProfesor": profesor["nombre"],
        "horario": texto(datos, "horario"),
        "cuposTotales": cupos,
        "cuposDisponibles": cupos,
        "estado": claves.OFERTA_ACTIVA,
        # Si es False la matrícula nace APROBADA y no pasa por la cola
        "requiereAprobacion": bool(datos.get("requiereAprobacion", True)),
        "creadoEn": db.ahora_iso(),
    }
    try:
        db.tabla().put_item(Item=oferta, ConditionExpression="attribute_not_exists(PK)")
    except ClientError as e:
        if db.es_condicion_fallida(e):
            raise ErrorApi(409, f"La oferta '{id_oferta}' ya existe")
        raise

    _invalidar_oferta(curso_id, periodo, profesor_id)
    return respuesta(201, db.publico(oferta))


def _invalidar_oferta(curso_id: str, periodo: str, profesor_id: str) -> None:
    cache.cache_delete(
        claves.rk_catalogo(periodo),
        claves.rk_curso(curso_id),
        claves.rk_ofertas_profesor(profesor_id, periodo),
        claves.rk_ofertas_profesor(profesor_id, None),
    )


# ── GET /periodos/{periodo}/ofertas ───────────────────────────────────

@rutas.ruta("GET", "/periodos/{periodo}/ofertas")
def catalogo_periodo(event: Evento) -> RespuestaApi:
    """Catálogo: Query a GSI2 con PK = PERIOD#<periodo> y SK begins_with OFFER#."""
    periodo: str = _exigir_periodo(param(event, "periodo"))

    def desde_dynamodb() -> dict[str, Any]:
        items: list[db.Item] = db.query(
            IndexName=claves.INDICE_GSI2,
            KeyConditionExpression=(
                Key("GSI2PK").eq(claves.gsi2pk_periodo(periodo))
                & Key("GSI2SK").begins_with(claves.PREFIJO_GSI2SK_OFERTA)
            ),
        )
        return {"ofertas": [db.publico(i) for i in items]}

    catalogo, fuente = cache.cache_aside(claves.rk_catalogo(periodo), desde_dynamodb, _ttl_cupos())
    ofertas: list[Any] = (catalogo or {}).get("ofertas", [])
    return respuesta(200, {
        "periodo": periodo, "total": len(ofertas), "ofertas": ofertas, "_fuente": fuente,
    })


# ── GET /profesores/{profesorId}/ofertas ──────────────────────────────

@rutas.ruta("GET", "/profesores/{profesorId}/ofertas")
def ofertas_profesor(event: Evento) -> RespuestaApi:
    """
    Query a GSI1 con PK = PROF#<profesorId>; con ?periodo= se acota con
    SK begins_with PERIOD#<periodo>#.
    """
    sesion: seguridad.Sesion = seguridad.autenticar(event)
    profesor_id: str = param(event, "profesorId")
    seguridad.exigir_propietario(sesion, claves.ROL_PROFESOR, profesor_id)

    periodo: str | None = query_param(event, "periodo")
    if periodo:
        _exigir_periodo(periodo)

    def desde_dynamodb() -> dict[str, Any]:
        items: list[db.Item] = db.query(
            IndexName=claves.INDICE_GSI1,
            KeyConditionExpression=(
                Key("GSI1PK").eq(claves.gsi1pk_profesor(profesor_id))
                & Key("GSI1SK").begins_with(claves.prefijo_gsi1sk_periodo(periodo))
            ),
        )
        return {"ofertas": [db.publico(i) for i in items]}

    resultado, fuente = cache.cache_aside(
        claves.rk_ofertas_profesor(profesor_id, periodo), desde_dynamodb, _ttl_cupos(),
    )
    ofertas: list[Any] = (resultado or {}).get("ofertas", [])
    return respuesta(200, {
        "profesorId": profesor_id, "total": len(ofertas), "ofertas": ofertas, "_fuente": fuente,
    })


# ── PUT /ofertas/{ofertaId}/estado ────────────────────────────────────

@rutas.ruta("PUT", "/ofertas/{ofertaId}/estado")
def cambiar_estado_oferta(event: Evento) -> RespuestaApi:
    """Una oferta CERRADA sale del detalle del curso y no admite matrículas."""
    seguridad.exigir_rol(seguridad.autenticar(event), claves.ROL_ADMIN)
    id_oferta: str = param(event, "ofertaId")
    llave: dict[str, str] | None = claves.llave_oferta(id_oferta)
    if llave is None:
        raise ErrorApi(400, "ofertaId inválido. Formato: <cursoId>-<periodo>-<grupo>")

    estado: str = texto(leer_json(event), "estado").upper()
    if estado not in (claves.OFERTA_ACTIVA, claves.OFERTA_CERRADA):
        raise ErrorApi(400, "estado debe ser ACTIVA o CERRADA")

    try:
        actualizada: db.Item = db.tabla().update_item(
            Key=llave,
            UpdateExpression="SET estado = :estado",
            ConditionExpression="attribute_exists(PK)",
            ExpressionAttributeValues={":estado": estado},
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except ClientError as e:
        if db.es_condicion_fallida(e):
            raise ErrorApi(404, f"La oferta '{id_oferta}' no existe")
        raise

    _invalidar_oferta(actualizada["cursoId"], actualizada["periodo"], actualizada["profesorId"])
    return respuesta(200, db.publico(actualizada))


def main(event: Evento, context: Any) -> RespuestaApi:
    return rutas.despachar(event)
