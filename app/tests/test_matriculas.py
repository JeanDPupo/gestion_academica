"""
test_matriculas.py
──────────────────
Tests de la Lambda /matriculas: transacciones de matrícula, retiro y
cambio de grupo, consulta del horario y ranking de demanda.
Usa moto para DynamoDB y fakeredis para Redis.
"""
import pytest

from comun import claves

G1 = "MAT101-2026-1-G1"
G2 = "MAT101-2026-1-G2"


@pytest.fixture
def campus(api):
    """
    Coordinación, un profesor, tres estudiantes y MAT101 con dos grupos:
    G1 con 2 cupos y G2 con 1 cupo.
    """
    admin = api.registrar("ADMIN", "a1")
    api.registrar("PROFESSOR", "p1", "Luis Mendoza")
    tokens = {
        "admin": admin,
        "p1": api.post("/auth/login", {
            "email": "p1@campus.example", "password": "clave-segura-1",
        }).json["token"],
        "e1": api.registrar("STUDENT", "e1", "Ana Pérez"),
        "e2": api.registrar("STUDENT", "e2", "Juan Gómez"),
        "e3": api.registrar("STUDENT", "e3", "Carla Ruiz"),
    }
    api.crear_curso(admin, "MAT101", creditos=4)
    api.crear_oferta(admin, "MAT101", "G1", "p1", cupos=2)
    api.crear_oferta(admin, "MAT101", "G2", "p1", cupos=1)
    return tokens


def _cupos(tabla, id_oferta):
    return tabla.get_item(Key=claves.llave_oferta(id_oferta))["Item"]["cuposDisponibles"]


def _matricula(tabla, student_id, curso="MAT101", periodo="2026-1"):
    return tabla.get_item(Key=claves.llave_matricula(student_id, periodo, curso)).get("Item")


# ── Matricular ────────────────────────────────────────────────────────

def test_matricular_crea_la_matricula_y_descuenta_el_cupo(api, campus, tabla_dynamodb):
    r = api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"])
    assert r.status == 201
    assert r.json["estado"] == "PENDIENTE"
    assert r.json["nombreCurso"] == "Curso MAT101" and r.json["creditos"] == 4

    item = _matricula(tabla_dynamodb, "e1")
    assert item["ofertaId"] == G1                      # el grupo es un atributo
    assert item["GSI1PK"] == f"OFFER#{G1}" and item["GSI1SK"] == "STUDENT#e1"
    assert item["GSI2PK"] == "PERIOD#2026-1" and item["GSI2SK"].startswith("PENDING#")
    assert item["nombreEstudiante"] == "Ana Pérez"     # desnormalizado
    assert "LSI1SK" not in item                        # sin nota no entra al LSI
    assert _cupos(tabla_dynamodb, G1) == 1


def test_no_se_puede_matricular_dos_veces_el_mismo_curso(api, campus, tabla_dynamodb):
    """Ni en el mismo grupo ni en otro: la llave no incluye el grupo."""
    assert api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"]).status == 201
    assert api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"]).status == 409
    assert api.post("/matriculas", {"ofertaId": G2}, token=campus["e1"]).status == 409
    # La transacción fallida no tocó ningún cupo
    assert _cupos(tabla_dynamodb, G1) == 1
    assert _cupos(tabla_dynamodb, G2) == 1


def test_sin_cupo_retorna_409_y_no_crea_la_matricula(api, campus, tabla_dynamodb):
    assert api.post("/matriculas", {"ofertaId": G2}, token=campus["e1"]).status == 201
    r = api.post("/matriculas", {"ofertaId": G2}, token=campus["e2"])
    assert r.status == 409
    assert _matricula(tabla_dynamodb, "e2") is None    # todo o nada
    assert _cupos(tabla_dynamodb, G2) == 0             # nunca negativo


def test_oferta_cerrada_no_admite_matriculas(api, campus, tabla_dynamodb):
    api.put(f"/ofertas/{G1}/estado", {"estado": "CERRADA"}, token=campus["admin"])
    assert api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"]).status == 409
    assert _cupos(tabla_dynamodb, G1) == 2


def test_matricular_valida_oferta_y_rol(api, campus):
    assert api.post("/matriculas", {"ofertaId": G1}).status == 401
    assert api.post("/matriculas", {"ofertaId": G1}, token=campus["p1"]).status == 403
    assert api.post("/matriculas", {"ofertaId": "malformada"}, token=campus["e1"]).status == 400
    assert api.post("/matriculas", {"ofertaId": "MAT101-2026-1-G9"},
                    token=campus["e1"]).status == 404


