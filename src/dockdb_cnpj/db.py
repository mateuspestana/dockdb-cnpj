"""
Conexão DuckDB (leitura / escrita).

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from dockdb_cnpj.config import DB_PATH, ensure_dirs

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"


def connect(db_path: Path | str | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Abre conexão DuckDB. Em read_only o arquivo deve existir."""
    path = Path(db_path) if db_path else DB_PATH
    if not read_only:
        ensure_dirs()
        path.parent.mkdir(parents=True, exist_ok=True)
    if read_only and not path.exists():
        raise FileNotFoundError(
            f"Base DuckDB não encontrada em {path}. "
            "Rode scripts/download_cnpj.py e scripts/load_duckdb.py primeiro."
        )
    return duckdb.connect(str(path), read_only=read_only)


def fetch_dicts(con: duckdb.DuckDBPyConnection, sql: str, params: list | tuple | None = None) -> list[dict]:
    if params:
        cur = con.execute(sql, params)
    else:
        cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
