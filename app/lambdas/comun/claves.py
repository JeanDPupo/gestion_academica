"""
claves.py
─────────
Única fuente de verdad de las llaves del modelo.

Todo el Single Table Design vive aquí: ningún handler arma un "STUDENT#..."
a mano. Si cambia el diseño de llaves, cambia este archivo y nada más.

Tabla base:  PK / SK
LSI1:        PK / LSI1SK          (matrículas de un estudiante por nota)
GSI1:        GSI1PK / GSI1SK      (ofertas de un profesor · estudiantes de una oferta)
GSI2:        GSI2PK / GSI2SK      (catálogo del periodo · matrículas pendientes)

Ver docs/diseno-dynamodb-gestion-academica.md para la justificación.
"""
import re
from decimal import Decimal
from typing import NamedTuple

# ── Roles y estados ───────────────────────────────────────────────────
ROL_ESTUDIANTE: str = "STUDENT"
ROL_PROFESOR: str = "PROFESSOR"
ROL_ADMIN: str = "ADMIN"
ROLES: tuple[str, ...] = (ROL_ESTUDIANTE, ROL_PROFESOR, ROL_ADMIN)

OFERTA_ACTIVA: str = "ACTIVA"
OFERTA_CERRADA: str = "CERRADA"

MATRICULA_PENDIENTE: str = "PENDIENTE"
MATRICULA_APROBADA: str = "APROBADA"

# Prefijo de PK del perfil según el rol
_PREFIJO_ROL: dict[str, str] = {
    ROL_ESTUDIANTE: "STUDENT",
    ROL_PROFESOR: "PROF",
    ROL_ADMIN: "ADMIN",
}

# Atributos que son llaves del modelo y no se exponen en el API
ATRIBUTOS_LLAVE: frozenset[str] = frozenset(
    {"PK", "SK", "LSI1SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"}
)

# ── Validación de identificadores ─────────────────────────────────────
# Los ids viajan en la URL y dentro de llaves separadas por "#" y "-",
# así que se restringen a un alfabeto que no choca con esos separadores.
_RE_ID_USUARIO = re.compile(r"^[A-Za-z0-9_.]{1,40}$")
_RE_CURSO = re.compile(r"^[A-Z0-9]{2,12}$")
_RE_GRUPO = re.compile(r"^[A-Z0-9]{1,6}$")
_RE_PERIODO = re.compile(r"^\d{4}-[1-9]$")
_RE_OFERTA = re.compile(r"^([A-Z0-9]{2,12})-(\d{4}-[1-9])-([A-Z0-9]{1,6})$")
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def id_usuario_valido(valor: str) -> bool:
    return bool(_RE_ID_USUARIO.match(valor or ""))


def curso_valido(curso_id: str) -> bool:
    return bool(_RE_CURSO.match(curso_id or ""))


def grupo_valido(grupo: str) -> bool:
    return bool(_RE_GRUPO.match(grupo or ""))


def periodo_valido(periodo: str) -> bool:
    return bool(_RE_PERIODO.match(periodo or ""))


def normalizar_email(email: str) -> str:
    """Minúsculas y sin espacios: el email es llave de unicidad."""
    return (email or "").strip().lower()


def email_valido(email: str) -> bool:
    return bool(_RE_EMAIL.match(email or ""))


# ── Oferta: id compuesto ──────────────────────────────────────────────
class PartesOferta(NamedTuple):
    curso_id: str
    periodo: str
    grupo: str


def oferta_id(curso_id: str, periodo: str, grupo: str) -> str:
    """
    Id determinístico y globalmente único de una oferta:
        <cursoId>-<periodo>-<grupo>      p. ej.  MAT101-2026-1-G1

    Como el id contiene el curso y el periodo, basta el ofertaId para
    reconstruir la llave primaria de la oferta (GetItem, sin índice) y
    GSI1PK = OFFER#<ofertaId> no puede colisionar entre cursos.
    """
    return f"{curso_id}-{periodo}-{grupo}"


def partes_oferta(id_oferta: str) -> PartesOferta | None:
    """Descompone un ofertaId. Retorna None si el formato no es válido."""
    m = _RE_OFERTA.match(id_oferta or "")
    if not m:
        return None
    return PartesOferta(m.group(1), m.group(2), m.group(3))


# ── Llaves de la tabla base ───────────────────────────────────────────
def pk_usuario(rol: str, user_id: str) -> str:
    return f"{_PREFIJO_ROL[rol]}#{user_id}"


def pk_estudiante(student_id: str) -> str:
    return f"STUDENT#{student_id}"


def pk_profesor(profesor_id: str) -> str:
    return f"PROF#{profesor_id}"


