"""
Testes de integração com fixture mínima dos CSVs da RF.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dockdb_cnpj.load import load_duckdb
from dockdb_cnpj.db import connect
from dockdb_cnpj.queries import (
    buscar_empresas,
    buscar_socios,
    consulta_cnpj,
    exportar_busca,
)
from dockdb_cnpj.validate import validar_base

FIXTURE = Path(__file__).parent / "fixtures" / "mini"


@pytest.fixture(scope="module")
def mini_db(tmp_path_factory) -> Path:
    db = tmp_path_factory.mktemp("db") / "mini.duckdb"
    load_duckdb(
        zip_dir=FIXTURE,  # sem zips; extract=False
        csv_dir=FIXTURE,
        db_path=db,
        extract=False,
        resume=False,
        build_cnae_bridge=True,
        build_mvs=True,
        build_fts=True,
        run_validate=True,
    )
    return db


def test_load_counts(mini_db: Path) -> None:
    con = connect(mini_db, read_only=True)
    assert con.execute("SELECT count(*) FROM empresas").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM estabelecimento").fetchone()[0] == 5
    assert con.execute("SELECT count(*) FROM socios").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM estabelecimento_cnae").fetchone()[0] >= 3
    con.close()


def test_consulta_decode(mini_db: Path) -> None:
    con = connect(mini_db, read_only=True)
    data = consulta_cnpj(con, "12345678000195")
    assert data["empresas"]
    assert data["empresas"][0].get("natureza_juridica_desc")
    assert data["estabelecimentos"][0].get("cnae_descricao")
    assert data["estabelecimentos"][0].get("situacao_cadastral_desc") == "Ativa"
    con.close()


def test_busca_filtros(mini_db: Path) -> None:
    con = connect(mini_db, read_only=True)
    rows = buscar_empresas(con, uf="SP", cnae="6201501", limit=10)
    assert rows
    assert any(r["cnae_origem"] in ("principal", "secundario") for r in rows)
    rows_mei = buscar_empresas(con, mei=True, limit=10)
    assert any(r["cnpj"].startswith("12345678") for r in rows_mei)
    rows_mun = buscar_empresas(con, municipio_nome="SAO PAULO", limit=10)
    assert rows_mun
    con.close()


def test_socio(mini_db: Path) -> None:
    con = connect(mini_db, read_only=True)
    rows = buscar_socios(con, nome="JOAO", limit=10)
    assert rows
    assert "TESTE" in (rows[0].get("razao_social") or "")
    con.close()


def test_export_csv(mini_db: Path, tmp_path: Path) -> None:
    con = connect(mini_db, read_only=True)
    dest = tmp_path / "out.csv"
    exportar_busca(con, dest, formato="csv", uf="SP", limit=10)
    assert dest.exists()
    assert dest.stat().st_size > 0
    con.close()


def test_validacao(mini_db: Path) -> None:
    con = connect(mini_db, read_only=False)
    result = validar_base(con, persist=True)
    assert result["ok"]
    con.close()


def test_materialized_views(mini_db: Path) -> None:
    con = connect(mini_db, read_only=True)
    n = con.execute("SELECT count(*) FROM mv_estabelecimento_ativo").fetchone()[0]
    assert n == 4
    n_m = con.execute("SELECT count(*) FROM mv_matriz").fetchone()[0]
    assert n_m == 3
    n_mei = con.execute("SELECT count(*) FROM mv_mei").fetchone()[0]
    assert n_mei >= 1
    con.close()


def test_upgrade_idempotent(mini_db: Path) -> None:
    from dockdb_cnpj.load import upgrade_base

    con = connect(mini_db, read_only=False)
    out = upgrade_base(con, build_cnae_bridge=True, build_mvs=True, build_fts=True)
    assert out.get("estabelecimento_cnae")
    assert out.get("views")
    con.close()


def test_resume_after_socios_processed(tmp_path: Path) -> None:
    """Resume do pós-processamento quando socios_original já foi dropado."""
    from dockdb_cnpj.load import _save_checkpoint, load_duckdb

    fixture = Path(__file__).parent / "fixtures" / "mini"
    db = tmp_path / "resume.duckdb"
    load_duckdb(
        zip_dir=tmp_path,
        csv_dir=fixture,
        db_path=db,
        extract=False,
        resume=False,
        build_fts=False,
    )
    _save_checkpoint(
        db,
        {
            "completed": [
                "codigos",
                "empresas",
                "estabelecimento",
                "socios_original",
                "simples",
            ],
            "files_done": {},
            "ano_mes": "202609",
        },
    )
    load_duckdb(
        zip_dir=tmp_path,
        csv_dir=fixture,
        db_path=db,
        extract=False,
        resume=True,
        build_fts=False,
    )
    con = connect(db, read_only=True)
    assert con.execute("SELECT count(*) FROM socios").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM estabelecimento_cnae").fetchone()[0] >= 3
    con.close()



def test_consulta_alfanumerica(mini_db: Path) -> None:
    con = connect(mini_db, read_only=True)
    data = consulta_cnpj(con, "12.abc.345/01de-35")
    assert data["cnpj_consultado"] == "12ABC34501DE35"
    assert data["cnpj_formatado"] == "12.ABC.345/01DE-35"
    assert data["alfanumerico"] is True
    assert data["dv_valido"] is True
    assert data["empresas"][0]["razao_social"] == "EMPRESA ALFA LTDA"
    est = data["estabelecimentos"][0]
    assert est["municipio_ibge"] == "3304557"
    basico = consulta_cnpj(con, "12ABC345")
    assert len(basico["estabelecimentos"]) == 1
    con.close()


def test_consulta_dv_invalido(mini_db: Path) -> None:
    con = connect(mini_db, read_only=True)
    data = consulta_cnpj(con, "87654321000200")
    assert data["dv_valido"] is False
    assert data["dv_esperado"] == "79"
    assert data["estabelecimentos"]  # existe na base mesmo com DV errado
    con.close()


def test_socio_pj_alfanumerico(mini_db: Path) -> None:
    con = connect(mini_db, read_only=True)
    rows = buscar_socios(con, documento="12.ABC.345/01DE-35", limit=10)
    assert rows
    assert rows[0]["razao_social"] == "OUTRA EMPRESA SA"
    con.close()


def test_busca_municipio_ibge(mini_db: Path) -> None:
    con = connect(mini_db, read_only=True)
    rows = buscar_empresas(con, municipio_ibge="3304557", limit=10)
    assert {r["cnpj"] for r in rows} == {"87654321000200", "12ABC34501DE35"}
    assert all(r["municipio_ibge"] == "3304557" for r in rows)
    con.close()


def test_validacao_dv_e_ibge(mini_db: Path) -> None:
    con = connect(mini_db, read_only=True)
    result = validar_base(con, persist=False)
    checks = {c["check"]: c for c in result["checks"]}
    assert result["ok"]  # avisos não derrubam ok
    assert checks["cnpj_dv"]["nivel"] == "aviso"
    assert checks["cnpj_dv"]["valor"] == 1
    assert checks["cnpj_alfanumerico"]["valor"] == 1
    assert checks["municipio_ibge_cobertura"]["ok"]
    con.close()
