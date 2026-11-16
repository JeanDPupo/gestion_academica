#!/usr/bin/env python3
"""
ver_tabla.py
────────────
Muestra el contenido de la tabla agrupado por partición (item collection),
con las llaves de la tabla y de los índices. Sirve para la sustentación:
deja ver el Single Table Design tal como quedó en DynamoDB.

Uso (dentro de cdk-dev):
    python scripts/ver_tabla.py                 # toda la tabla
    python scripts/ver_tabla.py STUDENT#        # solo particiones con ese prefijo
    python scripts/ver_tabla.py --indice GSI1   # vista desde un índice

Es la ÚNICA parte del proyecto que usa Scan: es una herramienta de
inspección, no un patrón de acceso. Ninguna Lambda hace Scan.
"""
import argparse
import os
import sys
from collections import defaultdict
from typing import Any

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.dirname(__file__))

LLAVES_INDICE: dict[str, tuple[str, str]] = {
    "tabla": ("PK", "SK"),
    "LSI1": ("PK", "LSI1SK"),
    "GSI1": ("GSI1PK", "GSI1SK"),
    "GSI2": ("GSI2PK", "GSI2SK"),
}
# Atributos que se muestran junto a las llaves, según el tipo de ítem
RESUMEN: dict[str, tuple[str, ...]] = {
    "STUDENT": ("nombre", "programa"),
    "PROFESSOR": ("nombre", "departamento"),
    "ADMIN": ("nombre",),
    "EMAIL": ("userId", "rol"),
    "COURSE": ("nombre", "creditos"),
    "OFFER": ("profesorId", "cuposDisponibles", "cuposTotales", "estado"),
    "ENROLLMENT": ("ofertaId", "estado", "nota"),
}


def escanear(tabla: Any, indice: str | None) -> list[dict[str, Any]]:
    parametros: dict[str, Any] = {"IndexName": indice} if indice else {}
    items: list[dict[str, Any]] = []
    while True:
        pagina = tabla.scan(**parametros)
        items.extend(pagina["Items"])
        if "LastEvaluatedKey" not in pagina:
            return items
        parametros["ExclusiveStartKey"] = pagina["LastEvaluatedKey"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Muestra la tabla por particiones")
    parser.add_argument("prefijo", nargs="?", default="", help="Prefijo de la llave de partición")
    parser.add_argument("--indice", choices=["LSI1", "GSI1", "GSI2"], help="Ver desde un índice")
    args = parser.parse_args()

    if os.environ.get("TABLE_NAME"):
        nombre: str = os.environ["TABLE_NAME"]
    else:
        from seed import nombre_tabla
        nombre = nombre_tabla()

    vista: str = args.indice or "tabla"
    pk, sk = LLAVES_INDICE[vista]
    items = escanear(boto3.resource("dynamodb").Table(nombre), args.indice)

    particiones: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if pk in item and sk in item and str(item[pk]).startswith(args.prefijo):
            particiones[item[pk]].append(item)

    print(f"Tabla {nombre} · vista: {vista} ({pk} / {sk}) · "
          f"{sum(len(v) for v in particiones.values())} ítems en {len(particiones)} particiones\n")
    for particion in sorted(particiones):
        print(f"{pk} = {particion}")
        for item in sorted(particiones[particion], key=lambda i: i[sk]):
            campos = RESUMEN.get(item.get("entityType", ""), ())
            detalle = "  ".join(f"{c}={item[c]}" for c in campos if c in item)
            print(f"    {sk} = {item[sk]:<46} {detalle}")
        print()


if __name__ == "__main__":
    main()
