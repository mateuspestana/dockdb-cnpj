"""
Tabelas auxiliares versionadas no pacote (não vêm da Receita).

- ``municipio_ibge``: código RF (TOM/SIAFI) → código IBGE, UF, região e centroide.
- ``cnae_hierarquia``: subclasse → classe → grupo → divisão → seção (CNAE 2.3).

Regerar os CSVs: ``python scripts/build_reference_data.py``.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

from pathlib import Path

import duckdb

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

DATA_DIR = Path(__file__).resolve().parent / "data"
MUNICIPIOS_CSV = DATA_DIR / "municipios_ibge.csv"
CNAE_CSV = DATA_DIR / "cnae_classes.csv"


def _csv(path: Path) -> str:
    p = str(path).replace("'", "''")
    return f"read_csv('{p}', header=true, all_varchar=true)"


def build_municipio_ibge(con: duckdb.DuckDBPyConnection) -> int:
    print("  municipio_ibge …", flush=True)
    con.execute("DROP TABLE IF EXISTS municipio_ibge")
    con.execute(
        f"""
        CREATE TABLE municipio_ibge AS
        SELECT
            codigo_rf,
            codigo_ibge,
            nome,
            uf,
            regiao,
            capital = '1' AS capital,
            CAST(latitude AS DOUBLE) AS latitude,
            CAST(longitude AS DOUBLE) AS longitude
        FROM {_csv(MUNICIPIOS_CSV)}
        """
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_municipio_ibge_rf ON municipio_ibge(codigo_rf)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_municipio_ibge_ibge ON municipio_ibge(codigo_ibge)"
    )
    row = con.execute("SELECT count(*) FROM municipio_ibge").fetchone()
    return int(row[0]) if row else 0


def build_cnae_hierarquia(con: duckdb.DuckDBPyConnection) -> int:
    """Uma linha por CNAE da tabela ``cnae`` (RF), com classe/grupo/divisão/seção.

    A ligação é pelo prefixo de classe (5 dígitos), o que cobre também
    subclasses antigas que a RF ainda usa mas saíram da CNAE 2.3.
    """
    print("  cnae_hierarquia …", flush=True)
    con.execute("DROP TABLE IF EXISTS cnae_hierarquia")
    con.execute(
        f"""
        CREATE TABLE cnae_hierarquia AS
        WITH k AS (SELECT * FROM {_csv(CNAE_CSV)})
        SELECT
            c.codigo AS cnae,
            c.descricao AS cnae_desc,
            k.classe,
            k.classe_desc,
            k.grupo,
            k.grupo_desc,
            k.divisao,
            k.divisao_desc,
            k.secao,
            k.secao_desc
        FROM cnae c
        LEFT JOIN k ON k.classe = substr(c.codigo, 1, 5)
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_cnae_hier_cnae ON cnae_hierarquia(cnae)")
    row = con.execute("SELECT count(*) FROM cnae_hierarquia").fetchone()
    return int(row[0]) if row else 0


def build_referencias(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    return {
        "municipio_ibge": build_municipio_ibge(con),
        "cnae_hierarquia": build_cnae_hierarquia(con),
    }
