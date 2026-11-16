"""
util.py
───────
Ayudas para los tests: carga de handlers y un cliente que arma eventos
con el formato proxy de API Gateway.
"""
import importlib.util
import json
import os
import re
import sys
from types import ModuleType
from typing import Any

RAIZ_APP: str = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIR_LAMBDAS: str = os.path.join(RAIZ_APP, "lambdas")

_handlers: dict[str, ModuleType] = {}


def cargar_handler(nombre: str) -> ModuleType:
    """
    Importa lambdas/<nombre>/handler.py con un nombre de módulo único.
    Todos los handlers se llaman igual, así que no se pueden importar
    con `import handler`.
    """
    if nombre not in _handlers:
        ruta: str = os.path.join(DIR_LAMBDAS, nombre, "handler.py")
        spec = importlib.util.spec_from_file_location(f"handler_{nombre}", ruta)
        assert spec and spec.loader
        modulo: ModuleType = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = modulo
        spec.loader.exec_module(modulo)
        _handlers[nombre] = modulo
    return _handlers[nombre]


def lambdas_con_rutas() -> list[str]:
    """Lambdas que registran rutas con el Enrutador (todas menos health)."""
    return sorted(
        nombre for nombre in os.listdir(DIR_LAMBDAS)
        if nombre not in ("comun", "health")
        and os.path.isfile(os.path.join(DIR_LAMBDAS, nombre, "handler.py"))
    )


class Respuesta:
    def __init__(self, cruda: dict[str, Any]) -> None:
        self.status: int = cruda["statusCode"]
        self.headers: dict[str, str] = cruda.get("headers", {})
        self.json: dict[str, Any] = json.loads(cruda["body"]) if cruda.get("body") else {}

    def __repr__(self) -> str:
        return f"<Respuesta {self.status} {self.json}>"


class ClienteApi:
    """
    Resuelve (método, ruta) contra las rutas registradas por cada handler
    y lo invoca con un evento como el que entrega API Gateway.
    """

    def __init__(self) -> None:
        self.token: str | None = None

    def _resolver(self, metodo: str, ruta: str) -> tuple[ModuleType, str, dict[str, str]]:
        for nombre in lambdas_con_rutas():
            modulo: ModuleType = cargar_handler(nombre)
            for (m, plantilla) in modulo.rutas._rutas:
                if m != metodo:
                    continue
                patron: str = "^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", plantilla) + "$"
                encontrado = re.match(patron, ruta)
                if encontrado:
                    return modulo, plantilla, encontrado.groupdict()
        raise AssertionError(f"Ninguna Lambda registra {metodo} {ruta}")

    def llamar(
        self,
        metodo: str,
        ruta: str,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
        token: str | None = None,
    ) -> Respuesta:
        modulo, plantilla, params = self._resolver(metodo, ruta)
        cabeceras: dict[str, str] = {"Content-Type": "application/json"}
        # token=None usa el del cliente; token="" envía la petición sin credencial
        credencial: str | None = self.token if token is None else token
        if credencial:
            cabeceras["Authorization"] = f"Bearer {credencial}"
        evento: dict[str, Any] = {
            "httpMethod": metodo,
            "resource": plantilla,
            "path": ruta,
            "pathParameters": params or None,
            "queryStringParameters": query,
            "headers": cabeceras,
            "body": json.dumps(body) if body is not None else None,
        }
        return Respuesta(modulo.main(evento, None))

    def get(self, ruta: str, **kw: Any) -> Respuesta:
        return self.llamar("GET", ruta, **kw)

    def post(self, ruta: str, body: dict[str, Any] | None = None, **kw: Any) -> Respuesta:
        return self.llamar("POST", ruta, body=body or {}, **kw)

    def put(self, ruta: str, body: dict[str, Any] | None = None, **kw: Any) -> Respuesta:
        return self.llamar("PUT", ruta, body=body or {}, **kw)

    def delete(self, ruta: str, **kw: Any) -> Respuesta:
        return self.llamar("DELETE", ruta, **kw)

    # ── Atajos para preparar escenarios ───────────────────────────────

    def registrar(self, rol: str, user_id: str, nombre: str | None = None) -> str:
        """Registra un usuario, inicia sesión y retorna su token."""
        email: str = f"{user_id}@campus.example"
        if rol == "ADMIN":
            self.crear_admin(user_id, email)
        else:
            r = self.post("/auth/registro", {
                "rol": rol, "id": user_id, "nombre": nombre or f"Usuario {user_id}",
                "email": email, "password": "clave-segura-1",
            }, token="")
            assert r.status == 201, r
        r = self.post("/auth/login", {"email": email, "password": "clave-segura-1"}, token="")
        assert r.status == 200, r
        return r.json["token"]

    def crear_admin(self, user_id: str, email: str) -> None:
        """La primera cuenta de coordinación se siembra directo en la tabla."""
        from comun import db
        auth = cargar_handler("auth")
        perfil, login = auth.construir_usuario(
            "ADMIN", user_id, "Coordinación", email, "clave-segura-1", "Registro",
        )
        db.tabla().put_item(Item=perfil)
        db.tabla().put_item(Item=login)

    def crear_curso(self, admin: str, curso_id: str, creditos: int = 3) -> None:
        r = self.post("/cursos", {
            "cursoId": curso_id, "nombre": f"Curso {curso_id}", "creditos": creditos,
        }, token=admin)
        assert r.status == 201, r

    def crear_oferta(
        self, admin: str, curso_id: str, grupo: str, profesor_id: str,
        cupos: int = 2, periodo: str = "2026-1", requiere_aprobacion: bool = True,
    ) -> str:
        r = self.post(f"/cursos/{curso_id}/ofertas", {
            "periodo": periodo, "grupo": grupo, "profesorId": profesor_id,
            "horario": "Lun 8:00-10:00", "cupos": cupos,
            "requiereAprobacion": requiere_aprobacion,
        }, token=admin)
        assert r.status == 201, r
        return r.json["ofertaId"]
