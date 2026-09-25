"""
API FastAPI para consulta CNPJ (DuckDB).

Expor apenas em rede confiável. Autenticação: ver TODO.md.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dockdb_cnpj import __email__, __version__  # noqa: E402
from dockdb_cnpj.config import DB_PATH, DEFAULT_QUERY_LIMIT, MAX_QUERY_LIMIT  # noqa: E402
from dockdb_cnpj.db import connect  # noqa: E402
from dockdb_cnpj.queries import (  # noqa: E402
    agregados_cnae,
    agregados_situacao,
    agregados_uf,
    buscar_empresas,
    buscar_socios,
    consulta_cnpj,
    exportar_busca,
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
        "**Segurança:** sem autenticação — exponha apenas em rede confiável "
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
    uf: Optional[str] = None,
    cnae: Optional[str] = None,
    incluir_cnae_secundario: bool = Query(True),
    municipio: Optional[str] = None,
    municipio_nome: Optional[str] = None,
    q: Optional[str] = None,
    fuzzy: bool = False,
    situacao: Optional[str] = None,
    porte: Optional[str] = None,
    matriz_filial: Optional[str] = None,
    mei: Optional[bool] = None,
    simples: Optional[bool] = None,
    capital_min: Optional[float] = None,
    capital_max: Optional[float] = None,
    data_inicio_de: Optional[str] = None,
    data_inicio_ate: Optional[str] = None,
    limit: int = Query(DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT),
) -> list[dict]:
    assert _con is not None
    return buscar_empresas(
        _con,
        uf=uf,
        cnae=cnae,
        incluir_cnae_secundario=incluir_cnae_secundario,
        municipio=municipio,
        municipio_nome=municipio_nome,
        q=q,
        fuzzy=fuzzy,
        situacao=situacao,
        porte=porte,
        matriz_filial=matriz_filial,
        mei=mei,
        simples=simples,
        capital_min=capital_min,
        capital_max=capital_max,
        data_inicio_de=data_inicio_de,
        data_inicio_ate=data_inicio_ate,
        limit=limit,
    )


@app.get("/socios")
def list_socios(
    nome: Optional[str] = None,
    documento: Optional[str] = None,
    limit: int = Query(DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT),
) -> list[dict]:
    assert _con is not None
    try:
        return buscar_socios(_con, nome=nome, documento=documento, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/agregados/{tipo}")
def get_agregados(
    tipo: str,
    uf: Optional[str] = None,
    limit: int = Query(30, ge=1, le=500),
) -> list[dict]:
    assert _con is not None
    if tipo == "uf":
        return agregados_uf(_con, limit=limit)
    if tipo == "cnae":
        return agregados_cnae(_con, uf=uf, limit=limit)
    if tipo == "situacao":
        return agregados_situacao(_con)
    raise HTTPException(status_code=400, detail="tipo deve ser uf, cnae ou situacao")


@app.get("/export")
def export_empresas(
    formato: str = Query("csv", pattern="^(csv|parquet)$"),
    uf: Optional[str] = None,
    cnae: Optional[str] = None,
    incluir_cnae_secundario: bool = True,
    municipio: Optional[str] = None,
    municipio_nome: Optional[str] = None,
    q: Optional[str] = None,
    fuzzy: bool = False,
    situacao: Optional[str] = None,
    porte: Optional[str] = None,
    matriz_filial: Optional[str] = None,
    mei: Optional[bool] = None,
    simples: Optional[bool] = None,
    capital_min: Optional[float] = None,
    capital_max: Optional[float] = None,
    data_inicio_de: Optional[str] = None,
    data_inicio_ate: Optional[str] = None,
    limit: int = Query(DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT),
):
    assert _con is not None
    out_dir = Path(DB_PATH).parent / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"export.{formato}"
    exportar_busca(
        _con,
        dest,
        formato=formato,  # type: ignore[arg-type]
        uf=uf,
        cnae=cnae,
        incluir_cnae_secundario=incluir_cnae_secundario,
        municipio=municipio,
        municipio_nome=municipio_nome,
        q=q,
        fuzzy=fuzzy,
        situacao=situacao,
        porte=porte,
        matriz_filial=matriz_filial,
        mei=mei,
        simples=simples,
        capital_min=capital_min,
        capital_max=capital_max,
        data_inicio_de=data_inicio_de,
        data_inicio_ate=data_inicio_ate,
        limit=limit,
    )
    media = "text/csv" if formato == "csv" else "application/octet-stream"
    return FileResponse(dest, media_type=media, filename=dest.name)


@app.post("/query")
def post_query(body: QueryBody) -> dict[str, Any]:
    assert _con is not None
    try:
        return run_sql(_con, body.sql, limit=body.limit)
    except UnsafeSQLError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro na consulta: {e}") from e
