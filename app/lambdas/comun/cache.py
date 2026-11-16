"""
cache.py
────────
Abstracción de Redis para todas las Lambdas.

Principio rector: Redis es una optimización de lectura, nunca la fuente
de verdad. Por eso todas las funciones atrapan `redis.RedisError` y
devuelven un valor neutro: si Redis no está disponible la Lambda sigue
funcionando solo con DynamoDB (degraded mode).

Patrones implementados
  · Cache-Aside            cache_aside()          lecturas de catálogo, perfiles, horario…
  · Negative caching       cache_aside()          ids inexistentes (TTL corto)
  · Invalidación           cache_delete()         tras cada escritura confirmada
  · Session store          sesion_*()             Redis es el almacén principal
  · Rate limiting          limite_excedido()      ventana fija por clave
  · Contador en tiempo real demanda_*()           Sorted Set con ZINCRBY

Circuit breaker
  Si Redis falla, las siguientes llamadas se omiten durante
  REDIS_PAUSA_FALLO segundos. Sin esto, una petición que hace varias
  operaciones de caché pagaría el timeout de conexión una vez por
  operación mientras Redis esté caído.
"""
import json
import logging
import os
import time
from typing import Any, Callable, cast

import redis

logger: logging.Logger = logging.getLogger(__name__)

# Marca que se guarda en caché para "este id no existe" (negative caching)
_NEGATIVO: dict[str, bool] = {"__negativo__": True}

FUENTE_CACHE: str = "cache"
FUENTE_DYNAMODB: str = "dynamodb"

_cliente: redis.Redis | None = None
# Instante (time.monotonic) hasta el cual no se intenta hablar con Redis
_pausado_hasta: float = 0.0


