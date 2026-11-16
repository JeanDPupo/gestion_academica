"""
Lambda /matriculas
──────────────────
Ciclo de vida de la matrícula de un estudiante.

Rutas soportadas:
  POST   /matriculas                                              → Matricular          (patrón 10)
  GET    /estudiantes/{studentId}/matriculas                      → Horario / historial (patrón 3)
  DELETE /estudiantes/{studentId}/matriculas/{periodo}/{cursoId}  → Retirar o rechazar
  PUT    /estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/grupo → Cambiar de grupo
  GET    /periodos/{periodo}/demanda                              → Cursos más solicitados

Modelo de datos (Single Table Design):
  Matrícula  PK = STUDENT#<studentId>   SK = ENROLL#<periodo>#<cursoId>
             GSI1PK = OFFER#<ofertaId>  GSI1SK = STUDENT#<studentId>
             GSI2PK = PERIOD#<periodo>  GSI2SK = PENDING#<fecha>#<studentId>#<cursoId>
                                        (solo mientras está PENDIENTE: índice disperso)

  El grupo (ofertaId) NO forma parte de la SK. Por eso la propia llave
  garantiza "una matrícula por estudiante, curso y periodo": un segundo
  Put con attribute_not_exists(PK) falla aunque sea a otro grupo.

Toda escritura es una transacción (TransactWriteItems): la matrícula y
el contador de cupos de la oferta cambian juntos o no cambia ninguno.

Redis:
  horario:<studentId>:<periodo>   Cache-Aside, TTL 5 min + invalidación
  demanda:<periodo>               Sorted Set, ZINCRBY por cada solicitud
"""
import logging
from typing import Any

from boto3.dynamodb.conditions import Key

from comun import cache, claves, db, dominio, seguridad
from comun.http import (
    Enrutador, ErrorApi, Evento, RespuestaApi,
    leer_json, param, query_param, respuesta, texto,
)

logger: logging.Logger = logging.getLogger()
logger.setLevel(logging.INFO)

rutas: Enrutador = Enrutador()

TTL_HORARIO: int = 300
TOP_DEMANDA_MAXIMO: int = 50

# Condiciones reutilizadas en las transacciones
_HAY_CUPO: str = "cuposDisponibles > :cero AND estado = :activa"
_DEVOLVER_CUPO: str = "attribute_exists(PK) AND cuposDisponibles < cuposTotales"


def _exigir_periodo(periodo: str) -> str:
    if not claves.periodo_valido(periodo):
        raise ErrorApi(400, "El periodo debe tener el formato AAAA-N, por ejemplo 2026-1")
    return periodo


# ── POST /matriculas ──────────────────────────────────────────────────