SK_PERFIL: str = "PROFILE"


def pk_email(email: str) -> str:
    return f"EMAIL#{normalizar_email(email)}"


SK_LOGIN: str = "LOGIN"


def pk_curso(curso_id: str) -> str:
    return f"COURSE#{curso_id}"


SK_CURSO: str = "METADATA"
PREFIJO_SK_OFERTA: str = "OFFER#"


def sk_oferta(periodo: str, id_oferta: str) -> str:
    return f"OFFER#{periodo}#{id_oferta}"


def llave_oferta(id_oferta: str) -> dict[str, str] | None:
    """PK/SK de una oferta a partir de su id compuesto."""
    partes = partes_oferta(id_oferta)
    if partes is None:
        return None
    return {"PK": pk_curso(partes.curso_id), "SK": sk_oferta(partes.periodo, id_oferta)}


def sk_matricula(periodo: str, curso_id: str) -> str:
    return f"ENROLL#{periodo}#{curso_id}"


def prefijo_sk_matricula(periodo: str | None = None) -> str:
    """begins_with para las matrículas de un periodo (o todas si None)."""
    return f"ENROLL#{periodo}#" if periodo else "ENROLL#"


def llave_matricula(student_id: str, periodo: str, curso_id: str) -> dict[str, str]:
    return {"PK": pk_estudiante(student_id), "SK": sk_matricula(periodo, curso_id)}


# ── Llaves de índices ─────────────────────────────────────────────────
INDICE_NOTAS: str = "LSI1"
INDICE_GSI1: str = "GSI1"
INDICE_GSI2: str = "GSI2"


def lsi1sk_nota(nota: Decimal, periodo: str, curso_id: str) -> str:
    """
    GRADE#<nota×100 en 4 dígitos>#<periodo>#<cursoId>
    4.50 → GRADE#0450#...  El relleno con ceros hace que el orden
    lexicográfico coincida con el numérico.
    """
    centesimas: int = int((nota * 100).to_integral_value())
    return f"GRADE#{centesimas:04d}#{periodo}#{curso_id}"


# GSI1 — Oferta: ofertas que dicta un profesor
def gsi1pk_profesor(profesor_id: str) -> str:
    return f"PROF#{profesor_id}"


def gsi1sk_oferta(periodo: str, id_oferta: str) -> str:
    return f"PERIOD#{periodo}#OFFER#{id_oferta}"


def prefijo_gsi1sk_periodo(periodo: str | None = None) -> str:
    return f"PERIOD#{periodo}#" if periodo else "PERIOD#"


# GSI1 — Matrícula: estudiantes de una oferta (lista de clase)
def gsi1pk_oferta(id_oferta: str) -> str:
    return f"OFFER#{id_oferta}"


def gsi1sk_estudiante(student_id: str) -> str:
    return f"STUDENT#{student_id}"


# GSI2 — agrupa por periodo: catálogo de ofertas y cola de pendientes
def gsi2pk_periodo(periodo: str) -> str:
    return f"PERIOD#{periodo}"


def gsi2sk_oferta(curso_id: str, id_oferta: str) -> str:
    return f"OFFER#{curso_id}#{id_oferta}"


PREFIJO_GSI2SK_OFERTA: str = "OFFER#"


def gsi2sk_pendiente(fecha_iso: str, student_id: str, curso_id: str) -> str:
    return f"PENDING#{fecha_iso}#{student_id}#{curso_id}"


PREFIJO_GSI2SK_PENDIENTE: str = "PENDING#"


# ── Claves de Redis ───────────────────────────────────────────────────
# Convención:  <tipo>:<id>[:<detalle>]
def rk_perfil(rol: str, user_id: str) -> str:
    return f"perfil:{_PREFIJO_ROL[rol].lower()}:{user_id}"


def rk_curso(curso_id: str) -> str:
    return f"curso:{curso_id}"


def rk_catalogo(periodo: str) -> str:
    return f"catalogo:{periodo}"


def rk_ofertas_profesor(profesor_id: str, periodo: str | None) -> str:
    return f"ofertas-prof:{profesor_id}:{periodo or 'todos'}"


def rk_horario(student_id: str, periodo: str | None) -> str:
    return f"horario:{student_id}:{periodo or 'todos'}"


def rk_notas(student_id: str) -> str:
    return f"notas:{student_id}"


def rk_clase(id_oferta: str) -> str:
    return f"clase:{id_oferta}"


def rk_sesion(jti: str) -> str:
    return f"sesion:{jti}"


def rk_limite_login(email: str) -> str:
    return f"limite:login:{normalizar_email(email)}"


def rk_demanda(periodo: str) -> str:
    return f"demanda:{periodo}"
