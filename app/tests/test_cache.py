"""
test_cache.py
─────────────
Tests unitarios del módulo comun/cache.py.
Verifica get / set / delete, Cache-Aside con negative caching,
sesiones, rate limiting, el contador de demanda y el comportamiento
degradado cuando Redis no está disponible.
"""
from comun import cache


# ── cache_set / cache_get ─────────────────────────────────────────────

def test_set_y_get_basico():
    item = {"id": "x1", "nombre": "Test"}
    cache.cache_set("curso:x1", item, ttl=60)
    assert cache.cache_get("curso:x1") == item


def test_get_clave_inexistente_retorna_none():
    assert cache.cache_get("curso:no-existe") is None


def test_set_respeta_ttl(redis_fake):
    cache.cache_set("curso:ttl", {"v": 1}, ttl=10)
    assert 1 <= redis_fake.ttl("curso:ttl") <= 10


def test_set_usa_ttl_de_entorno(monkeypatch, redis_fake):
    # cache_set lee REDIS_TTL en cada llamada, no hace falta recargar el módulo
    monkeypatch.setenv("REDIS_TTL", "120")
    cache.cache_set("curso:env", {"v": 2})
    assert 100 <= redis_fake.ttl("curso:env") <= 120


# ── cache_delete ──────────────────────────────────────────────────────

def test_delete_elimina_varias_claves():
    cache.cache_set("a", {"v": 1}, ttl=60)
    cache.cache_set("b", {"v": 2}, ttl=60)
    assert cache.cache_delete("a", "b") is True
    assert cache.cache_get("a") is None
    assert cache.cache_get("b") is None


def test_delete_clave_inexistente_no_falla():
    assert cache.cache_delete("curso:no-existe") is True


# ── Cache-Aside ───────────────────────────────────────────────────────

def test_cache_aside_miss_carga_y_luego_hit():
    llamadas = []

    def cargar():
        llamadas.append(1)
        return {"nombre": "Cálculo"}

    valor, fuente = cache.cache_aside("curso:MAT101", cargar, ttl=60)
    assert (valor, fuente) == ({"nombre": "Cálculo"}, "dynamodb")

    valor, fuente = cache.cache_aside("curso:MAT101", cargar, ttl=60)
    assert (valor, fuente) == ({"nombre": "Cálculo"}, "cache")
    assert len(llamadas) == 1      # la segunda lectura no tocó la fuente


def test_cache_aside_guarda_lista_vacia_como_valor():
    """Un resultado vacío es un valor válido, no un "no existe"."""
    valor, _ = cache.cache_aside("catalogo:2030-1", lambda: {"ofertas": []}, ttl=60)
    valor, fuente = cache.cache_aside("catalogo:2030-1", lambda: {"ofertas": ["x"]}, ttl=60)
    assert valor == {"ofertas": []}
    assert fuente == "cache"


def test_negative_caching_evita_recargar_ids_inexistentes(redis_fake):
    llamadas = []

    def cargar():
        llamadas.append(1)
        return None

    assert cache.cache_aside("perfil:student:fantasma", cargar, ttl=900) == (None, "dynamodb")
    assert cache.cache_aside("perfil:student:fantasma", cargar, ttl=900) == (None, "cache")
    assert len(llamadas) == 1
    # La marca negativa vive poco: si el recurso se crea, aparece pronto
    assert redis_fake.ttl("perfil:student:fantasma") <= 30


# ── Sesiones ──────────────────────────────────────────────────────────

def test_sesion_guardar_activa_y_cerrar(redis_fake):
    cache.sesion_guardar("sesion:abc", {"userId": "e1"}, ttl=3600)
    assert cache.sesion_activa("sesion:abc") is True
    assert 3500 <= redis_fake.ttl("sesion:abc") <= 3600

    cache.sesion_cerrar("sesion:abc")
    assert cache.sesion_activa("sesion:abc") is False


# ── Rate limiting ─────────────────────────────────────────────────────

def test_limite_permite_hasta_el_maximo_y_luego_bloquea(redis_fake):
    resultados = [cache.limite_excedido("limite:login:a@b.co", 3, 60) for _ in range(5)]
    assert resultados == [False, False, False, True, True]
    assert 1 <= redis_fake.ttl("limite:login:a@b.co") <= 60


def test_limite_reiniciar_borra_el_contador():
    for _ in range(4):
        cache.limite_excedido("limite:login:a@b.co", 3, 60)
    cache.limite_reiniciar("limite:login:a@b.co")
    assert cache.limite_excedido("limite:login:a@b.co", 3, 60) is False


# ── Contador de demanda (Sorted Set) ──────────────────────────────────

def test_demanda_ordena_por_solicitudes():
    for curso, veces in (("MAT101", 3), ("FIS201", 5), ("PRG110", 1)):
        for _ in range(veces):
            cache.demanda_incrementar("demanda:2026-1", curso)

    assert cache.demanda_top("demanda:2026-1", 2) == [("FIS201", 5), ("MAT101", 3)]


