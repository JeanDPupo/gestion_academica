"""
test_usuarios.py
────────────────
Tests de la Lambda /usuarios: perfiles con Cache-Aside y negative caching.
"""
from comun import claves


def test_perfil_estudiante_miss_y_luego_hit(api, redis_fake):
    token = api.registrar("STUDENT", "e1", "Ana Pérez")
    redis_fake.delete(claves.rk_perfil("STUDENT", "e1"))   # forzar el miss

    primera = api.get("/estudiantes/e1", token=token)
    segunda = api.get("/estudiantes/e1", token=token)

    assert primera.status == segunda.status == 200
    assert primera.json["_fuente"] == "dynamodb"
    assert segunda.json["_fuente"] == "cache"
    assert segunda.json["nombre"] == "Ana Pérez"
    assert "PK" not in segunda.json


def test_perfil_cacheado_tiene_ttl_de_15_minutos(api, redis_fake):
    token = api.registrar("STUDENT", "e1")
    api.get("/estudiantes/e1", token=token)
    assert 800 <= redis_fake.ttl(claves.rk_perfil("STUDENT", "e1")) <= 900


def test_estudiante_no_puede_ver_el_perfil_de_otro(api):
    ana = api.registrar("STUDENT", "e1")
    api.registrar("STUDENT", "e2")
    assert api.get("/estudiantes/e2", token=ana).status == 403


def test_profesor_y_coordinacion_ven_perfiles_de_estudiantes(api):
    api.registrar("STUDENT", "e1")
    profe = api.registrar("PROFESSOR", "p1")
    admin = api.registrar("ADMIN", "a1")
    assert api.get("/estudiantes/e1", token=profe).status == 200
    assert api.get("/estudiantes/e1", token=admin).status == 200


def test_perfil_profesor_visible_para_cualquier_autenticado(api):
    api.registrar("PROFESSOR", "p1", "Luis Mendoza")
    estudiante = api.registrar("STUDENT", "e1")
    r = api.get("/profesores/p1", token=estudiante)
    assert r.status == 200 and r.json["nombre"] == "Luis Mendoza"
    assert api.get("/profesores/p1").status == 401


def test_id_inexistente_usa_negative_caching(api, redis_fake, tabla_dynamodb):
    admin = api.registrar("ADMIN", "a1")
    primera = api.get("/estudiantes/fantasma", token=admin)
    assert primera.status == 404
    assert redis_fake.ttl(claves.rk_perfil("STUDENT", "fantasma")) <= 30

    # Mientras viva la marca, la segunda consulta no llega a DynamoDB:
    # aunque el ítem aparezca en la tabla, la respuesta sigue siendo 404.
    tabla_dynamodb.put_item(Item={"PK": "STUDENT#fantasma", "SK": "PROFILE", "nombre": "X"})
    assert api.get("/estudiantes/fantasma", token=admin).status == 404


def test_registrarse_borra_la_marca_negativa(api):
    admin = api.registrar("ADMIN", "a1")
    assert api.get("/estudiantes/e5", token=admin).status == 404
    api.registrar("STUDENT", "e5")
    assert api.get("/estudiantes/e5", token=admin).status == 200


def test_perfil_se_sirve_con_redis_caido(api, redis_caido, tabla_dynamodb):
    from comun import seguridad
    tabla_dynamodb.put_item(Item={
        "PK": "STUDENT#e1", "SK": "PROFILE", "studentId": "e1", "nombre": "Ana",
    })
    token, _ = seguridad.crear_token("e1", "STUDENT", "Ana")
    r = api.get("/estudiantes/e1", token=token)
    assert r.status == 200 and r.json["_fuente"] == "dynamodb"
