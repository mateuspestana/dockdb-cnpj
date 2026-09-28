"""
Tabelas auxiliares versionadas no pacote (não vêm da Receita).

- ``municipio_ibge``: código RF (TOM/SIAFI) → código IBGE, UF, região e centroide.

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


def build_referencias(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    return {"municipio_ibge": build_municipio_ibge(con)}
