#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# desplegar.sh — despliega el stack en el emulador y carga los datos.
#
# Uso (dentro del contenedor cdk-dev):
#     bash scripts/desplegar.sh
#
# Equivale a ejecutar a mano:
#     cdklocal bootstrap      (necesario tras cada reinicio del emulador)
#     cdklocal deploy
#     python scripts/seed.py
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

echo "▶ 1/3  cdklocal bootstrap"
cdklocal bootstrap

echo "▶ 2/3  cdklocal deploy"
cdklocal deploy --require-approval never

echo "▶ 3/3  Datos de demo y prueba de punta a punta"
python scripts/seed.py
