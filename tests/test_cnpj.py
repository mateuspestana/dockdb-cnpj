"""
Testes unitários de CNPJ (numérico e alfanumérico).

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import duckdb
import pytest

from dockdb_cnpj.cnpj import (
    calcular_dv,
    completar_zeros,
    dv_valido,
    formatar,
    normalize_cnpj,
    sql_dv_expr,
)

CASOS = [
    ("12ABC34501DE", "35"),  # exemplo oficial da RFB
    ("00000000E08G", "12"),  # CNPJ alfanumérico real (dump 2026-09)
    ("112223330001", "81"),
    ("123456780001", "95"),
]


@pytest.mark.parametrize(("base", "dv"), CASOS)
def test_calcular_dv(base: str, dv: str) -> None:
    assert calcular_dv(base) == dv
    assert dv_valido(base + dv)


@pytest.mark.parametrize(("base", "dv"), CASOS)
def test_sql_dv_bate_com_python(base: str, dv: str) -> None:
    con = duckdb.connect()
    sql = f"SELECT {sql_dv_expr('x')} FROM (SELECT ?::VARCHAR AS x)"
    assert con.execute(sql, [base + "00"]).fetchone()[0] == dv


def test_dv_invalido_e_formato() -> None:
    assert not dv_valido("12ABC34501DE36")
    assert not dv_valido("12ABC34501DEAB")  # DV precisa ser numérico
    assert not dv_valido("123")


def test_normalize() -> None:
    assert normalize_cnpj("12.abc.345/01de-35") == "12ABC34501DE35"
    assert normalize_cnpj("11.222.333") == "11222333"
    with pytest.raises(ValueError):
        normalize_cnpj("123")
    with pytest.raises(ValueError):
        normalize_cnpj("12ABC34501DEXX")


def test_formatar() -> None:
    assert formatar("12ABC34501DE35") == "12.ABC.345/01DE-35"
    assert formatar("11222333") == "11.222.333"


def test_completar_zeros() -> None:
    assert completar_zeros("191") == "00000191"
    assert completar_zeros("191000191") == "00000191000191"
    assert completar_zeros("12ABC34501DE35") == "12ABC34501DE35"
