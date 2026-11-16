#!/usr/bin/env python3
"""
seed.py
───────
Carga los datos de la demo y, de paso, prueba el API de punta a punta.

Qué hace
  1. Ubica el API desplegado en el emulador y la tabla DynamoDB.
  2. Siembra la cuenta de coordinación directamente en la tabla (es la
     única que no se puede crear por el API: registrar un ADMIN exige
     la sesión de otro ADMIN).
  3. Crea todo lo demás llamando al API, como lo haría el frontend:
     profesores, estudiantes, cursos, ofertas, matrículas, aprobaciones
     y notas. Cada llamada verifica el código HTTP esperado.
  4. Escribe frontend/config.js con la URL del API para el navegador.

Uso (dentro del contenedor cdk-dev, después de `cdklocal deploy`):
    python scripts/seed.py

Es idempotente: si los datos ya existen (409) continúa.
Con --api <url> usa esa URL en vez de buscar el API en el emulador.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

RAIZ_APP: str = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ_APP, "lambdas"))

NOMBRE_STACK: str = "GestionAcademicaStack"
NOMBRE_API: str = "GestionAcademica-API"
CLAVE_DEMO: str = "Demo2026*"
PERIODO: str = "2026-1"
PERIODO_ANTERIOR: str = "2025-2"

ADMIN: dict[str, str] = {
    "id": "coord1", "nombre": "Coordinación Académica",
    "email": "coordinacion@campus.example", "dependencia": "Registro y Control",
}

PROFESORES: list[dict[str, str]] = [
    {"id": "P1001", "nombre": "Luis Mendoza", "email": "luis.mendoza@campus.example", "departamento": "Matemáticas"},
    {"id": "P1002", "nombre": "Nora Salas", "email": "nora.salas@campus.example", "departamento": "Ingeniería de Sistemas"},
    {"id": "P1003", "nombre": "Diego Ortiz", "email": "diego.ortiz@campus.example", "departamento": "Física"},
]

ESTUDIANTES: list[dict[str, str]] = [
    {"id": "2021114001", "nombre": "Ana Pérez", "email": "ana.perez@campus.example", "programa": "Ingeniería de Sistemas"},
    {"id": "2021114002", "nombre": "Juan Gómez", "email": "juan.gomez@campus.example", "programa": "Ingeniería de Sistemas"},
    {"id": "2021114003", "nombre": "Carla Ruiz", "email": "carla.ruiz@campus.example", "programa": "Ingeniería Electrónica"},
    {"id": "2021114004", "nombre": "Mateo Vargas", "email": "mateo.vargas@campus.example", "programa": "Ingeniería Civil"},
    {"id": "2021114005", "nombre": "Sofía Castro", "email": "sofia.castro@campus.example", "programa": "Ingeniería de Sistemas"},
    {"id": "2021114006", "nombre": "Daniel Rojas", "email": "daniel.rojas@campus.example", "programa": "Ingeniería Industrial"},
]

CURSOS: list[dict[str, Any]] = [
    {"cursoId": "MAT101", "nombre": "Cálculo Diferencial", "creditos": 4},
    {"cursoId": "FIS201", "nombre": "Física Mecánica", "creditos": 3},
    {"cursoId": "PRG110", "nombre": "Programación I", "creditos": 3},
    {"cursoId": "BDN301", "nombre": "Bases de Datos NoSQL", "creditos": 3},
    {"cursoId": "EST205", "nombre": "Estadística", "creditos": 3},
]

# (curso, periodo, grupo, profesor, horario, cupos, requiereAprobacion)
OFERTAS: list[tuple[str, str, str, str, str, int, bool]] = [
    ("MAT101", PERIODO_ANTERIOR, "G1", "P1001", "Lun y Mié 8:00-10:00", 30, False),
    ("PRG110", PERIODO_ANTERIOR, "G1", "P1002", "Mar y Jue 10:00-12:00", 30, False),
    ("MAT101", PERIODO, "G1", "P1001", "Lun y Mié 8:00-10:00", 3, True),
    ("MAT101", PERIODO, "G2", "P1001", "Mar y Jue 14:00-16:00", 2, True),
    ("FIS201", PERIODO, "G1", "P1003", "Lun y Mié 10:00-12:00", 3, True),
    ("PRG110", PERIODO, "G1", "P1002", "Vie 8:00-12:00", 4, False),
    ("BDN301", PERIODO, "G1", "P1002", "Mar y Jue 18:00-20:00", 2, True),
    ("EST205", PERIODO, "G1", "P1001", "Mié y Vie 14:00-16:00", 5, True),
]

# Historial 2025-2 con nota: (estudiante, curso, nota)
HISTORIAL: list[tuple[str, str, float]] = [
    ("2021114001", "MAT101", 4.6), ("2021114001", "PRG110", 3.9),
    ("2021114002", "MAT101", 3.2), ("2021114002", "PRG110", 4.4),
    ("2021114003", "PRG110", 2.8),
]

# Matrículas 2026-1: (estudiante, oferta, ¿aprobar?, código HTTP esperado)
MATRICULAS: list[tuple[str, str, bool, int]] = [
    ("2021114001", "BDN301-2026-1-G1", True, 201),
    ("2021114002", "BDN301-2026-1-G1", False, 201),      # llena el grupo (2 cupos)
    ("2021114003", "BDN301-2026-1-G1", False, 409),      # sin cupo: suma a la demanda
    ("2021114001", "FIS201-2026-1-G1", False, 201),
    ("2021114001", "PRG110-2026-1-G1", False, 201),      # la cursó en 2025-2: otro periodo, otra llave
    ("2021114002", "MAT101-2026-1-G1", True, 201),
    ("2021114003", "MAT101-2026-1-G1", False, 201),
    ("2021114004", "MAT101-2026-1-G2", False, 201),
    ("2021114004", "EST205-2026-1-G1", True, 201),
    ("2021114005", "PRG110-2026-1-G1", False, 201),      # sin aprobación: nace APROBADA
    ("2021114005", "MAT101-2026-1-G1", False, 201),      # llena MAT101 G1 (3 cupos)
    ("2021114006", "MAT101-2026-1-G1", False, 409),      # sin cupo
]


class Api:
    """Cliente HTTP mínimo (biblioteca estándar) con verificación de estado."""

    def __init__(self, base: str) -> None:
        self.base: str = base.rstrip("/")
        self.fallos: int = 0

    def llamar(
        self, metodo: str, ruta: str, cuerpo: dict[str, Any] | None = None,
        token: str | None = None, esperados: tuple[int, ...] = (200, 201),
    ) -> tuple[int, dict[str, Any]]:
        datos: bytes | None = json.dumps(cuerpo).encode() if cuerpo is not None else None
        cabeceras: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            cabeceras["Authorization"] = f"Bearer {token}"
        peticion = urllib.request.Request(
            self.base + ruta, data=datos, headers=cabeceras, method=metodo,
        )
        try:
            with urllib.request.urlopen(peticion, timeout=60) as r:
                status, texto = r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            status, texto = e.code, e.read().decode()
        try:
            respuesta: dict[str, Any] = json.loads(texto) if texto else {}
        except json.JSONDecodeError:
            respuesta = {"crudo": texto[:200]}

        ok: bool = status in esperados
        if not ok:
            self.fallos += 1
        detalle: str = "" if ok else f"   ← se esperaba {esperados}: {respuesta}"
        print(f"  {'✓' if ok else '✗'} {status}  {metodo:<6} {ruta}{detalle}")
        return status, respuesta

    def login(self, email: str) -> str:
        _, r = self.llamar("POST", "/auth/login", {"email": email, "password": CLAVE_DEMO})
        return r.get("token", "")


def ubicar_api() -> tuple[str, str]:
    """(URL para este contenedor, URL para el navegador) del API desplegado."""
    import boto3
    endpoint: str = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    apis: list[dict[str, Any]] = boto3.client("apigateway").get_rest_apis(limit=100)["items"]
    encontrada: list[str] = [a["id"] for a in apis if a["name"] == NOMBRE_API]
    if not encontrada:
        sys.exit(f"No se encontró el API '{NOMBRE_API}'. ¿Ya corriste `cdklocal deploy`?")
    sufijo: str = f"/restapis/{encontrada[0]}/prod/_user_request_"
    puerto: str = os.environ.get("PUERTO_EMULADOR", "4566")
    return endpoint + sufijo, f"http://localhost:{puerto}{sufijo}"


def nombre_tabla() -> str:
    if os.environ.get("TABLE_NAME"):
        return os.environ["TABLE_NAME"]
    import boto3
    salidas = boto3.client("cloudformation").describe_stacks(
        StackName=NOMBRE_STACK
    )["Stacks"][0]["Outputs"]
    return next(s["OutputValue"] for s in salidas if s["OutputKey"] == "TableName")


def sembrar_admin(tabla: Any) -> None:
    """Crea la cuenta de coordinación si no existe (dos Put condicionales)."""
    import importlib.util
    from botocore.exceptions import ClientError

    spec = importlib.util.spec_from_file_location(
        "handler_auth", os.path.join(RAIZ_APP, "lambdas", "auth", "handler.py"),
    )
    assert spec and spec.loader
    auth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auth)

    perfil, login = auth.construir_usuario(
        "ADMIN", ADMIN["id"], ADMIN["nombre"], ADMIN["email"], CLAVE_DEMO, ADMIN["dependencia"],
    )
    try:
        tabla.put_item(Item=login, ConditionExpression="attribute_not_exists(PK)")
        tabla.put_item(Item=perfil)
        print(f"  ✓ coordinación creada: {ADMIN['email']}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        print(f"  ✓ coordinación ya existía: {ADMIN['email']}")


def sembrar_por_api(api: Api) -> None:
    ya_existe: tuple[int, ...] = (201, 409)

    print("\n── Salud del servicio")
    api.llamar("GET", "/health")

    print("\n── Usuarios (POST /auth/registro)")
    for rol, usuarios in (("PROFESSOR", PROFESORES), ("STUDENT", ESTUDIANTES)):
        for u in usuarios:
            api.llamar("POST", "/auth/registro", {**u, "rol": rol, "password": CLAVE_DEMO},
                       esperados=ya_existe)

    print("\n── Sesiones (POST /auth/login)")
    admin: str = api.login(ADMIN["email"])
    profes: dict[str, str] = {p["id"]: api.login(p["email"]) for p in PROFESORES}
    alumnos: dict[str, str] = {e["id"]: api.login(e["email"]) for e in ESTUDIANTES}

    print("\n── Cursos y ofertas (coordinación)")
    for curso in CURSOS:
        api.llamar("POST", "/cursos", curso, token=admin, esperados=ya_existe)
    dueno: dict[str, str] = {}
    for curso_id, periodo, grupo, profesor, horario, cupos, aprobacion in OFERTAS:
        api.llamar("POST", f"/cursos/{curso_id}/ofertas", {
            "periodo": periodo, "grupo": grupo, "profesorId": profesor, "horario": horario,
            "cupos": cupos, "requiereAprobacion": aprobacion,
        }, token=admin, esperados=ya_existe)
        dueno[f"{curso_id}-{periodo}-{grupo}"] = profesor

    print(f"\n── Historial {PERIODO_ANTERIOR} con notas (matricular → calificar)")
    for estudiante, curso_id, nota in HISTORIAL:
        oferta: str = f"{curso_id}-{PERIODO_ANTERIOR}-G1"
        api.llamar("POST", "/matriculas", {"ofertaId": oferta},
                   token=alumnos[estudiante], esperados=ya_existe)
        api.llamar("PUT", f"/estudiantes/{estudiante}/matriculas/{PERIODO_ANTERIOR}/{curso_id}/nota",
                   {"nota": nota}, token=profes[dueno[oferta]])

    print(f"\n── Matrículas {PERIODO} (incluye rechazos por cupo: 409 esperado)")
    for estudiante, oferta, aprobar, esperado in MATRICULAS:
        status, _ = api.llamar("POST", "/matriculas", {"ofertaId": oferta},
                               token=alumnos[estudiante], esperados=(esperado, 409))
        if aprobar and status in (201, 409):
            curso_id = oferta.split("-")[0]
            api.llamar("POST", f"/estudiantes/{estudiante}/matriculas/{PERIODO}/{curso_id}/aprobar",
                       token=profes[dueno[oferta]], esperados=(200, 409))

    print("\n── Lecturas de verificación (segunda lectura debe venir de caché)")
    api.llamar("GET", f"/periodos/{PERIODO}/ofertas")
    _, catalogo = api.llamar("GET", f"/periodos/{PERIODO}/ofertas")
    api.llamar("GET", "/cursos/MAT101")
    api.llamar("GET", f"/estudiantes/2021114001/matriculas?periodo={PERIODO}",
               token=alumnos["2021114001"])
    api.llamar("GET", "/estudiantes/2021114001/notas", token=alumnos["2021114001"])
    api.llamar("GET", f"/profesores/P1001/ofertas?periodo={PERIODO}", token=profes["P1001"])
    api.llamar("GET", "/ofertas/MAT101-2026-1-G1/estudiantes", token=profes["P1001"])
    api.llamar("GET", f"/periodos/{PERIODO}/matriculas/pendientes", token=admin)
    _, demanda = api.llamar("GET", f"/periodos/{PERIODO}/demanda")

    print(f"\n   catálogo {PERIODO}: {catalogo.get('total')} ofertas (fuente: {catalogo.get('_fuente')})")
    print("   demanda: " + ", ".join(
        f"{f['cursoId']}={f['solicitudes']}" for f in demanda.get("ranking", [])
    ))


def escribir_config(base_navegador: str) -> None:
    carpeta: str = os.environ.get("FRONTEND_DIR", os.path.join(RAIZ_APP, "..", "frontend"))
    if not os.path.isdir(carpeta):
        print(f"\n(No existe {carpeta}: no se escribió config.js)")
        return
    ruta: str = os.path.join(carpeta, "config.js")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("// Generado por app/scripts/seed.py — no editar a mano\n")
        f.write(f"window.API_BASE = {json.dumps(base_navegador)};\n")
    print(f"\n✓ {ruta} → {base_navegador}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", help="URL base del API (por defecto se busca en el emulador)")
    parser.add_argument("--api-navegador", help="URL base que usará el navegador")
    parser.add_argument("--sin-admin", action="store_true",
                        help="No sembrar coordinación (ya existe en la tabla)")
    args = parser.parse_args()

    if args.api:
        base_interna, base_navegador = args.api, args.api_navegador or args.api
    else:
        base_interna, base_navegador = ubicar_api()
    print(f"API: {base_interna}")

    if not args.sin_admin:
        import boto3
        print("\n── Coordinación (directo en DynamoDB)")
        sembrar_admin(boto3.resource("dynamodb").Table(nombre_tabla()))

    api = Api(base_interna)
    sembrar_por_api(api)
    escribir_config(base_navegador)

    print("\n" + "─" * 60)
    if api.fallos:
        sys.exit(f"✗ {api.fallos} llamadas no respondieron lo esperado. Revisa las líneas con ✗.")
    print("✓ Datos de demo cargados. Todas las llamadas respondieron lo esperado.")
    print(f"  Contraseña de todas las cuentas: {CLAVE_DEMO}")
    print(f"  Coordinación: {ADMIN['email']}")
    print(f"  Profesor:     {PROFESORES[0]['email']}")
    print(f"  Estudiante:   {ESTUDIANTES[0]['email']}")
    print("  Frontend:     http://localhost:8080")


if __name__ == "__main__":
    main()
