"""
test_evaluacion.py
──────────────────
Tests de la Lambda /evaluacion: lista de clase (GSI1), cola de
pendientes (GSI2 disperso), aprobación, calificación y notas (LSI1).
"""
import pytest

from comun import claves

G1 = "MAT101-2026-1-G1"
RUTA_E1 = "/estudiantes/e1/matriculas/2026-1/MAT101"


@pytest.fixture
def campus(api):
    """Dos profesores, tres estudiantes y tres cursos con una oferta cada uno."""
    admin = api.registrar("ADMIN", "a1")
    tokens = {"admin": admin}
    for profe in ("p1", "p2"):
        tokens[profe] = api.registrar("PROFESSOR", profe)
    for est, nombre in (("e1", "Ana Pérez"), ("e2", "Juan Gómez"), ("e3", "Carla Ruiz")):
        tokens[est] = api.registrar("STUDENT", est, nombre)
    for curso, creditos, profe in (("MAT101", 4, "p1"), ("FIS201", 3, "p1"), ("PRG110", 2, "p2")):
        api.crear_curso(admin, curso, creditos)
        api.crear_oferta(admin, curso, "G1", profe, cupos=10)
    return tokens


def _matricular(api, campus, estudiante, curso="MAT101"):
    r = api.post("/matriculas", {"ofertaId": f"{curso}-2026-1-G1"}, token=campus[estudiante])
    assert r.status == 201, r


def _aprobar_y_calificar(api, campus, estudiante, curso, nota, profe="p1"):
    ruta = f"/estudiantes/{estudiante}/matriculas/2026-1/{curso}"
    assert api.post(f"{ruta}/aprobar", token=campus[profe]).status == 200
    assert api.put(f"{ruta}/nota", {"nota": nota}, token=campus[profe]).status == 200


# ── Lista de clase (patrones 5 y 12, GSI1) ────────────────────────────

def test_lista_de_clase_sale_del_gsi1_sin_consultar_perfiles(api, campus):
    for est in ("e1", "e2"):
        _matricular(api, campus, est)
    _matricular(api, campus, "e3", "FIS201")       # otra oferta: no debe aparecer

    r = api.get(f"/ofertas/{G1}/estudiantes", token=campus["p1"])
    assert r.status == 200 and r.json["total"] == 2
    assert [(e["studentId"], e["nombreEstudiante"]) for e in r.json["estudiantes"]] == [
        ("e1", "Ana Pérez"), ("e2", "Juan Gómez"),
    ]
    assert r.json["oferta"]["ofertaId"] == G1


def test_solo_el_profesor_de_la_oferta_o_coordinacion_ven_la_lista(api, campus):
    ruta = f"/ofertas/{G1}/estudiantes"
    assert api.get(ruta, token=campus["p2"]).status == 403     # dicta otra oferta
    assert api.get(ruta, token=campus["e1"]).status == 403
    assert api.get(ruta).status == 401
    assert api.get(ruta, token=campus["admin"]).status == 200
    assert api.get("/ofertas/MAT101-2026-1-G9/estudiantes", token=campus["admin"]).status == 404


def test_la_autorizacion_no_depende_de_la_cache(api, campus):
    """Con la lista ya en Redis, otro profesor sigue recibiendo 403."""
    _matricular(api, campus, "e1")
    ruta = f"/ofertas/{G1}/estudiantes"
    assert api.get(ruta, token=campus["p1"]).json["_fuente"] == "dynamodb"
    assert api.get(ruta, token=campus["p1"]).json["_fuente"] == "cache"
    assert api.get(ruta, token=campus["p2"]).status == 403


def test_lista_de_clase_se_invalida_al_matricular_y_al_retirar(api, campus):
    ruta = f"/ofertas/{G1}/estudiantes"
    assert api.get(ruta, token=campus["p1"]).json["total"] == 0        # queda en caché

    _matricular(api, campus, "e1")
    assert api.get(ruta, token=campus["p1"]).json["total"] == 1

    api.delete(RUTA_E1, token=campus["e1"])
    r = api.get(ruta, token=campus["p1"])
    assert r.json["total"] == 0 and r.json["_fuente"] == "dynamodb"


