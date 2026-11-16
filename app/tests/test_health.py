"""
test_health.py
──────────────
Tests de la Lambda /health.
"""
import json

from util import cargar_handler


def _health(monkeypatch, redis_ok: bool):
    handler = cargar_handler("health")
    estado = {"estado": "ok", "host": "redis"} if redis_ok else {"estado": "error", "detalle": "x"}
    monkeypatch.setattr(handler, "_check_redis", lambda: estado)
    r = handler.main({"httpMethod": "GET"}, None)
    return r["statusCode"], json.loads(r["body"])


def test_health_ok_con_dynamodb_y_redis(tabla_dynamodb, monkeypatch):
    status, cuerpo = _health(monkeypatch, redis_ok=True)
    assert status == 200 and cuerpo["estado"] == "ok"
    assert cuerpo["dynamodb"]["tabla"] == "test-tabla"


def test_health_degradado_si_solo_falla_redis(tabla_dynamodb, monkeypatch):
    """Redis es una optimización: sin él el servicio sigue respondiendo."""
    status, cuerpo = _health(monkeypatch, redis_ok=False)
    assert status == 200 and cuerpo["estado"] == "degradado"


def test_health_503_si_falla_dynamodb(monkeypatch):
    """Sin tabla (fuente de verdad) no hay servicio."""
    from moto import mock_aws
    with mock_aws():
        status, cuerpo = _health(monkeypatch, redis_ok=True)
    assert status == 503 and cuerpo["estado"] == "error"
