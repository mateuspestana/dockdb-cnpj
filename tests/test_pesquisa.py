"""
Testes v0.7: hierarquia CNAE, coortes, busca por lista e geocodificação.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dockdb_cnpj.analytics import agregados_municipio, coortes
from dockdb_cnpj.db import connect
from dockdb_cnpj.enriquecimento import enriquecer, ler_lista
from dockdb_cnpj.geo import ceps_pendentes, geocodificar_ceps
from dockdb_cnpj.load import load_duckdb
from dockdb_cnpj.queries import agregados_cnae, buscar_empresas, consulta_cnpj

FIXTURE = Path(__file__).parent / "fixtures" / "mini"


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("pesquisa") / "p.duckdb"
    load_duckdb(zip_dir=FIXTURE, csv_dir=FIXTURE, db_path=path, extract=False, build_fts=False)
    return path


def test_cnae_hierarquia(db: Path) -> None:
    con = connect(db, read_only=True)
    row = con.execute(
        "SELECT classe, grupo, divisao, secao FROM cnae_hierarquia WHERE cnae = '6201501'"
    ).fetchone()
    assert row == ("62015", "620", "62", "J")
    con.close()


def test_busca_secao_divisao(db: Path) -> None:
    con = connect(db, read_only=True)
    rows = buscar_empresas(con, cnae_secao="j", limit=10)
    assert {r["cnpj"] for r in rows} == {"12345678000195", "12ABC34501DE35"}
    assert all(r["cnae_secao"] == "J" for r in rows)
    rows = buscar_empresas(con, cnae_divisao="46", limit=10)
    assert {r["cnpj"] for r in rows} == {"87654321000198", "87654321000200"}
    assert buscar_empresas(con, cnae_secao="Z", limit=10) == []
    con.close()


def test_agregados_cnae_nivel(db: Path) -> None:
    con = connect(db, read_only=True)
    rows = agregados_cnae(con, nivel="secao")
    assert {r["secao"]: r["n"] for r in rows} == {"J": 2, "G": 2}
    with pytest.raises(ValueError):
        agregados_cnae(con, nivel="xyz")
    con.close()


def test_coortes(db: Path) -> None:
    con = connect(db, read_only=True)
    rows = {r["periodo"]: r for r in coortes(con, freq="ano")}
    assert rows["2021"]["aberturas"] == 2
    assert rows["2021"]["ativas_hoje"] == 1
    assert rows["2021"]["taxa_sobrevivencia"] == 0.5
    assert rows["2025"]["baixas"] == 1
    assert rows["2025"]["aberturas"] == 0
    assert rows["2025"]["saldo"] == -1
    so_rj = coortes(con, freq="mes", uf="RJ", desde="2026")
    assert [r["periodo"] for r in so_rj] == ["202608"]
    con.close()


def test_agregados_municipio(db: Path) -> None:
    con = connect(db, read_only=True)
    rows = {r["municipio_ibge"]: r for r in agregados_municipio(con)}
    assert rows["3550308"]["n"] == 2
    assert rows["3304557"]["latitude"] is not None
    con.close()


def test_enriquecer_ordem_e_casos(db: Path) -> None:
    con = connect(db, read_only=True)
    entradas = ["12.345.678/0001-95", "12abc345", "191", "xx", "87654321000200", None]
    rows = enriquecer(con, entradas)
    assert [r["entrada"] for r in rows] == ["12.345.678/0001-95", "12abc345", "191", "xx", "87654321000200", ""]
    assert rows[0]["encontrado"] and rows[0]["razao_social"] == "EMPRESA TESTE LTDA"
    assert rows[1]["cnpj"] == "12ABC34501DE35"  # básico → matriz
    assert rows[1]["municipio_ibge"] == "3304557"
    assert rows[2]["cnpj_normalizado"] == "00000191" and not rows[2]["encontrado"]
    assert rows[3]["erro"] and not rows[3]["encontrado"]
    assert rows[4]["encontrado"] and rows[4]["dv_valido"] is False
    assert rows[4]["situacao_cadastral_desc"] == "Baixada"
    con.close()


def test_ler_lista(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("12345678000195\n12ABC34501DE35\n")
    assert ler_lista(tmp_path / "a.txt") == ["12345678000195", "12ABC34501DE35"]
    (tmp_path / "b.csv").write_text("nome;CNPJ\nA;12.345.678/0001-95\n")
    assert ler_lista(tmp_path / "b.csv") == ["12.345.678/0001-95"]
    with pytest.raises(ValueError):
        ler_lista(tmp_path / "b.csv", coluna="nao_existe")


def test_geocodificar_com_cache(db: Path, tmp_path: Path) -> None:
    copia = tmp_path / "geo.duckdb"
    shutil.copy(db, copia)
    chamadas: list[str] = []

    def fake(cep: str) -> dict:
        chamadas.append(cep)
        if cep == "20040020":
            return {"status": "ok", "latitude": -22.9, "longitude": -43.18, "municipio_ibge": "3304557"}
        return {"status": "sem_coordenada"}

    con = connect(copia, read_only=False)
    stats = geocodificar_ceps(con, ["20040-020", "01001000", "20040020", "x"], fetcher=fake, pausa=0)
    assert stats["pendentes"] == 2 and stats["ok"] == 1 and stats["sem_coordenada"] == 1
    assert ceps_pendentes(con, ["20040020", "01001000"]) == []
    geocodificar_ceps(con, ["20040020"], fetcher=fake, pausa=0)
    assert chamadas == ["20040020", "01001000"]  # cache evitou nova chamada

    rows = {r["cnpj"]: r for r in buscar_empresas(con, uf="RJ", limit=10)}
    alfa = rows["12ABC34501DE35"]
    assert alfa["geo_precisao"] == "cep" and alfa["latitude"] == -22.9
    sp = buscar_empresas(con, uf="SP", limit=1)[0]
    assert sp["geo_precisao"] == "municipio"
    est = consulta_cnpj(con, "12ABC34501DE35")["estabelecimentos"][0]
    assert est["geo_precisao"] == "cep"
    con.close()
