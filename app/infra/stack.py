"""
GestionAcademicaStack
─────────────────────
Define la infraestructura serverless del sistema de gestión académica:
  - Tabla DynamoDB  (Single Table Design: PK+SK, 1 LSI y 2 GSI sobrecargados)
  - Lambda Layer    con las dependencias de las Lambdas (boto3, botocore, redis)
  - Una Lambda por dominio (ver LAMBDAS), con el módulo `comun` empaquetado
  - API Gateway     (RestApi) que enruta cada ruta a su Lambda (ver RUTAS)

Para agregar un endpoint: una fila en RUTAS y su función en el handler.
"""
import os
import shutil
import subprocess
import sys
from typing import Any

import aws_cdk as cdk
import jsii
from aws_cdk import (
    Stack,
    aws_dynamodb as ddb,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    RemovalPolicy,
    CfnOutput,
)
from constructs import Construct

# Runtime común a todas las Lambdas y a la layer
RUNTIME: _lambda.Runtime = _lambda.Runtime.PYTHON_3_11
DIR_LAMBDAS: str = "lambdas"
DIR_COMUN: str = os.path.join(DIR_LAMBDAS, "comun")
DIR_LAYER: str = "layers/dependencias"
REQUIREMENTS_LAYER: str = os.path.join(DIR_LAYER, "requirements.txt")

# LocalStack Community acepta las Lambda Layers pero no las monta al ejecutar
# (es una función de LocalStack Pro). Cuando se despliega en el emulador
# (cdk-dev define AWS_ENDPOINT_URL), las dependencias se empaquetan dentro
# del código de cada Lambda en lugar de usar la layer.
ES_LOCAL: bool = "AWS_ENDPOINT_URL" in os.environ

# ── Lambdas: nombre → (descripción, timeout en segundos, ¿escribe?) ────
LAMBDAS: dict[str, tuple[str, int, bool]] = {
    "health":     ("Health check de DynamoDB y Redis", 5, False),
    "auth":       ("Registro, login y sesiones", 10, True),
    "usuarios":   ("Perfiles de estudiantes y profesores", 10, False),
    "cursos":     ("Cursos, ofertas y catálogo", 10, True),
    "matriculas": ("Matricular, retirar y cambiar de grupo", 10, True),
}

# ── Rutas del API: (lambda, método, ruta) ──────────────────────────────
RUTAS: list[tuple[str, str, str]] = [
    ("health",     "GET",    "/health"),
    ("auth",       "POST",   "/auth/registro"),
    ("auth",       "POST",   "/auth/login"),
    ("auth",       "POST",   "/auth/logout"),
    ("auth",       "GET",    "/auth/me"),
    ("usuarios",   "GET",    "/estudiantes/{studentId}"),
    ("usuarios",   "GET",    "/profesores/{profesorId}"),
    ("cursos",     "POST",   "/cursos"),
    ("cursos",     "GET",    "/cursos/{cursoId}"),
    ("cursos",     "POST",   "/cursos/{cursoId}/ofertas"),
    ("cursos",     "GET",    "/periodos/{periodo}/ofertas"),
    ("cursos",     "GET",    "/profesores/{profesorId}/ofertas"),
    ("cursos",     "PUT",    "/ofertas/{ofertaId}/estado"),
    ("matriculas", "POST",   "/matriculas"),
    ("matriculas", "GET",    "/estudiantes/{studentId}/matriculas"),
    ("matriculas", "DELETE", "/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}"),
    ("matriculas", "PUT",    "/estudiantes/{studentId}/matriculas/{periodo}/{cursoId}/grupo"),
    ("matriculas", "GET",    "/periodos/{periodo}/demanda"),
]


def _pip_install(requirements: str, destino: str) -> None:
    """Instala las dependencias en `destino` para el runtime de Lambda."""
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--quiet",
            "--requirement", requirements,
            "--target", destino,
            # Descargar wheels para el sistema y la versión de Python
            # de Lambda, no los del contenedor de desarrollo
            "--platform", "manylinux2014_x86_64",
            "--implementation", "cp",
            "--python-version", "3.11",
            "--only-binary=:all:",
            # Sin .pyc: hace el resultado reproducible (mismo hash de asset
            # si no cambian las dependencias → no se redespliega sin motivo)
            "--no-compile",
        ],
        check=True,
    )


