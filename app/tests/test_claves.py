"""
test_claves.py
──────────────
Tests del diseño de llaves (Single Table Design).
"""
from decimal import Decimal

from comun import claves


# ── Oferta: id compuesto ──────────────────────────────────────────────

def test_oferta_id_compuesto_es_reversible():
    id_oferta = claves.oferta_id("MAT101", "2026-1", "G1")
    assert id_oferta == "MAT101-2026-1-G1"
    assert claves.partes_oferta(id_oferta) == ("MAT101", "2026-1", "G1")


def test_llave_oferta_se_reconstruye_desde_el_id():
    assert claves.llave_oferta("MAT101-2026-1-G1") == {
        "PK": "COURSE#MAT101",
        "SK": "OFFER#2026-1#MAT101-2026-1-G1",
    }


def test_oferta_id_invalido_retorna_none():
    assert claves.partes_oferta("no-es-una-oferta") is None
    assert claves.partes_oferta("MAT101#2026-1#G1") is None
    assert claves.llave_oferta("") is None


# ── Matrícula ─────────────────────────────────────────────────────────

def test_llave_matricula_no_incluye_el_grupo():
    """Una matrícula por estudiante, curso y periodo: el grupo es atributo."""
    llave = claves.llave_matricula("e1", "2026-1", "MAT101")
    assert llave == {"PK": "STUDENT#e1", "SK": "ENROLL#2026-1#MAT101"}


def test_prefijo_matricula_por_periodo_y_total():
    assert claves.prefijo_sk_matricula("2026-1") == "ENROLL#2026-1#"
    assert claves.prefijo_sk_matricula() == "ENROLL#"


# ── LSI de notas ──────────────────────────────────────────────────────

def test_lsi_nota_rellena_con_ceros():
    assert claves.lsi1sk_nota(Decimal("4.50"), "2026-1", "MAT101") == "GRADE#0450#2026-1#MAT101"
    assert claves.lsi1sk_nota(Decimal("0"), "2026-1", "MAT101") == "GRADE#0000#2026-1#MAT101"
    assert claves.lsi1sk_nota(Decimal("5"), "2026-1", "MAT101") == "GRADE#0500#2026-1#MAT101"


def test_lsi_nota_orden_lexicografico_igual_al_numerico():
    notas = [Decimal("3.05"), Decimal("4.9"), Decimal("0.5"), Decimal("5"), Decimal("3.5")]
    llaves = [claves.lsi1sk_nota(n, "2026-1", "X1") for n in notas]
    assert sorted(llaves) == [claves.lsi1sk_nota(n, "2026-1", "X1") for n in sorted(notas)]


# ── GSI sobrecargados ─────────────────────────────────────────────────

def test_gsi1_separa_ofertas_y_matriculas_por_prefijo():
    assert claves.gsi1pk_profesor("p1") == "PROF#p1"
    assert claves.gsi1pk_oferta("MAT101-2026-1-G1") == "OFFER#MAT101-2026-1-G1"
    assert claves.gsi1sk_oferta("2026-1", "MAT101-2026-1-G1").startswith(
        claves.prefijo_gsi1sk_periodo("2026-1")
    )


def test_gsi2_comparte_particion_de_periodo():
    assert claves.gsi2pk_periodo("2026-1") == "PERIOD#2026-1"
    assert claves.gsi2sk_oferta("MAT101", "MAT101-2026-1-G1").startswith("OFFER#")
    pendiente = claves.gsi2sk_pendiente("2026-01-15T10:00:00+00:00", "e1", "MAT101")
    assert pendiente.startswith(claves.PREFIJO_GSI2SK_PENDIENTE)


def test_pendientes_se_ordenan_por_fecha_de_solicitud():
    primera = claves.gsi2sk_pendiente("2026-01-15T10:00:00+00:00", "e9", "MAT101")
    segunda = claves.gsi2sk_pendiente("2026-01-15T10:00:05+00:00", "e1", "MAT101")
    assert primera < segunda


# ── Email y validaciones ──────────────────────────────────────────────

def test_email_se_normaliza():
    assert claves.pk_email("  Ana.Perez@Campus.EXAMPLE ") == "EMAIL#ana.perez@campus.example"


def test_validaciones_de_identificadores():
    assert claves.periodo_valido("2026-1")
    assert not claves.periodo_valido("2026")
    assert not claves.periodo_valido("2026-1#")
    assert claves.curso_valido("MAT101")
    assert not claves.curso_valido("mat-101")
    assert claves.id_usuario_valido("2021114001")
    assert not claves.id_usuario_valido("e1#PROFILE")
    assert claves.email_valido("a@b.co")
    assert not claves.email_valido("sin-arroba")


def test_pk_de_perfil_segun_rol():
    assert claves.pk_usuario(claves.ROL_ESTUDIANTE, "e1") == "STUDENT#e1"
    assert claves.pk_usuario(claves.ROL_PROFESOR, "p1") == "PROF#p1"
    assert claves.pk_usuario(claves.ROL_ADMIN, "a1") == "ADMIN#a1"
