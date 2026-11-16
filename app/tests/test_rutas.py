"""
test_rutas.py
─────────────
Verifica que el stack CDK y los handlers declaran exactamente las mismas
rutas: una ruta en API Gateway sin función (o al revés) sería un 405 o
un endpoint inalcanzable que ningún otro test detecta.
"""
import os
import sys

import pytest

from util import RAIZ_APP, cargar_handler, lambdas_con_rutas

pytest.importorskip("aws_cdk")
sys.path.insert(0, os.path.join(RAIZ_APP, "infra"))

import stack  # noqa: E402  (necesita infra/ en el path)


def _rutas_del_stack() -> dict[str, set[tuple[str, str]]]:
    por_lambda: dict[str, set[tuple[str, str]]] = {}
    for nombre, metodo, ruta in stack.RUTAS:
        por_lambda.setdefault(nombre, set()).add((metodo, ruta))
    return por_lambda


@pytest.mark.parametrize("nombre", [n for n in stack.LAMBDAS if n != "health"])
def test_rutas_del_stack_coinciden_con_el_handler(nombre):
    en_handler = set(cargar_handler(nombre).rutas._rutas)
    assert _rutas_del_stack()[nombre] == en_handler


def test_toda_lambda_con_rutas_esta_declarada_en_el_stack():
    """Un handler nuevo que no se agregó a LAMBDAS/RUTAS no se desplegaría."""
    assert set(lambdas_con_rutas()) == set(stack.LAMBDAS) - {"health"}


def test_cada_lambda_del_stack_tiene_carpeta_y_rutas():
    con_rutas = {nombre for nombre, _, _ in stack.RUTAS}
    assert con_rutas == set(stack.LAMBDAS)
    for nombre in stack.LAMBDAS:
        assert os.path.isfile(os.path.join(RAIZ_APP, "lambdas", nombre, "handler.py"))


def test_no_hay_rutas_repetidas():
    pares = [(metodo, ruta) for _, metodo, ruta in stack.RUTAS]
    assert len(pares) == len(set(pares))
