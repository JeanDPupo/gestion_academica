"""
dominio.py
──────────
Reglas compartidas por las Lambdas de matrículas y de evaluación:
lectura de ofertas y matrículas, autorización sobre una oferta e
invalidación de las cachés que dependen de una matrícula.
"""
from typing import Any

from comun import cache, claves, db, seguridad
from comun.http import ErrorApi

# Campos de la matrícula que se muestran en la lista de clase
CAMPOS_LISTA_CLASE: tuple[str, ...] = (
    "studentId", "nombreEstudiante", "estado", "nota", "fechaSolicitud",
)


def leer_oferta(id_oferta: str) -> db.Item:
    """
    Oferta por su id compuesto, con lectura fuertemente consistente:
    de ella dependen la autorización del profesor y los datos que se
    copian a la matrícula.
    """
    llave: dict[str, str] | None = claves.llave_oferta(id_oferta)
    if llave is None:
        raise ErrorApi(400, "ofertaId inválido. Formato: <cursoId>-<periodo>-<grupo>")
    oferta: db.Item | None = db.get_item(llave["PK"], llave["SK"], consistente=True)
    if oferta is None:
        raise ErrorApi(404, f"La oferta '{id_oferta}' no existe")
    return oferta


def leer_matricula(student_id: str, periodo: str, curso_id: str) -> db.Item:
    llave: dict[str, str] = claves.llave_matricula(student_id, periodo, curso_id)
    matricula: db.Item | None = db.get_item(llave["PK"], llave["SK"], consistente=True)
    if matricula is None:
        raise ErrorApi(
            404, f"El estudiante '{student_id}' no tiene matrícula en {curso_id} ({periodo})",
        )
    return matricula


def gestiona_oferta(sesion: seguridad.Sesion, oferta: db.Item) -> bool:
    """Coordinación, o el profesor que dicta la oferta."""
    return seguridad.es_admin(sesion) or seguridad.es_el_usuario(
        sesion, claves.ROL_PROFESOR, oferta["profesorId"],
    )


def exigir_gestor_oferta(sesion: seguridad.Sesion, oferta: db.Item) -> None:
    """
    Autorización contra DynamoDB: la oferta se leyó con ConsistentRead,
    nunca de una caché que pudiera estar desactualizada.
    """
    if not gestiona_oferta(sesion, oferta):
        raise ErrorApi(403, "Solo el profesor de la oferta o coordinación pueden hacer esto")


def invalidar_matricula(student_id: str, periodo: str, *ofertas: str) -> None:
    """
    Borra las cachés que una escritura sobre la matrícula deja viejas:
    el horario y las notas del estudiante y la lista de clase de cada
    oferta involucrada. Se llama después de confirmar la escritura.
    """
    cache.cache_delete(
        claves.rk_horario(student_id, periodo),
        claves.rk_horario(student_id, None),
        claves.rk_notas(student_id),
        *(claves.rk_clase(o) for o in ofertas),
    )


def vista_lista_clase(matricula: db.Item) -> dict[str, Any]:
    visible: dict[str, Any] = db.publico(matricula) or {}
    return {campo: visible[campo] for campo in CAMPOS_LISTA_CLASE if campo in visible}
