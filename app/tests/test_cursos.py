"""
test_cursos.py
──────────────
Tests de la Lambda /cursos: cursos, ofertas, catálogo del periodo
(GSI2) y ofertas de un profesor (GSI1), con Cache-Aside.
"""
import pytest

from comun import claves


@pytest.fixture
def escenario(api):
    """Coordinación, dos profesores y un curso con dos grupos en 2026-1."""
    admin = api.registrar("ADMIN", "a1")
    api.registrar("PROFESSOR", "p1", "Luis Mendoza")
    api.registrar("PROFESSOR", "p2", "Nora Salas")
    api.crear_curso(admin, "MAT101", creditos=4)
    api.crear_oferta(admin, "MAT101", "G1", "p1", cupos=30)
    api.crear_oferta(admin, "MAT101", "G2", "p2", cupos=25)
    return admin


# ── Cursos ────────────────────────────────────────────────────────────

def test_crear_curso_exige_coordinacion(api):
    estudiante = api.registrar("STUDENT", "e1")
    datos = {"cursoId": "MAT101", "nombre": "Cálculo", "creditos": 4}
    assert api.post("/cursos", datos).status == 401
    assert api.post("/cursos", datos, token=estudiante).status == 403


def test_crear_curso_duplicado_retorna_409(api):
    admin = api.registrar("ADMIN", "a1")
    api.crear_curso(admin, "MAT101")
    r = api.post("/cursos", {"cursoId": "MAT101", "nombre": "Otro", "creditos": 3}, token=admin)
    assert r.status == 409


def test_crear_curso_valida_datos(api):
    admin = api.registrar("ADMIN", "a1")
    assert api.post("/cursos", {"cursoId": "mat-101", "nombre": "X", "creditos": 3},
                    token=admin).status == 400
    assert api.post("/cursos", {"cursoId": "MAT101", "nombre": "X", "creditos": "tres"},
                    token=admin).status == 400
    assert api.post("/cursos", {"cursoId": "MAT101", "nombre": "X", "creditos": 0},
                    token=admin).status == 400


# ── Ofertas ───────────────────────────────────────────────────────────

def test_crear_oferta_guarda_llaves_de_tabla_e_indices(escenario, tabla_dynamodb):
    oferta = tabla_dynamodb.get_item(
        Key={"PK": "COURSE#MAT101", "SK": "OFFER#2026-1#MAT101-2026-1-G1"}
    )["Item"]
    assert oferta["GSI1PK"] == "PROF#p1"
    assert oferta["GSI1SK"] == "PERIOD#2026-1#OFFER#MAT101-2026-1-G1"
    assert oferta["GSI2PK"] == "PERIOD#2026-1"
    assert oferta["GSI2SK"] == "OFFER#MAT101#MAT101-2026-1-G1"
    # Desnormalización: nombre del curso, créditos y nombre del profesor
    assert oferta["nombreCurso"] == "Curso MAT101"
    assert oferta["creditos"] == 4
    assert oferta["nombreProfesor"] == "Luis Mendoza"
    assert oferta["cuposDisponibles"] == oferta["cuposTotales"] == 30


def test_crear_oferta_con_curso_o_profesor_inexistente_retorna_404(api, escenario):
    base = {"periodo": "2026-1", "grupo": "G9", "horario": "Lun 8-10", "cupos": 10}
    assert api.post("/cursos/NOEXISTE/ofertas", {**base, "profesorId": "p1"},
                    token=escenario).status == 404
    assert api.post("/cursos/MAT101/ofertas", {**base, "profesorId": "fantasma"},
                    token=escenario).status == 404


def test_crear_oferta_duplicada_retorna_409(api, escenario):
    r = api.post("/cursos/MAT101/ofertas", {
        "periodo": "2026-1", "grupo": "G1", "profesorId": "p1", "horario": "x", "cupos": 5,
    }, token=escenario)
    assert r.status == 409


def test_crear_oferta_valida_periodo_y_cupos(api, escenario):
    base = {"grupo": "G5", "profesorId": "p1", "horario": "x"}
    assert api.post("/cursos/MAT101/ofertas", {**base, "periodo": "2026", "cupos": 5},
                    token=escenario).status == 400
    assert api.post("/cursos/MAT101/ofertas", {**base, "periodo": "2026-1", "cupos": 0},
                    token=escenario).status == 400


# ── Detalle del curso (patrón 6) ──────────────────────────────────────

def test_detalle_curso_trae_curso_y_ofertas_en_una_respuesta(api, escenario):
    r = api.get("/cursos/MAT101")              # público: no exige token
    assert r.status == 200
    assert r.json["curso"]["nombre"] == "Curso MAT101"
    assert [o["grupo"] for o in r.json["ofertas"]] == ["G1", "G2"]
    assert r.json["_fuente"] == "dynamodb"
    assert api.get("/cursos/MAT101").json["_fuente"] == "cache"