@jsii.implements(cdk.ILocalBundling)
class _EmpaquetadoLocal:
    """
    Empaqueta con el pip del propio contenedor cdk-dev, sin necesitar Docker.

    - Layer:  instala las dependencias en "python/", donde Lambda las busca.
    - Lambda: copia su handler y el módulo compartido `comun/`; en LocalStack
              agrega además las dependencias (ver ES_LOCAL).
    """

    def __init__(
        self,
        requirements: str | None,
        subdir: str = "",
        copiar: dict[str, str] | None = None,
    ) -> None:
        self.requirements: str | None = requirements
        self.subdir: str = subdir
        # origen → subcarpeta de destino dentro del paquete ("" = raíz)
        self.copiar: dict[str, str] = copiar or {}

    def try_bundle(self, output_dir: str, *args: Any, **kwargs: Any) -> bool:
        for origen, destino in self.copiar.items():
            shutil.copytree(
                origen,
                os.path.join(output_dir, destino),
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        if self.requirements:
            _pip_install(self.requirements, os.path.join(output_dir, self.subdir))
        return True


def _codigo_lambda(nombre: str) -> _lambda.Code:
    """
    Paquete de una Lambda: lambdas/<nombre>/ en la raíz + lambdas/comun/
    como paquete `comun`. En AWS las dependencias van en la layer; en
    LocalStack se instalan dentro del mismo paquete.
    """
    directorio: str = os.path.join(DIR_LAMBDAS, nombre)
    return _lambda.Code.from_asset(
        # El origen debe ser la carpeta propia de cada Lambda: CDK reutiliza
        # el resultado del bundling entre assets con el mismo origen y las
        # mismas opciones, y todas las Lambdas recibirían el mismo código.
        directorio,
        # El hash se calcula sobre el resultado: cambia cuando cambia el
        # handler, el módulo comun o las dependencias
        asset_hash_type=cdk.AssetHashType.OUTPUT,
        bundling=cdk.BundlingOptions(
            # Solo se usaría si falla el bundling local (cdk-dev no tiene Docker)
            image=RUNTIME.bundling_image,
            command=["bash", "-c", f"echo 'Requiere bundling local ({nombre})' && exit 1"],
            local=_EmpaquetadoLocal(
                REQUIREMENTS_LAYER if ES_LOCAL else None,
                copiar={directorio: "", DIR_COMUN: "comun"},
            ),
        ),
    )


class GestionAcademicaStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── 1. TABLA DYNAMODB ─────────────────────────────────────────
        # Single Table Design: PK y SK genéricos para soportar todas las
        # entidades (estudiante, profesor, email, curso, oferta, matrícula).
        tabla: ddb.Table = ddb.Table(
            self,
            "AppTable",
            partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            # DESTROY permite borrar la tabla al hacer `cdklocal destroy`
            # En producción usar RETAIN
            removal_policy=RemovalPolicy.DESTROY,
        )

        # LSI1 — matrículas de un estudiante ordenadas por nota.
        # Comparte la PK de la tabla; solo se puede definir al crearla.
        tabla.add_local_secondary_index(
            index_name="LSI1",
            sort_key=ddb.Attribute(name="LSI1SK", type=ddb.AttributeType.STRING),
            projection_type=ddb.ProjectionType.ALL,
        )

        # GSI1 (sobrecargado) — ofertas de un profesor · estudiantes de una oferta
        tabla.add_global_secondary_index(
            index_name="GSI1",
            partition_key=ddb.Attribute(name="GSI1PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="GSI1SK", type=ddb.AttributeType.STRING),
            projection_type=ddb.ProjectionType.ALL,
        )

        # GSI2 (sobrecargado) — catálogo del periodo · matrículas pendientes
        tabla.add_global_secondary_index(
            index_name="GSI2",
            partition_key=ddb.Attribute(name="GSI2PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="GSI2SK", type=ddb.AttributeType.STRING),
            projection_type=ddb.ProjectionType.ALL,
        )

        # Variables de entorno comunes para todas las Lambdas
        env_comun: dict[str, str] = {
            "TABLE_NAME": tabla.table_name,
            "REDIS_HOST": os.environ.get("REDIS_HOST", "redis"),
            "REDIS_PORT": os.environ.get("REDIS_PORT", "6379"),
            "REDIS_TTL":  "300",   # TTL por defecto de la caché, en segundos
            # TTL de las respuestas que muestran cupos (catálogo, curso, ofertas)
            "TTL_CUPOS":  os.environ.get("TTL_CUPOS", "15"),
            # Secreto con el que se firman los tokens de sesión.
            # En AWS real debe venir de Secrets Manager / SSM, no del entorno.
            "TOKEN_SECRET": os.environ.get("TOKEN_SECRET", "solo-para-desarrollo-local"),
            "SESION_TTL": os.environ.get("SESION_TTL", "3600"),
        }

        # ── 2. LAMBDA LAYER (dependencias) ────────────────────────────
        # Las librerías externas van en una layer compartida, construida
        # con pip a partir de layers/dependencias/requirements.txt.
        # Se reconstruye solo cuando cambia ese archivo.
        # En LocalStack no se crea: no la aplicaría (ver ES_LOCAL).
        layers: list[_lambda.ILayerVersion] = []
        if not ES_LOCAL:
            layer_dependencias: _lambda.LayerVersion = _lambda.LayerVersion(
                self,
                "DependenciasLayer",
                code=_lambda.Code.from_asset(
                    DIR_LAYER,
                    bundling=cdk.BundlingOptions(
                        # image/command solo se usan si falla el bundling local
                        image=RUNTIME.bundling_image,
                        command=[
                            "bash", "-c",
                            "pip install -r requirements.txt -t /asset-output/python",
                        ],
                        local=_EmpaquetadoLocal(REQUIREMENTS_LAYER, subdir="python"),
                    ),
                ),
                compatible_runtimes=[RUNTIME],
                description="boto3, botocore y redis para las Lambdas",
            )
            layers.append(layer_dependencias)

        # ── 3. LAMBDAS (una por dominio) ──────────────────────────────
        funciones: dict[str, _lambda.Function] = {}
        for nombre, (descripcion, timeout, escribe) in LAMBDAS.items():
            funcion: _lambda.Function = _lambda.Function(
                self,
                f"{nombre.capitalize()}Handler",
                runtime=RUNTIME,
                handler="handler.main",
                code=_codigo_lambda(nombre),
                layers=layers,
                environment=env_comun,
                timeout=cdk.Duration.seconds(timeout),
                description=descripcion,
            )
            # Mínimo privilegio: solo escriben las Lambdas que lo necesitan.
            # grant_* incluye el acceso a los índices de la tabla.
            if escribe:
                tabla.grant_read_write_data(funcion)
            else:
                tabla.grant_read_data(funcion)
            funciones[nombre] = funcion

        # ── 4. API GATEWAY ────────────────────────────────────────────
        api: apigw.RestApi = apigw.RestApi(
            self,
            "Api",
            rest_api_name="GestionAcademica-API",
            description="Gestión académica — DynamoDB + Redis + CDK",
            deploy_options=apigw.StageOptions(stage_name="prod"),
        )

        integraciones: dict[str, apigw.LambdaIntegration] = {
            # allow_test_invoke=False evita un permiso extra por método
            nombre: apigw.LambdaIntegration(funcion, allow_test_invoke=False)
            for nombre, funcion in funciones.items()
        }

        con_preflight: set[str] = set()
        for nombre, metodo, ruta in RUTAS:
            recurso: apigw.Resource = api.root.resource_for_path(ruta)
            recurso.add_method(metodo, integraciones[nombre])
            # CORS: el navegador envía un OPTIONS previo (preflight) porque
            # las peticiones llevan Authorization. Lo responde la misma
            # Lambda (ver comun/http.py), una vez por recurso.
            if ruta not in con_preflight:
                recurso.add_method("OPTIONS", integraciones[nombre])
                con_preflight.add(ruta)

        # ── 5. OUTPUTS ────────────────────────────────────────────────
        CfnOutput(self, "ApiUrl",
                  value=api.url,
                  description="URL base del API Gateway")
        CfnOutput(self, "ApiId",
                  value=api.rest_api_id,
                  description="Id del API (cambia en cada despliegue del emulador)")
        CfnOutput(self, "TableName",
                  value=tabla.table_name,
                  description="Nombre de la tabla DynamoDB")