@rutas.ruta("POST", "/matriculas")
def matricular(event: Evento) -> RespuestaApi:
    """
    Transacción de tres operaciones (todo o nada):
      0. Put de la matrícula          si no existe ya para ese curso y periodo
      1. Update de la oferta: cupo-1  si queda cupo y la oferta está ACTIVA
      2. ConditionCheck del perfil    el estudiante existe
    Dos estudiantes compitiendo por el último cupo no pueden ganar ambos:
    la condición se evalúa de forma atómica en DynamoDB.
    """
    sesion: seguridad.Sesion = seguridad.autenticar(event)
    seguridad.exigir_rol(sesion, claves.ROL_ESTUDIANTE, claves.ROL_ADMIN)
    datos: dict[str, Any] = leer_json(event)

    # El estudiante se matricula a sí mismo; coordinación indica a quién
    student_id: str = (
        texto(datos, "studentId") if seguridad.es_admin(sesion) else sesion["userId"]
    )
    oferta: db.Item = dominio.leer_oferta(texto(datos, "ofertaId"))
    id_oferta: str = oferta["ofertaId"]
    curso_id: str = oferta["cursoId"]
    periodo: str = oferta["periodo"]

    estudiante: db.Item | None = db.get_item(
        claves.pk_estudiante(student_id), claves.SK_PERFIL, consistente=True,
    )
    if estudiante is None:
        raise ErrorApi(404, f"El estudiante '{student_id}' no existe")

    ahora: str = db.ahora_iso()
    pendiente: bool = bool(oferta.get("requiereAprobacion", True))
    llave: dict[str, str] = claves.llave_matricula(student_id, periodo, curso_id)

    # Copia de los datos que se muestran con la matrícula (desnormalización):
    # el horario del estudiante y la lista de clase salen de una sola Query.
    matricula: db.Item = {
        **llave,
        "GSI1PK": claves.gsi1pk_oferta(id_oferta),
        "GSI1SK": claves.gsi1sk_estudiante(student_id),
        "entityType": "ENROLLMENT",
        "studentId": student_id,
        "nombreEstudiante": estudiante["nombre"],
        "cursoId": curso_id,
        "nombreCurso": oferta["nombreCurso"],
        "creditos": oferta["creditos"],
        "periodo": periodo,
        "ofertaId": id_oferta,
        "grupo": oferta["grupo"],
        "horario": oferta["horario"],
        "nombreProfesor": oferta["nombreProfesor"],
        "estado": claves.MATRICULA_PENDIENTE if pendiente else claves.MATRICULA_APROBADA,
        "fechaSolicitud": ahora,
    }
    if pendiente:
        # Solo las pendientes entran a GSI2 (índice disperso)
        matricula["GSI2PK"] = claves.gsi2pk_periodo(periodo)
        matricula["GSI2SK"] = claves.gsi2sk_pendiente(ahora, student_id, curso_id)

    clave_demanda: str = claves.rk_demanda(periodo)
    try:
        db.transaccion([
            db.op_put(matricula, "attribute_not_exists(PK)"),
            db.op_update(
                claves.llave_oferta(id_oferta) or {},
                "SET cuposDisponibles = cuposDisponibles - :uno",
                _HAY_CUPO,
                {":uno": 1, ":cero": 0, ":activa": claves.OFERTA_ACTIVA},
            ),
            db.op_check(
                {"PK": claves.pk_estudiante(student_id), "SK": claves.SK_PERFIL},
                "attribute_exists(PK)",
            ),
        ])
    except db.TransaccionCancelada as e:
        if e.fallo(0):
            raise ErrorApi(409, f"Ya tienes una matrícula de {curso_id} en el periodo {periodo}")
        if e.fallo(1):
            # Una solicitud sin cupo también es demanda del curso
            cache.demanda_incrementar(clave_demanda, curso_id)
            raise ErrorApi(409, f"La oferta '{id_oferta}' no tiene cupos o está cerrada")
        raise ErrorApi(404, f"El estudiante '{student_id}' no existe")

    # Después del commit: contar la demanda e invalidar lo que quedó viejo
    cache.demanda_incrementar(clave_demanda, curso_id)
    dominio.invalidar_matricula(student_id, periodo, id_oferta)
    return respuesta(201, db.publico(matricula))


# ── GET /estudiantes/{studentId}/matriculas ───────────────────────────

