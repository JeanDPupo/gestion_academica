"""
test_auth.py
────────────
Tests de la Lambda /auth: registro con email único, login con
rate limiting, sesiones en Redis y logout.
Usa moto para DynamoDB y fakeredis para Redis.
"""
from comun import claves


def _registro(api, **cambios):
    datos = {
        "rol": "STUDENT", "id": "e1", "nombre": "Ana Pérez",
        "email": "ana@campus.example", "password": "clave-segura-1",
        "programa": "Ingeniería de Sistemas",
    }
    datos.update(cambios)
    return api.post("/auth/registro", datos)


# ── Registro ──────────────────────────────────────────────────────────

def test_registro_crea_perfil_e_item_de_email(api, tabla_dynamodb):
    r = _registro(api)
    assert r.status == 201
    assert r.json["studentId"] == "e1"
    assert "passwordHash" not in r.json and "PK" not in r.json

    perfil = tabla_dynamodb.get_item(Key={"PK": "STUDENT#e1", "SK": "PROFILE"})["Item"]
    login = tabla_dynamodb.get_item(
        Key={"PK": "EMAIL#ana@campus.example", "SK": "LOGIN"}
    )["Item"]
    assert perfil["programa"] == "Ingeniería de Sistemas"
    assert login["userId"] == "e1" and login["rol"] == "STUDENT"
    assert login["passwordHash"] != "clave-segura-1"      # nunca en texto plano


def test_registro_de_profesor_usa_su_propia_particion(api, tabla_dynamodb):
    r = _registro(api, rol="PROFESSOR", id="p1", email="profe@campus.example",
                  departamento="Matemáticas")
    assert r.status == 201
    assert "Item" in tabla_dynamodb.get_item(Key={"PK": "PROF#p1", "SK": "PROFILE"})


def test_email_duplicado_retorna_409_y_no_crea_el_segundo_perfil(api, tabla_dynamodb):
    """La transacción es todo o nada: el perfil de e2 no debe quedar huérfano."""
    assert _registro(api).status == 201
    r = _registro(api, id="e2", email="  ANA@Campus.example ")   # mismo email normalizado
    assert r.status == 409
    assert "Item" not in tabla_dynamodb.get_item(Key={"PK": "STUDENT#e2", "SK": "PROFILE"})


def test_mismo_email_no_puede_ser_estudiante_y_profesor(api):
    assert _registro(api).status == 201
    assert _registro(api, rol="PROFESSOR", id="p1").status == 409


def test_id_duplicado_retorna_409(api):
    assert _registro(api).status == 201
    assert _registro(api, email="otra@campus.example").status == 409


def test_registro_valida_los_datos(api):
    assert _registro(api, email="sin-arroba").status == 400
    assert _registro(api, password="corta").status == 400
    assert _registro(api, id="e1#PROFILE").status == 400
    assert _registro(api, rol="DECANO").status == 400
    assert _registro(api, nombre="").status == 400


def test_registrar_coordinacion_exige_sesion_de_coordinacion(api):
    assert _registro(api, rol="ADMIN", id="a2", email="a2@campus.example").status == 401

    estudiante = api.registrar("STUDENT", "e9")
    r = api.post("/auth/registro", {
        "rol": "ADMIN", "id": "a2", "nombre": "X", "email": "a2@campus.example",
        "password": "clave-segura-1",
    }, token=estudiante)
    assert r.status == 403

    admin = api.registrar("ADMIN", "a1")
    r = api.post("/auth/registro", {
        "rol": "ADMIN", "id": "a2", "nombre": "X", "email": "a2@campus.example",
        "password": "clave-segura-1",
    }, token=admin)
    assert r.status == 201


# ── Login ─────────────────────────────────────────────────────────────

def test_login_correcto_abre_sesion_en_redis(api, redis_fake):
    _registro(api)
    r = api.post("/auth/login", {"email": "Ana@campus.example", "password": "clave-segura-1"})
    assert r.status == 200
    assert r.json["usuario"] == {"userId": "e1", "rol": "STUDENT", "nombre": "Ana Pérez"}
    assert r.json["sesionEnRedis"] is True

    sesiones = redis_fake.keys("sesion:*")
    assert len(sesiones) == 1
    assert 3500 <= redis_fake.ttl(sesiones[0]) <= 3600


def test_login_con_clave_incorrecta_o_email_inexistente_retorna_401(api):
    _registro(api)
    mala = api.post("/auth/login", {"email": "ana@campus.example", "password": "incorrecta"})
    nadie = api.post("/auth/login", {"email": "nadie@campus.example", "password": "x" * 8})
    assert mala.status == nadie.status == 401
    assert mala.json == nadie.json        # el mensaje no revela si el email existe


def test_rate_limiting_bloquea_tras_cinco_intentos(api):
    _registro(api)
    malo = {"email": "ana@campus.example", "password": "incorrecta"}
    assert [api.post("/auth/login", malo).status for _ in range(5)] == [401] * 5
    assert api.post("/auth/login", malo).status == 429
    # Bloqueado incluso con la clave correcta, hasta que expire la ventana
    bueno = {"email": "ana@campus.example", "password": "clave-segura-1"}
    assert api.post("/auth/login", bueno).status == 429


def test_login_exitoso_reinicia_el_contador(api, redis_fake):
    _registro(api)
    api.post("/auth/login", {"email": "ana@campus.example", "password": "incorrecta"})
    api.post("/auth/login", {"email": "ana@campus.example", "password": "clave-segura-1"})
    assert redis_fake.get(claves.rk_limite_login("ana@campus.example")) is None


def test_login_funciona_con_redis_caido(api, redis_caido):
    """Degraded mode: sin rate limiting ni registro de sesión, pero entra."""
    _registro(api)
    r = api.post("/auth/login", {"email": "ana@campus.example", "password": "clave-segura-1"})
    assert r.status == 200
    assert r.json["sesionEnRedis"] is False
    assert api.get("/auth/me", token=r.json["token"]).status == 200


# ── Sesión ────────────────────────────────────────────────────────────

def test_me_devuelve_el_perfil_y_usa_cache(api):
    token = api.registrar("STUDENT", "e1", "Ana Pérez")
    primera = api.get("/auth/me", token=token)
    assert primera.status == 200
    assert primera.json["nombre"] == "Ana Pérez" and primera.json["rol"] == "STUDENT"
    assert primera.json["_fuente"] == "cache"     # el login ya había poblado la caché


def test_me_sin_token_retorna_401(api):
    assert api.get("/auth/me").status == 401


def test_logout_invalida_el_token(api):
    token = api.registrar("STUDENT", "e1")
    assert api.get("/auth/me", token=token).status == 200
    assert api.post("/auth/logout", token=token).status == 200
    assert api.get("/auth/me", token=token).status == 401