# ── Pendientes (patrón 9, GSI2 disperso) ──────────────────────────────

def test_pendientes_del_periodo_en_orden_de_solicitud(api, campus, tabla_dynamodb):
    # Fechas fijas para no depender del reloj
    for est, fecha in (("e2", "2026-01-15T10:00:00+00:00"), ("e1", "2026-01-15T10:00:07+00:00")):
        _matricular(api, campus, est)
        tabla_dynamodb.update_item(
            Key=claves.llave_matricula(est, "2026-1", "MAT101"),
            UpdateExpression="SET GSI2SK = :sk",
            ExpressionAttributeValues={":sk": claves.gsi2sk_pendiente(fecha, est, "MAT101")},
        )

    r = api.get("/periodos/2026-1/matriculas/pendientes", token=campus["admin"])
    assert r.status == 200
    assert [p["studentId"] for p in r.json["pendientes"]] == ["e2", "e1"]


def test_pendientes_no_incluye_ofertas_del_catalogo(api, campus):
    """Ofertas y pendientes comparten GSI2PK; el prefijo de la SK los separa."""
    r = api.get("/periodos/2026-1/matriculas/pendientes", token=campus["admin"])
    assert r.json["pendientes"] == []
    assert api.get("/periodos/2026-1/ofertas").json["total"] == 3


def test_pendientes_exige_coordinacion(api, campus):
    assert api.get("/periodos/2026-1/matriculas/pendientes", token=campus["p1"]).status == 403


# ── Aprobar ───────────────────────────────────────────────────────────

def test_aprobar_saca_la_matricula_del_indice_de_pendientes(api, campus, tabla_dynamodb):
    _matricular(api, campus, "e1")
    _matricular(api, campus, "e2")

    r = api.post(f"{RUTA_E1}/aprobar", token=campus["p1"])
    assert r.status == 200 and r.json["estado"] == "APROBADA"
    assert r.json["aprobadaPor"] == "p1"

    item = tabla_dynamodb.get_item(Key=claves.llave_matricula("e1", "2026-1", "MAT101"))["Item"]
    assert "GSI2PK" not in item and "GSI2SK" not in item

    pendientes = api.get("/periodos/2026-1/matriculas/pendientes", token=campus["admin"])
    assert [p["studentId"] for p in pendientes.json["pendientes"]] == ["e2"]


def test_aprobar_dos_veces_retorna_409(api, campus):
    _matricular(api, campus, "e1")
    assert api.post(f"{RUTA_E1}/aprobar", token=campus["p1"]).status == 200
    assert api.post(f"{RUTA_E1}/aprobar", token=campus["admin"]).status == 409


def test_aprobar_exige_ser_el_profesor_de_la_oferta(api, campus):
    _matricular(api, campus, "e1")
    assert api.post(f"{RUTA_E1}/aprobar", token=campus["p2"]).status == 403
    assert api.post(f"{RUTA_E1}/aprobar", token=campus["e1"]).status == 403
    assert api.post("/estudiantes/e3/matriculas/2026-1/MAT101/aprobar",
                    token=campus["p1"]).status == 404


# ── Calificar ─────────────────────────────────────────────────────────

def test_calificar_guarda_la_nota_y_la_llave_del_lsi(api, campus, tabla_dynamodb):
    _matricular(api, campus, "e1")
    api.post(f"{RUTA_E1}/aprobar", token=campus["p1"])

    r = api.put(f"{RUTA_E1}/nota", {"nota": 4.5}, token=campus["p1"])
    assert r.status == 200 and r.json["nota"] == 4.5

    item = tabla_dynamodb.get_item(Key=claves.llave_matricula("e1", "2026-1", "MAT101"))["Item"]
    assert item["LSI1SK"] == "GRADE#0450#2026-1#MAT101"


def test_no_se_califica_una_matricula_pendiente(api, campus):
    _matricular(api, campus, "e1")
    assert api.put(f"{RUTA_E1}/nota", {"nota": 4.0}, token=campus["p1"]).status == 409


