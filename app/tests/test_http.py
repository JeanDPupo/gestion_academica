"""
test_http.py
────────────
Tests del enrutador y de las utilidades HTTP compartidas.
"""
import json

from comun.http import Enrutador, ErrorApi, leer_json, respuesta, cabecera

rutas = Enrutador()


@rutas.ruta("GET", "/cursos/{cursoId}")
def _detalle(event):
    return respuesta(200, {"cursoId": event["pathParameters"]["cursoId"]})


@rutas.ruta("POST", "/cursos")
def _crear(event):
    datos = leer_json(event)
    if "nombre" not in datos:
        raise ErrorApi(400, "falta nombre")
    return respuesta(201, datos)


@rutas.ruta("GET", "/explota")
def _explota(event):
    raise RuntimeError("detalle interno que no debe salir al cliente")


def test_despacha_por_resource_y_metodo():
    r = rutas.despachar({
        "httpMethod": "GET", "resource": "/cursos/{cursoId}",
        "pathParameters": {"cursoId": "MAT101"},
    })
    assert r["statusCode"] == 200
    assert json.loads(r["body"]) == {"cursoId": "MAT101"}


def test_despacha_por_path_si_el_evento_no_trae_resource():
    r = rutas.despachar({"httpMethod": "GET", "path": "/cursos/FIS201"})
    assert json.loads(r["body"]) == {"cursoId": "FIS201"}


def test_metodo_no_registrado_retorna_405():
    r = rutas.despachar({"httpMethod": "DELETE", "resource": "/cursos", "path": "/cursos"})
    assert r["statusCode"] == 405


def test_options_responde_preflight_cors():
    r = rutas.despachar({"httpMethod": "OPTIONS", "resource": "/cursos"})
    assert r["statusCode"] == 204
    assert r["headers"]["Access-Control-Allow-Origin"] == "*"
    assert "Authorization" in r["headers"]["Access-Control-Allow-Headers"]


def test_error_api_se_traduce_a_su_status():
    r = rutas.despachar({"httpMethod": "POST", "resource": "/cursos", "body": "{}"})
    assert r["statusCode"] == 400
    assert json.loads(r["body"]) == {"error": "falta nombre"}


def test_json_invalido_retorna_400():
    r = rutas.despachar({"httpMethod": "POST", "resource": "/cursos", "body": "no es json {{{"})
    assert r["statusCode"] == 400


def test_excepcion_no_controlada_retorna_500_sin_filtrar_detalles():
    r = rutas.despachar({"httpMethod": "GET", "resource": "/explota"})
    assert r["statusCode"] == 500
    assert "detalle interno" not in r["body"]


def test_todas_las_respuestas_llevan_cors():
    r = rutas.despachar({"httpMethod": "GET", "resource": "/explota"})
    assert r["headers"]["Access-Control-Allow-Origin"] == "*"


def test_cabecera_no_distingue_mayusculas():
    assert cabecera({"headers": {"AUTHORIZATION": "Bearer x"}}, "Authorization") == "Bearer x"
    assert cabecera({"headers": None}, "Authorization") is None
