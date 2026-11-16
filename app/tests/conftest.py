"""
conftest.py
───────────
Fixtures compartidos por todos los tests.
Usa moto (mock DynamoDB) y fakeredis (mock Redis)
para que los tests corran sin infraestructura real.
"""
import os
import sys

import boto3
import pytest
from moto import mock_aws

RAIZ_APP: str = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# lambdas/ en el path para importar el paquete `comun` igual que en la Lambda
sys.path.insert(0, os.path.join(RAIZ_APP, "lambdas"))
sys.path.insert(0, os.path.join(RAIZ_APP, "scripts"))
sys.path.insert(0, os.path.dirname(__file__))

# Dentro de cdk-dev, AWS_ENDPOINT_URL apunta al emulador; si se deja,
# boto3 ignora moto y los tests escriben en LocalStack real.
os.environ.pop("AWS_ENDPOINT_URL", None)

# Variables de entorno necesarias antes de importar los módulos
os.environ.setdefault("AWS_ACCESS_KEY_ID",     "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION",    "us-east-1")
os.environ.setdefault("TABLE_NAME",            "test-tabla")
os.environ.setdefault("REDIS_HOST",            "localhost")
os.environ.setdefault("REDIS_PORT",            "6379")
os.environ.setdefault("REDIS_TTL",             "300")
os.environ.setdefault("TOKEN_SECRET",          "secreto-de-pruebas")
# Menos iteraciones de PBKDF2: los tests no necesitan el costo real
os.environ.setdefault("PBKDF2_ITERACIONES",    "1000")


@pytest.fixture
def tabla_dynamodb():
    """
    Crea en memoria (moto) la misma tabla que define el stack CDK:
    PK+SK, LSI1, GSI1 y GSI2. Se destruye al terminar cada test.
    """
    from comun import db
    from esquema import crear_tabla

    with mock_aws():
        db.reiniciar_conexion()
        tabla = crear_tabla(boto3.resource("dynamodb", region_name="us-east-1"), "test-tabla")
        yield tabla
        db.reiniciar_conexion()


@pytest.fixture
def redis_fake():
    """
    Instancia de fakeredis que reemplaza al cliente Redis real.
    Se reinicia automáticamente en cada test.
    """
    import fakeredis
    servidor = fakeredis.FakeRedis(decode_responses=True)
    return servidor


@pytest.fixture(autouse=True)
def parchear_redis(monkeypatch, redis_fake):
    """
    Reemplaza _get_client() en comun/cache.py por fakeredis para que
    todos los tests usen el mock, y deja el circuit breaker cerrado.
    """
    from comun import cache
    monkeypatch.setattr(cache, "_get_client", lambda: redis_fake)
    cache.reiniciar_circuito()
    yield
    cache.reiniciar_circuito()


@pytest.fixture
def redis_caido(monkeypatch):
    """Simula que Redis no responde: cualquier comando lanza ConnectionError."""
    import redis
    from comun import cache

    class RedisRoto:
        def __getattr__(self, nombre):
            def fallar(*args, **kwargs):
                raise redis.ConnectionError("sin conexión")
            return fallar

    monkeypatch.setattr(cache, "_get_client", lambda: RedisRoto())
    cache.reiniciar_circuito()


@pytest.fixture
def api(tabla_dynamodb):
    """Cliente de pruebas que invoca los handlers como lo hace API Gateway."""
    from util import ClienteApi
    return ClienteApi()
