"""
esquema.py
──────────
Definición de la tabla para entornos sin CDK (tests con moto y el
servidor de simulación). Debe reflejar lo que declara infra/stack.py:
PK+SK, LSI1, GSI1 y GSI2, todos con proyección ALL.
"""
from typing import Any

ATRIBUTOS_LLAVE: tuple[str, ...] = (
    "PK", "SK", "LSI1SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK",
)


def crear_tabla(recurso: Any, nombre: str) -> Any:
    """Crea la tabla en el recurso DynamoDB dado y espera a que exista."""
    tabla = recurso.create_table(
        TableName=nombre,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": atributo, "AttributeType": "S"} for atributo in ATRIBUTOS_LLAVE
        ],
        LocalSecondaryIndexes=[{
            "IndexName": "LSI1",
            "KeySchema": [
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "LSI1SK", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        GlobalSecondaryIndexes=[
            {
                "IndexName": indice,
                "KeySchema": [
                    {"AttributeName": f"{indice}PK", "KeyType": "HASH"},
                    {"AttributeName": f"{indice}SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for indice in ("GSI1", "GSI2")
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    tabla.wait_until_exists()
    return tabla
