#!/usr/bin/env python3
"""
servidor_local.py
─────────────────
Modo simulación: levanta el API y el frontend en un solo proceso, SIN
Docker, usando moto (DynamoDB en memoria) y fakeredis (Redis en memoria).

Para qué sirve
  · Probar cambios en segundos mientras se desarrolla.
  · Plan B de la demo si el emulador no levanta en el equipo de la
    sustentación.

Qué NO es
  No reemplaza el despliegue con CDK en LocalStack, que es el entregable:
  aquí no hay API Gateway, ni Lambdas, ni contenedores. Los handlers son
  exactamente los mismos; lo simulado es la infraestructura.

Uso (desde la carpeta app/, con las dependencias de requirements.txt):
    python scripts/servidor_local.py              # http://localhost:8000
    python scripts/servidor_local.py --puerto 9000 --sin-datos
"""
import argparse
import json
import mimetypes
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qsl, urlsplit

RAIZ_APP: str = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIR_FRONTEND: str = os.path.abspath(os.path.join(RAIZ_APP, "..", "frontend"))
sys.path.insert(0, os.path.join(RAIZ_APP, "lambdas"))
sys.path.insert(0, os.path.dirname(__file__))

os.environ.pop("AWS_ENDPOINT_URL", None)       # que boto3 no busque el emulador
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("TABLE_NAME", "gestion-academica-local")

PREFIJO_API: str = "/api"
LAMBDAS: tuple[str, ...] = ("auth", "usuarios", "cursos", "matriculas", "evaluacion")

# (método, patrón compilado, plantilla, módulo handler)
_tabla_rutas: list[tuple[str, re.Pattern[str], str, Any]] = []
_health: Any = None
# Durante la carga de datos el seed ya imprime cada llamada
registrar_peticiones: bool = True


def _cargar(nombre: str) -> Any:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        f"handler_{nombre}", os.path.join(RAIZ_APP, "lambdas", nombre, "handler.py"),
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def preparar_infraestructura() -> None:
    """Inicia moto, crea la tabla y conecta fakeredis a comun/cache.py."""
    global _health
    import boto3
    import fakeredis
    from moto import mock_aws

    from comun import cache
    from esquema import crear_tabla

    mock_aws().start()
    crear_tabla(boto3.resource("dynamodb"), os.environ["TABLE_NAME"])

    redis_falso = fakeredis.FakeRedis(decode_responses=True)
    cache._get_client = lambda: redis_falso

    for nombre in LAMBDAS:
        modulo = _cargar(nombre)
        for (metodo, plantilla) in modulo.rutas._rutas:
            patron = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", plantilla) + "/?$")
            _tabla_rutas.append((metodo, patron, plantilla, modulo))

    _health = _cargar("health")
    _health._check_redis = lambda: {"estado": "ok", "host": "fakeredis (simulación)"}


class Peticion(BaseHTTPRequestHandler):
    server_version = "GestionAcademicaLocal/1.0"

    def log_message(self, formato: str, *args: Any) -> None:    # silencia el log por defecto
        pass

    # ── API ───────────────────────────────────────────────────────────

    def _evento(self, ruta: str, plantilla: str | None, params: dict[str, str]) -> dict[str, Any]:
        url = urlsplit(self.path)
        largo: int = int(self.headers.get("Content-Length") or 0)
        return {
            "httpMethod": self.command,
            "resource": plantilla,
            "path": ruta,
            "pathParameters": params or None,
            "queryStringParameters": dict(parse_qsl(url.query)) or None,
            "headers": dict(self.headers.items()),
            "body": self.rfile.read(largo).decode() if largo else None,
        }

    def _invocar(self, ruta: str) -> dict[str, Any]:
        if ruta.rstrip("/") == "/health":
            return _health.main(self._evento(ruta, "/health", {}), None)
        candidatos = [
            (m, patron.match(ruta), plantilla, modulo)
            for (m, patron, plantilla, modulo) in _tabla_rutas
        ]
        for metodo, encontrado, plantilla, modulo in candidatos:
            if encontrado and (metodo == self.command or self.command == "OPTIONS"):
                return modulo.main(self._evento(ruta, plantilla, encontrado.groupdict()), None)
        existe: bool = any(encontrado for _, encontrado, _, _ in candidatos)
        return {
            "statusCode": 405 if existe else 404,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Ruta o método no soportado"}),
        }

    # ── Frontend ──────────────────────────────────────────────────────

    def _estatico(self, ruta: str) -> None:
        if ruta == "/config.js":
            self._enviar(200, {"Content-Type": "application/javascript"},
                         f'window.API_BASE = "{PREFIJO_API}";\n'
                         'window.MODO_SIMULACION = true;\n')
            return
        relativo: str = "index.html" if ruta in ("", "/") else ruta.lstrip("/")
        archivo: str = os.path.abspath(os.path.join(DIR_FRONTEND, relativo))
        if not archivo.startswith(DIR_FRONTEND + os.sep) or not os.path.isfile(archivo):
            self._enviar(404, {"Content-Type": "text/plain"}, "No encontrado")
            return
        tipo: str = mimetypes.guess_type(archivo)[0] or "application/octet-stream"
        with open(archivo, "rb") as f:
            self._enviar(200, {"Content-Type": tipo, "Cache-Control": "no-store"}, f.read())

    def _enviar(self, status: int, cabeceras: dict[str, str], cuerpo: str | bytes) -> None:
        datos: bytes = cuerpo.encode() if isinstance(cuerpo, str) else cuerpo
        self.send_response(status)
        for clave, valor in cabeceras.items():
            self.send_header(clave, valor)
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _atender(self) -> None:
        ruta: str = urlsplit(self.path).path
        if ruta == PREFIJO_API or ruta.startswith(PREFIJO_API + "/"):
            r = self._invocar(ruta[len(PREFIJO_API):] or "/")
            if registrar_peticiones:
                print(f"  {r['statusCode']}  {self.command:<7} {self.path}")
            self._enviar(r["statusCode"], r.get("headers", {}), r.get("body") or "")
        elif self.command == "GET":
            self._estatico(ruta)
        else:
            self._enviar(404, {"Content-Type": "text/plain"}, "No encontrado")

    do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = _atender


def main() -> None:
    parser = argparse.ArgumentParser(description="API + frontend en modo simulación (sin Docker)")
    parser.add_argument("--puerto", type=int, default=8000)
    parser.add_argument("--sin-datos", action="store_true", help="No cargar los datos de demo")
    args = parser.parse_args()

    preparar_infraestructura()
    servidor = ThreadingHTTPServer(("0.0.0.0", args.puerto), Peticion)
    base: str = f"http://localhost:{args.puerto}"

    if not args.sin_datos:
        import boto3
        import seed
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        global registrar_peticiones
        registrar_peticiones = False
        seed.sembrar_admin(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))
        cliente = seed.Api(base + PREFIJO_API)
        seed.sembrar_por_api(cliente)
        registrar_peticiones = True
        if cliente.fallos:
            sys.exit(f"✗ {cliente.fallos} llamadas del seed fallaron")
        print(f"\nContraseña de todas las cuentas de demo: {seed.CLAVE_DEMO}")
        print(f"MODO SIMULACIÓN (moto + fakeredis) — frontend: {base}  ·  API: {base}{PREFIJO_API}")
        print("Ctrl+C para detener.\n")
        try:
            hilo.join()
        except KeyboardInterrupt:
            pass
        return

    print(f"MODO SIMULACIÓN (moto + fakeredis) — frontend: {base}  ·  API: {base}{PREFIJO_API}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