@rutas.ruta("GET", "/estudiantes/{studentId}/matriculas")
def matriculas_estudiante(event: Evento) -> RespuestaApi:
    """
    Query por PK = STUDENT#<id> y SK begins_with ENROLL#<periodo>#.
    Sin ?periodo= trae todo el historial (ordenado por periodo).
    """
    sesion: seguridad.Sesion = seguridad.autenticar(event)
    student_id: str = param(event, "studentId")
    seguridad.exigir_propietario(sesion, claves.ROL_ESTUDIANTE, student_id)

    periodo: str | None = query_param(event, "periodo")
    if periodo:
        _exigir_periodo(periodo)

    def desde_dynamodb() -> dict[str, Any]:
        items: list[db.Item] = db.query(
            KeyConditionExpression=(
                Key("PK").eq(claves.pk_estudiante(student_id))
                & Key("SK").begins_with(claves.prefijo_sk_matricula(periodo))
            ),
        )
        return {"matriculas": [db.publico(i) for i in items]}

    resultado, fuente = cache.cache_aside(
        claves.rk_horario(student_id, periodo), desde_dynamodb, TTL_HORARIO,
    )
    matriculas: list[dict[str, Any]] = (resultado or {}).get("matriculas", [])
    return respuesta(200, {
        "studentId": student_id,
        "periodo": periodo or "todos",
        "total": len(matriculas),
        "creditos": sum(m.get("creditos", 0) for m in matriculas),
        "matriculas": matriculas,
        "_fuente": fuente,
    })


# ── DELETE /estudiantes/{studentId}/matriculas/{periodo}/{cursoId} ────

@rutas.ruta("DELETE", "/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}")
def retirar(event: Evento) -> RespuestaApi:
    """
    Retiro (estudiante) o rechazo (profesor de la oferta / coordinación).
    Transacción: Delete de la matrícula + cupo+1 en la oferta. Al borrarse
    la llave queda libre y el estudiante puede volver a matricular el curso.
    """
    sesion: seguridad.Sesion = seguridad.autenticar(event)
    student_id: str = param(event, "studentId")
    periodo: str = _exigir_periodo(param(event, "periodo"))
    curso_id: str = param(event, "cursoId").upper()

    matricula: db.Item = dominio.leer_matricula(student_id, periodo, curso_id)
    id_oferta: str = matricula["ofertaId"]

    if not seguridad.es_el_usuario(sesion, claves.ROL_ESTUDIANTE, student_id):
        dominio.exigir_gestor_oferta(sesion, dominio.leer_oferta(id_oferta))
    if "nota" in matricula:
        raise ErrorApi(409, "Una matrícula calificada no se puede retirar")

    try:
        db.transaccion([
            # Las condiciones evitan devolver un cupo que no se ocupaba:
            # la matrícula debe existir, seguir en esa oferta y no tener nota.
            db.op_delete(
                claves.llave_matricula(student_id, periodo, curso_id),
                "attribute_exists(PK) AND ofertaId = :oferta AND attribute_not_exists(nota)",
                {":oferta": id_oferta},
            ),
            db.op_update(
                claves.llave_oferta(id_oferta) or {},
                "SET cuposDisponibles = cuposDisponibles + :uno",
                _DEVOLVER_CUPO,
                {":uno": 1},
            ),
        ])
    except db.TransaccionCancelada:
        raise ErrorApi(409, "La matrícula cambió mientras se procesaba el retiro. Intenta de nuevo")

    dominio.invalidar_matricula(student_id, periodo, id_oferta)
    return respuesta(200, {
        "mensaje": f"Matrícula de {curso_id} ({periodo}) retirada", "ofertaId": id_oferta,
    })


# ── PUT .../matriculas/{periodo}/{cursoId}/grupo ──────────────────────