def test_estudiante_siempre_se_matricula_a_si_mismo(api, campus, tabla_dynamodb):
    """Un studentId ajeno en el cuerpo se ignora: manda la sesión."""
    r = api.post("/matriculas", {"ofertaId": G1, "studentId": "e2"}, token=campus["e1"])
    assert r.status == 201 and r.json["studentId"] == "e1"
    assert _matricula(tabla_dynamodb, "e2") is None


def test_coordinacion_matricula_a_un_estudiante(api, campus):
    r = api.post("/matriculas", {"ofertaId": G1, "studentId": "e2"}, token=campus["admin"])
    assert r.status == 201 and r.json["studentId"] == "e2"
    r = api.post("/matriculas", {"ofertaId": G1, "studentId": "fantasma"}, token=campus["admin"])
    assert r.status == 404


def test_oferta_sin_aprobacion_nace_aprobada_y_fuera_de_gsi2(api, campus, tabla_dynamodb):
    api.crear_curso(campus["admin"], "DEP100")
    libre = api.crear_oferta(campus["admin"], "DEP100", "G1", "p1", requiere_aprobacion=False)
    r = api.post("/matriculas", {"ofertaId": libre}, token=campus["e1"])
    assert r.json["estado"] == "APROBADA"
    assert "GSI2PK" not in _matricula(tabla_dynamodb, "e1", "DEP100")


# ── Horario del estudiante (patrón 3) ─────────────────────────────────

def test_horario_por_periodo_e_historial_completo(api, campus):
    api.crear_curso(campus["admin"], "FIS201", creditos=3)
    api.crear_oferta(campus["admin"], "FIS201", "G1", "p1", periodo="2026-2")
    api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"])
    api.post("/matriculas", {"ofertaId": "FIS201-2026-2-G1"}, token=campus["e1"])

    periodo = api.get("/estudiantes/e1/matriculas", query={"periodo": "2026-1"}, token=campus["e1"])
    assert periodo.status == 200
    assert [m["cursoId"] for m in periodo.json["matriculas"]] == ["MAT101"]
    assert periodo.json["creditos"] == 4

    todo = api.get("/estudiantes/e1/matriculas", token=campus["e1"])
    assert [m["periodo"] for m in todo.json["matriculas"]] == ["2026-1", "2026-2"]
    assert todo.json["creditos"] == 7


def test_horario_se_cachea_y_se_invalida_al_matricular(api, campus):
    ruta, q = "/estudiantes/e1/matriculas", {"periodo": "2026-1"}
    assert api.get(ruta, query=q, token=campus["e1"]).json["_fuente"] == "dynamodb"
    assert api.get(ruta, query=q, token=campus["e1"]).json["_fuente"] == "cache"

    api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"])

    r = api.get(ruta, query=q, token=campus["e1"])
    assert r.json["_fuente"] == "dynamodb" and r.json["total"] == 1


def test_estudiante_no_ve_el_horario_de_otro(api, campus):
    assert api.get("/estudiantes/e2/matriculas", token=campus["e1"]).status == 403
    assert api.get("/estudiantes/e2/matriculas", token=campus["admin"]).status == 200


# ── Retirar ───────────────────────────────────────────────────────────

def test_retirar_borra_la_matricula_y_devuelve_el_cupo(api, campus, tabla_dynamodb):
    api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"])
    r = api.delete("/estudiantes/e1/matriculas/2026-1/MAT101", token=campus["e1"])
    assert r.status == 200
    assert _matricula(tabla_dynamodb, "e1") is None
    assert _cupos(tabla_dynamodb, G1) == 2


def test_tras_retirar_se_puede_volver_a_matricular(api, campus):
    api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"])
    api.delete("/estudiantes/e1/matriculas/2026-1/MAT101", token=campus["e1"])
    assert api.post("/matriculas", {"ofertaId": G2}, token=campus["e1"]).status == 201


def test_retirar_matricula_inexistente_no_infla_los_cupos(api, campus, tabla_dynamodb):
    r = api.delete("/estudiantes/e1/matriculas/2026-1/MAT101", token=campus["e1"])
    assert r.status == 404
    assert _cupos(tabla_dynamodb, G1) == 2


def test_retirar_exige_ser_dueno_profesor_de_la_oferta_o_coordinacion(api, campus):
    api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"])
    ruta = "/estudiantes/e1/matriculas/2026-1/MAT101"
    assert api.delete(ruta, token=campus["e2"]).status == 403
    # El profesor de la oferta puede rechazar la solicitud
    assert api.delete(ruta, token=campus["p1"]).status == 200