def test_calificar_valida_el_rango_de_la_nota(api, campus):
    _matricular(api, campus, "e1")
    api.post(f"{RUTA_E1}/aprobar", token=campus["p1"])
    for invalida in (5.1, -0.5, "excelente", None):
        assert api.put(f"{RUTA_E1}/nota", {"nota": invalida}, token=campus["p1"]).status == 400
    assert api.put(f"{RUTA_E1}/nota", {"nota": 5}, token=campus["p1"]).status == 200


def test_calificar_exige_ser_el_profesor_de_la_oferta(api, campus):
    _matricular(api, campus, "e1")
    api.post(f"{RUTA_E1}/aprobar", token=campus["p1"])
    assert api.put(f"{RUTA_E1}/nota", {"nota": 5}, token=campus["p2"]).status == 403
    assert api.put(f"{RUTA_E1}/nota", {"nota": 5}, token=campus["e1"]).status == 403


def test_recalificar_actualiza_la_posicion_en_el_lsi(api, campus, tabla_dynamodb):
    _matricular(api, campus, "e1")
    _aprobar_y_calificar(api, campus, "e1", "MAT101", 2.0)
    api.put(f"{RUTA_E1}/nota", {"nota": 3.75}, token=campus["p1"])
    item = tabla_dynamodb.get_item(Key=claves.llave_matricula("e1", "2026-1", "MAT101"))["Item"]
    assert item["LSI1SK"] == "GRADE#0375#2026-1#MAT101"


def test_matricula_calificada_no_se_retira_ni_cambia_de_grupo(api, campus, tabla_dynamodb):
    api.crear_oferta(campus["admin"], "MAT101", "G2", "p1", cupos=10)
    _matricular(api, campus, "e1")
    _aprobar_y_calificar(api, campus, "e1", "MAT101", 4.5)

    assert api.delete(RUTA_E1, token=campus["e1"]).status == 409
    assert api.put(f"{RUTA_E1}/grupo", {"ofertaId": "MAT101-2026-1-G2"},
                   token=campus["e1"]).status == 409

    item = tabla_dynamodb.get_item(Key=claves.llave_matricula("e1", "2026-1", "MAT101"))["Item"]
    oferta = tabla_dynamodb.get_item(Key=claves.llave_oferta(G1))["Item"]
    assert item["ofertaId"] == G1                  # sigue en su grupo
    assert oferta["cuposDisponibles"] == 9         # el cupo no se devolvió


# ── Notas (patrón 4, LSI1) ────────────────────────────────────────────

def test_notas_ordenadas_de_mayor_a_menor_con_promedio_ponderado(api, campus):
    for curso in ("MAT101", "FIS201", "PRG110"):
        _matricular(api, campus, "e1", curso)
    _aprobar_y_calificar(api, campus, "e1", "MAT101", 3.5)              # 4 créditos
    _aprobar_y_calificar(api, campus, "e1", "FIS201", 4.8)              # 3 créditos
    # PRG110 queda sin nota: no entra al índice disperso

    r = api.get("/estudiantes/e1/notas", token=campus["e1"])
    assert r.status == 200
    assert [(n["cursoId"], n["nota"]) for n in r.json["notas"]] == [
        ("FIS201", 4.8), ("MAT101", 3.5),
    ]
    assert r.json["creditosCalificados"] == 7
    assert r.json["promedio"] == round((3.5 * 4 + 4.8 * 3) / 7, 2)


def test_notas_sin_calificaciones(api, campus):
    r = api.get("/estudiantes/e1/notas", token=campus["e1"])
    assert r.json["notas"] == [] and r.json["promedio"] is None


def test_notas_se_cachean_y_se_invalidan_al_calificar(api, campus):
    _matricular(api, campus, "e1")
    assert api.get("/estudiantes/e1/notas", token=campus["e1"]).json["_fuente"] == "dynamodb"
    assert api.get("/estudiantes/e1/notas", token=campus["e1"]).json["_fuente"] == "cache"

    _aprobar_y_calificar(api, campus, "e1", "MAT101", 4.2)

    r = api.get("/estudiantes/e1/notas", token=campus["e1"])
    assert r.json["_fuente"] == "dynamodb" and r.json["total"] == 1


def test_estudiante_no_ve_las_notas_de_otro(api, campus):
    assert api.get("/estudiantes/e2/notas", token=campus["e1"]).status == 403