@rutas.ruta("PUT", "/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/grupo")
def cambiar_grupo(event: Evento) -> RespuestaApi:
    """
    El grupo es un atributo, así que cambiarlo no crea ni borra la
    matrícula. Transacción de tres operaciones:
      0. Update de la matrícula    si sigue en el grupo actual y sin nota
      1. cupo+1 en la oferta anterior
      2. cupo-1 en la oferta nueva si queda cupo y está ACTIVA
    """
    sesion: seguridad.Sesion = seguridad.autenticar(event)
    student_id: str = param(event, "studentId")
    periodo: str = _exigir_periodo(param(event, "periodo"))
    curso_id: str = param(event, "cursoId").upper()
    seguridad.exigir_propietario(sesion, claves.ROL_ESTUDIANTE, student_id)

    nueva: db.Item = dominio.leer_oferta(texto(leer_json(event), "ofertaId"))
    id_nueva: str = nueva["ofertaId"]
    if nueva["cursoId"] != curso_id or nueva["periodo"] != periodo:
        raise ErrorApi(400, "El nuevo grupo debe ser del mismo curso y periodo")

    matricula: db.Item = dominio.leer_matricula(student_id, periodo, curso_id)
    id_actual: str = matricula["ofertaId"]
    if id_actual == id_nueva:
        raise ErrorApi(409, "La matrícula ya está en ese grupo")
    if "nota" in matricula:
        raise ErrorApi(409, "Una matrícula calificada no se puede cambiar de grupo")

    try:
        db.transaccion([
            db.op_update(
                claves.llave_matricula(student_id, periodo, curso_id),
                # Al cambiar GSI1PK la matrícula pasa a la lista de clase del
                # grupo nuevo; GSI1SK (STUDENT#<id>) no cambia.
                "SET ofertaId = :nueva, GSI1PK = :gsi1pk, grupo = :grupo, "
                "horario = :horario, nombreProfesor = :profesor",
                "ofertaId = :actual AND attribute_not_exists(nota)",
                {
                    ":nueva": id_nueva,
                    ":gsi1pk": claves.gsi1pk_oferta(id_nueva),
                    ":grupo": nueva["grupo"],
                    ":horario": nueva["horario"],
                    ":profesor": nueva["nombreProfesor"],
                    ":actual": id_actual,
                },
            ),
            db.op_update(
                claves.llave_oferta(id_actual) or {},
                "SET cuposDisponibles = cuposDisponibles + :uno",
                _DEVOLVER_CUPO,
                {":uno": 1},
            ),
            db.op_update(
                claves.llave_oferta(id_nueva) or {},
                "SET cuposDisponibles = cuposDisponibles - :uno",
                _HAY_CUPO,
                {":uno": 1, ":cero": 0, ":activa": claves.OFERTA_ACTIVA},
            ),
        ])
    except db.TransaccionCancelada as e:
        if e.fallo(2):
            raise ErrorApi(409, f"La oferta '{id_nueva}' no tiene cupos o está cerrada")
        raise ErrorApi(409, "La matrícula cambió mientras se procesaba. Intenta de nuevo")

    dominio.invalidar_matricula(student_id, periodo, id_actual, id_nueva)
    return respuesta(200, {
        "mensaje": f"Cambio de grupo realizado: {id_actual} → {id_nueva}",
        "ofertaAnterior": id_actual,
        "ofertaId": id_nueva,
        "horario": nueva["horario"],
    })


# ── GET /periodos/{periodo}/demanda ───────────────────────────────────

@rutas.ruta("GET", "/periodos/{periodo}/demanda")
def ranking_demanda(event: Evento) -> RespuestaApi:
    """
    Cursos más solicitados del periodo. El dato vive solo en Redis
    (Sorted Set): es una métrica no crítica que tolera pérdida, por eso
    no se escribe en DynamoDB en el camino de la matrícula.
    """
    periodo: str = _exigir_periodo(param(event, "periodo"))
    try:
        top: int = int(query_param(event, "top") or 5)
    except ValueError:
        raise ErrorApi(400, "El parámetro 'top' debe ser un número entero")
    top = max(1, min(top, TOP_DEMANDA_MAXIMO))

    filas: list[tuple[str, int]] | None = cache.demanda_top(claves.rk_demanda(periodo), top)
    return respuesta(200, {
        "periodo": periodo,
        # False = Redis no disponible: el API responde, sin ranking
        "disponible": filas is not None,
        "ranking": [
            {"posicion": i + 1, "cursoId": curso, "solicitudes": solicitudes}
            for i, (curso, solicitudes) in enumerate(filas or [])
        ],
        "_fuente": "redis",
    })


def main(event: Evento, context: Any) -> RespuestaApi:
    return rutas.despachar(event)