def test_demanda_sin_datos_retorna_lista_vacia():
    assert cache.demanda_top("demanda:1999-1", 5) == []


# ── Modo degradado (Redis no disponible) ──────────────────────────────

def test_operaciones_no_explotan_si_redis_falla(redis_caido):
    """Cada función retorna su valor neutro en lugar de lanzar la excepción."""
    assert cache.cache_get("x") is None
    cache.reiniciar_circuito()
    assert cache.cache_set("x", {"v": 1}) is False
    cache.reiniciar_circuito()
    assert cache.cache_delete("x") is False
    cache.reiniciar_circuito()
    assert cache.sesion_activa("sesion:x") is None       # ni True ni False: no se sabe
    cache.reiniciar_circuito()
    assert cache.limite_excedido("limite:x", 1, 60) is False   # fail-open
    cache.reiniciar_circuito()
    assert cache.demanda_incrementar("demanda:x", "MAT101") is False
    cache.reiniciar_circuito()
    assert cache.demanda_top("demanda:x", 5) is None


def test_cache_aside_sigue_sirviendo_desde_la_fuente_si_redis_falla(redis_caido):
    valor, fuente = cache.cache_aside("curso:MAT101", lambda: {"nombre": "Cálculo"})
    assert valor == {"nombre": "Cálculo"}
    assert fuente == "dynamodb"


def test_circuit_breaker_omite_redis_tras_un_fallo(monkeypatch):
    """Después de un fallo no se vuelve a intentar hasta que pase la pausa."""
    import redis

    intentos = []

    class RedisRoto:
        def get(self, key):
            intentos.append(key)
            raise redis.ConnectionError("sin conexión")

    monkeypatch.setattr(cache, "_get_client", lambda: RedisRoto())
    cache.reiniciar_circuito()

    cache.cache_get("a")
    cache.cache_get("b")
    cache.cache_get("c")
    assert intentos == ["a"]          # b y c ni siquiera tocaron la red

    cache.reiniciar_circuito()        # equivale a que pase REDIS_PAUSA_FALLO
    cache.cache_get("d")
    assert intentos == ["a", "d"]


# ── Resolución DNS acotada ────────────────────────────────────────────
#
# Con Redis caído, Docker reenvía el nombre a DNS externos y la
# resolución puede tardar más que el timeout de la Lambda; redis-py
# además reintenta el connect. _ip_de acota ambos caminos.

def test_ip_de_resuelve_y_cachear(monkeypatch):
    import time
    llamadas = []

    def resolver_ok(host):
        llamadas.append(host)
        return "172.20.0.9"

    monkeypatch.setattr(cache.socket, "gethostbyname", resolver_ok)
    monkeypatch.setattr(cache, "_ip_cacheada", None)
    assert cache._ip_de("redis") == "172.20.0.9"
    assert cache._ip_de("redis") == "172.20.0.9"
    assert llamadas == ["redis"]           # la segunda salió de la caché


def test_ip_de_no_se_cuelga_si_el_dns_no_responde(monkeypatch):
    """El techo de resolución manda: falla en ~1 s aunque el DNS tardé más."""
    import time

    def resolver_lento(host):
        time.sleep(5)                      # mucho más que TECHO_RESOLVER_S
        return "10.9.8.7"

    monkeypatch.setattr(cache.socket, "gethostbyname", resolver_lento)
    monkeypatch.setattr(cache, "_ip_cacheada", None)
    t0 = time.monotonic()
    try:
        cache._ip_de("redis")
        raise AssertionError("debió lanzar ConnectionError")
    except cache.redis.ConnectionError:
        pass
    assert time.monotonic() - t0 < 3


def test_ip_de_convierte_dns_roto_en_connection_error(monkeypatch):
    import socket

    def resolver_roto(host):
        raise socket.gaierror(8, "nombre no resuelto")

    monkeypatch.setattr(cache.socket, "gethostbyname", resolver_roto)
    monkeypatch.setattr(cache, "_ip_cacheada", None)
    try:
        cache._ip_de("redis")
        raise AssertionError("debió lanzar ConnectionError")
    except cache.redis.ConnectionError:
        pass


def test_fallo_descarta_cliente_e_ip_para_re_resolver():
    import time
    cache._cliente = object()
    cache._ip_cacheada = ("redis", "10.0.0.5", time.monotonic() + 60)
    cache._registrar_fallo("get", Exception("sin conexión"))
    assert cache._cliente is None
    assert cache._ip_cacheada is None


def test_ping_sonda_reporta_false_sin_abrir_el_circuito(redis_caido):
    assert cache.ping() is False
    assert cache._disponible()             # el breaker queda cerrado
