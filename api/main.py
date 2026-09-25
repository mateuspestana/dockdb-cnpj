"""
API FastAPI para consulta CNPJ (DuckDB).

Expor apenas em rede confiável. Autenticação: ver TODO.md.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dockdb_cnpj import __email__, __version__  # noqa: E402
from dockdb_cnpj.config import DB_PATH, DEFAULT_QUERY_LIMIT, MAX_QUERY_LIMIT  # noqa: E402
from dockdb_cnpj.db import connect  # noqa: E402
from dockdb_cnpj.queries import (  # noqa: E402
    buscar_empresas,
    consulta_cnpj,
    get_referencia,
    run_sql,
)
from dockdb_cnpj.sql_guard import UnsafeSQLError  # noqa: E402

__author__ = "Matheus Cavalcanti Pestana"

_con = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _con
    try:
        _con = connect(DB_PATH, read_only=True)
    except FileNotFoundError as e:
        raise RuntimeError(str(e)) from e
    yield
    if _con is not None:
        _con.close()
        _con = None


app = FastAPI(
    title="DockDB-CNPJ API",
    description=(
        "Consulta à base pública de CNPJ em DuckDB.\n\n"
        "**Segurança:** sem autenticação na v0.1 — exponha apenas em rede confiável "
        "(localhost / VPN / LAN privada). Ver `TODO.md` para auth.\n\n"
        f"Autor: Matheus Cavalcanti Pestana &lt;{__email__}&gt;"
    ),
    version=__version__,
    contact={
        "name": "Matheus Cavalcanti Pestana",
        "email": __email__,
    },
    lifespan=lifespan,
)


class QueryBody(BaseModel):
    sql: str = Field(..., description="SELECT ou WITH")
    limit: int = Field(DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "db": str(DB_PATH),
        "author": f"Matheus Cavalcanti Pestana <{__email__}>",
        "version": __version__,
        "auth": "none — trusted network only (see TODO.md)",
    }


@app.get("/referencia")
def referencia() -> list[dict]:
    assert _con is not None
    return get_referencia(_con)


@app.get("/cnpj/{cnpj}")
def get_cnpj(cnpj: str) -> dict[str, Any]:
    assert _con is not None
    try:
        return consulta_cnpj(_con, cnpj)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/empresas")
def list_empresas(
    uf: str | None = None,
    cnae: str | None = None,
    incluir_cnae_secundario: bool = Query(
        True,
        description="Com cnae, busca também em cnae_fiscal_secundaria",
    ),
    municipio: str | None = None,
    q: str | None = None,
    situacao: str | None = None,
    limit: int = Query(DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT),
) -> list[dict]:
    assert _con is not None
    return buscar_empresas(
        _con,
        uf=uf,
        cnae=cnae,
        incluir_cnae_secundario=incluir_cnae_secundario,
        municipio=municipio,
        q=q,
        situacao=situacao,
        limit=limit,
    )


@app.post("/query")
def post_query(body: QueryBody) -> dict[str, Any]:
    assert _con is not None
    try:
        return run_sql(_con, body.sql, limit=body.limit)
    except UnsafeSQLError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro na consulta: {e}") from e