def _get_client() -> redis.Redis:
    """
    Cliente Redis reutilizado entre invocaciones de la Lambda.
    Los timeouts cortos evitan que una caída de Redis consuma el
    timeout de la Lambda.
    """
    global _cliente
    if _cliente is None:
        _cliente = redis.Redis(
            host=os.environ.get("REDIS_HOST", "redis"),
            port=int(os.environ.get("REDIS_PORT", 6379)),
            decode_responses=True,          # retorna str en lugar de bytes
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
    return _cliente


def _ttl_por_defecto() -> int:
    return int(os.environ.get("REDIS_TTL", 300))


# ── Circuit breaker ───────────────────────────────────────────────────

def _disponible() -> bool:
    return time.monotonic() >= _pausado_hasta


def _registrar_fallo(operacion: str, error: Exception) -> None:
    global _pausado_hasta
    pausa: float = float(os.environ.get("REDIS_PAUSA_FALLO", 15))
    _pausado_hasta = time.monotonic() + pausa
    logger.warning("Redis no disponible (%s): %s — se omite %.0fs", operacion, error, pausa)


def reiniciar_circuito() -> None:
    """Vuelve a habilitar Redis de inmediato (usado por los tests)."""
    global _pausado_hasta
    _pausado_hasta = 0.0


# ── Operaciones básicas ───────────────────────────────────────────────

def cache_get(key: str) -> Any | None:
    """
    Busca una clave en Redis.
    Retorna el objeto deserializado o None si no existe / hay error.
    """
    if not _disponible():
        return None
    try:
        # Con decode_responses=True redis-py retorna str, pero su firma
        # declara bytes | str; cast() lo indica al type checker.
        valor: str | None = cast(str | None, _get_client().get(key))
    except redis.RedisError as e:
        _registrar_fallo("get", e)
        return None
    if valor is None:
        logger.info("CACHE MISS key=%s", key)
        return None
    logger.info("CACHE HIT  key=%s", key)
    return json.loads(valor)


def cache_set(key: str, valor: Any, ttl: int | None = None) -> bool:
    """
    Guarda un objeto en Redis con TTL en segundos.
    Retorna True si se guardó correctamente.
    """
    if not _disponible():
        return False
    if ttl is None:
        ttl = _ttl_por_defecto()
    try:
        _get_client().set(key, json.dumps(valor, default=str), ex=ttl)
        logger.info("CACHE SET  key=%s ttl=%ss", key, ttl)
        return True
    except redis.RedisError as e:
        _registrar_fallo("set", e)
        return False


def cache_delete(*keys: str) -> bool:
    """
    Invalida una o varias claves (tras una escritura confirmada en DynamoDB).
    Se borra en vez de actualizar: si dos escrituras concurrentes
    actualizaran la caché podría quedar el valor viejo; al borrar, la
    siguiente lectura repuebla desde la fuente de verdad.
    """
    if not keys:
        return True
    if not _disponible():
        return False
    try:
        _get_client().delete(*keys)
        logger.info("CACHE DEL  keys=%s", ",".join(keys))
        return True
    except redis.RedisError as e:
        _registrar_fallo("delete", e)
        return False


# ── Cache-Aside + negative caching ────────────────────────────────────

def cache_aside(
    key: str,
    cargar: Callable[[], Any | None],
    ttl: int | None = None,
    ttl_negativo: int = 30,
) -> tuple[Any | None, str]:
    """
    Patrón Cache-Aside (lazy loading):
      1. Busca en Redis           → hit: retorna sin tocar DynamoDB
      2. Miss                     → ejecuta `cargar()` (lee DynamoDB)
      3. Guarda el resultado en Redis con TTL y lo retorna

    Si `cargar()` retorna None (el recurso no existe) se guarda una marca
    negativa con TTL corto: consultas repetidas a ids inexistentes no
    vuelven a golpear DynamoDB.

    Retorna (valor, fuente) con fuente = "cache" | "dynamodb".
    """
    en_cache: Any | None = cache_get(key)
    if en_cache is not None:
        if en_cache == _NEGATIVO:
            return None, FUENTE_CACHE
        return en_cache, FUENTE_CACHE

    valor: Any | None = cargar()
    if valor is None:
        cache_set(key, _NEGATIVO, ttl_negativo)
    else:
        cache_set(key, valor, ttl)
    return valor, FUENTE_DYNAMODB


# ── Sesiones (Redis como almacén principal) ───────────────────────────

def sesion_guardar(key: str, datos: dict[str, Any], ttl: int) -> bool:
    return cache_set(key, datos, ttl)


def sesion_activa(key: str) -> bool | None:
    """
    True  → la sesión existe en Redis
    False → Redis respondió y la sesión no existe (logout o expirada)
    None  → Redis no disponible: quien llama decide (degraded mode)
    """
    if not _disponible():
        return None
    try:
        return bool(_get_client().exists(key))
    except redis.RedisError as e:
        _registrar_fallo("exists", e)
        return None


def sesion_cerrar(key: str) -> bool:
    return cache_delete(key)


# ── Rate limiting (ventana fija) ──────────────────────────────────────

def limite_excedido(key: str, maximo: int, ventana_seg: int) -> bool:
    """
    Cuenta un intento y dice si se superó `maximo` dentro de la ventana.
    INCR es atómico; el TTL se fija en el primer intento de la ventana.
    Si Redis no está disponible no se limita (fail-open): se prefiere
    dejar entrar a un usuario legítimo que tumbar el login.
    """
    if not _disponible():
        return False
    try:
        cliente: redis.Redis = _get_client()
        intentos: int = cast(int, cliente.incr(key))
        if intentos == 1:
            cliente.expire(key, ventana_seg)
        return intentos > maximo
    except redis.RedisError as e:
        _registrar_fallo("incr", e)
        return False


def limite_reiniciar(key: str) -> bool:
    return cache_delete(key)


# ── Contador de demanda (Sorted Set) ──────────────────────────────────

def demanda_incrementar(key: str, miembro: str) -> bool:
    """ZINCRBY: suma 1 a la demanda de un curso. Dato no crítico."""
    if not _disponible():
        return False
    try:
        _get_client().zincrby(key, 1, miembro)
        return True
    except redis.RedisError as e:
        _registrar_fallo("zincrby", e)
        return False


def demanda_top(key: str, cantidad: int) -> list[tuple[str, int]] | None:
    """
    ZREVRANGE WITHSCORES: los `cantidad` miembros con mayor puntaje.
    Retorna None si Redis no está disponible.
    """
    if not _disponible():
        return None
    try:
        filas: list[tuple[str, float]] = cast(
            list[tuple[str, float]],
            _get_client().zrevrange(key, 0, cantidad - 1, withscores=True),
        )
        return [(miembro, int(puntaje)) for miembro, puntaje in filas]
    except redis.RedisError as e:
        _registrar_fallo("zrevrange", e)
        return None