def test_detalle_curso_excluye_ofertas_cerradas(api, escenario):
    r = api.put("/ofertas/MAT101-2026-1-G2/estado", {"estado": "CERRADA"}, token=escenario)
    assert r.status == 200
    ofertas = api.get("/cursos/MAT101").json["ofertas"]
    assert [o["ofertaId"] for o in ofertas] == ["MAT101-2026-1-G1"]


def test_detalle_curso_inexistente_retorna_404_con_marca_negativa(api, redis_fake):
    assert api.get("/cursos/FANTASMA").status == 404
    assert redis_fake.ttl(claves.rk_curso("FANTASMA")) <= 30


def test_crear_curso_borra_la_marca_negativa(api):
    admin = api.registrar("ADMIN", "a1")
    assert api.get("/cursos/FIS201").status == 404
    api.crear_curso(admin, "FIS201")
    assert api.get("/cursos/FIS201").status == 200


# ── Catálogo del periodo (patrón 7, GSI2) ─────────────────────────────

def test_catalogo_lista_solo_ofertas_del_periodo(api, escenario):
    api.crear_curso(escenario, "FIS201")
    api.crear_oferta(escenario, "FIS201", "G1", "p1", periodo="2026-1")
    api.crear_oferta(escenario, "FIS201", "G1", "p1", periodo="2026-2")

    r = api.get("/periodos/2026-1/ofertas")
    assert r.status == 200 and r.json["total"] == 3
    # GSI2SK = OFFER#<cursoId>#<ofertaId>: sale ordenado por curso
    assert [o["ofertaId"] for o in r.json["ofertas"]] == [
        "FIS201-2026-1-G1", "MAT101-2026-1-G1", "MAT101-2026-1-G2",
    ]
    assert api.get("/periodos/2026-2/ofertas").json["total"] == 1


def test_catalogo_cache_aside_con_ttl_corto(api, escenario, redis_fake):
    assert api.get("/periodos/2026-1/ofertas").json["_fuente"] == "dynamodb"
    assert api.get("/periodos/2026-1/ofertas").json["_fuente"] == "cache"
    # TTL corto: el catálogo incluye cuposDisponibles, que cambia seguido
    assert 1 <= redis_fake.ttl(claves.rk_catalogo("2026-1")) <= 15


def test_ttl_de_cupos_es_configurable(api, escenario, redis_fake, monkeypatch):
    monkeypatch.setenv("TTL_CUPOS", "5")
    api.get("/periodos/2026-1/ofertas")
    assert 1 <= redis_fake.ttl(claves.rk_catalogo("2026-1")) <= 5


def test_crear_oferta_invalida_el_catalogo(api, escenario):
    assert api.get("/periodos/2026-1/ofertas").json["total"] == 2      # queda en caché
    api.crear_oferta(escenario, "MAT101", "G3", "p1")
    r = api.get("/periodos/2026-1/ofertas")
    assert r.json["total"] == 3 and r.json["_fuente"] == "dynamodb"


def test_catalogo_de_periodo_sin_ofertas_retorna_lista_vacia(api, escenario):
    r = api.get("/periodos/2031-1/ofertas")
    assert r.status == 200 and r.json["ofertas"] == []


def test_catalogo_periodo_invalido_retorna_400(api, escenario):
    assert api.get("/periodos/veintiseis/ofertas").status == 400


# ── Ofertas de un profesor (patrón 8, GSI1) ───────────────────────────

def test_ofertas_del_profesor_filtradas_por_periodo(api, escenario):
    api.crear_oferta(escenario, "MAT101", "G1", "p1", periodo="2026-2")
    p1 = api.post("/auth/login", {
        "email": "p1@campus.example", "password": "clave-segura-1",
    }).json["token"]

    todas = api.get("/profesores/p1/ofertas", token=p1)
    periodo = api.get("/profesores/p1/ofertas", query={"periodo": "2026-1"}, token=p1)
    assert todas.json["total"] == 2
    assert [o["ofertaId"] for o in periodo.json["ofertas"]] == ["MAT101-2026-1-G1"]


def test_profesor_no_ve_las_ofertas_de_otro(api, escenario):
    p1 = api.post("/auth/login", {
        "email": "p1@campus.example", "password": "clave-segura-1",
    }).json["token"]
    assert api.get("/profesores/p2/ofertas", token=p1).status == 403
    assert api.get("/profesores/p2/ofertas", token=escenario).status == 200


# ── Estado de la oferta ───────────────────────────────────────────────

def test_cambiar_estado_valida_y_exige_coordinacion(api, escenario):
    estudiante = api.registrar("STUDENT", "e1")
    ruta = "/ofertas/MAT101-2026-1-G1/estado"
    assert api.put(ruta, {"estado": "CERRADA"}, token=estudiante).status == 403
    assert api.put(ruta, {"estado": "PAUSADA"}, token=escenario).status == 400
    assert api.put("/ofertas/malformada/estado", {"estado": "CERRADA"},
                   token=escenario).status == 400
    assert api.put("/ofertas/MAT101-2026-1-G9/estado", {"estado": "CERRADA"},
                   token=escenario).status == 404