# ── Cambiar de grupo ──────────────────────────────────────────────────

def test_cambiar_de_grupo_mueve_cupos_y_actualiza_gsi1(api, campus, tabla_dynamodb):
    api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"])
    r = api.put("/estudiantes/e1/matriculas/2026-1/MAT101/grupo",
                {"ofertaId": G2}, token=campus["e1"])
    assert r.status == 200 and r.json["ofertaId"] == G2

    item = _matricula(tabla_dynamodb, "e1")
    assert item["ofertaId"] == G2 and item["grupo"] == "G2"
    assert item["GSI1PK"] == f"OFFER#{G2}"         # pasa a la lista de clase de G2
    assert item["SK"] == "ENROLL#2026-1#MAT101"    # sigue siendo la misma matrícula
    assert _cupos(tabla_dynamodb, G1) == 2
    assert _cupos(tabla_dynamodb, G2) == 0


def test_cambiar_a_grupo_sin_cupo_no_modifica_nada(api, campus, tabla_dynamodb):
    api.post("/matriculas", {"ofertaId": G2}, token=campus["e2"])     # llena G2
    api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"])
    r = api.put("/estudiantes/e1/matriculas/2026-1/MAT101/grupo",
                {"ofertaId": G2}, token=campus["e1"])
    assert r.status == 409
    assert _matricula(tabla_dynamodb, "e1")["ofertaId"] == G1
    assert _cupos(tabla_dynamodb, G1) == 1 and _cupos(tabla_dynamodb, G2) == 0


def test_cambiar_de_grupo_valida_curso_periodo_y_grupo_actual(api, campus):
    api.crear_curso(campus["admin"], "FIS201")
    otra = api.crear_oferta(campus["admin"], "FIS201", "G1", "p1")
    api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"])
    ruta = "/estudiantes/e1/matriculas/2026-1/MAT101/grupo"

    assert api.put(ruta, {"ofertaId": otra}, token=campus["e1"]).status == 400   # otro curso
    assert api.put(ruta, {"ofertaId": G1}, token=campus["e1"]).status == 409     # mismo grupo
    assert api.put(ruta, {"ofertaId": G2}, token=campus["e2"]).status == 403     # no es suya
    assert api.put("/estudiantes/e3/matriculas/2026-1/MAT101/grupo",
                   {"ofertaId": G2}, token=campus["e3"]).status == 404           # sin matrícula


# ── Demanda (Sorted Set en Redis) ─────────────────────────────────────

def test_ranking_de_demanda_cuenta_solicitudes_incluso_sin_cupo(api, campus):
    api.crear_curso(campus["admin"], "FIS201")
    fis = api.crear_oferta(campus["admin"], "FIS201", "G1", "p1", cupos=5)
    api.post("/matriculas", {"ofertaId": G2}, token=campus["e1"])       # MAT101 +1
    api.post("/matriculas", {"ofertaId": G2}, token=campus["e2"])       # sin cupo: +1
    api.post("/matriculas", {"ofertaId": G1}, token=campus["e3"])       # +1
    api.post("/matriculas", {"ofertaId": fis}, token=campus["e1"])      # FIS201 +1
    api.post("/matriculas", {"ofertaId": fis}, token=campus["e1"])      # duplicada: no cuenta

    r = api.get("/periodos/2026-1/demanda")
    assert r.status == 200 and r.json["disponible"] is True
    assert r.json["ranking"] == [
        {"posicion": 1, "cursoId": "MAT101", "solicitudes": 3},
        {"posicion": 2, "cursoId": "FIS201", "solicitudes": 1},
    ]
    assert len(api.get("/periodos/2026-1/demanda", query={"top": "1"}).json["ranking"]) == 1


# ── Modo degradado ────────────────────────────────────────────────────

def test_matricular_funciona_con_redis_caido(api, campus, tabla_dynamodb, redis_caido):
    """La escritura es de DynamoDB: sin Redis solo se pierde la métrica."""
    r = api.post("/matriculas", {"ofertaId": G1}, token=campus["e1"])
    assert r.status == 201
    assert _cupos(tabla_dynamodb, G1) == 1

    horario = api.get("/estudiantes/e1/matriculas", token=campus["e1"])
    assert horario.status == 200 and horario.json["_fuente"] == "dynamodb"

    ranking = api.get("/periodos/2026-1/demanda")
    assert ranking.status == 200 and ranking.json["disponible"] is False
