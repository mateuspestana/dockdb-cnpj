"""
API FastAPI para consulta CNPJ (DuckDB).

Expor apenas em rede confiável. Autenticação: ver TODO.md.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dockdb_cnpj import __email__, __version__  # noqa: E402
from dockdb_cnpj.cnpj import calcular_dv, formatar, limpar  # noqa: E402
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

_con: duckdb.DuckDBPyConnection | None = None


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


def get_db() -> Iterator[duckdb.DuckDBPyConnection]:
    """Um cursor por requisição — a conexão DuckDB não é thread-safe."""
    if _con is None:
        raise HTTPException(status_code=503, detail="Base não carregada.")
    cur = _con.cursor()
    try:
        yield cur
    finally:
        cur.close()


Db = Depends(get_db)

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
def referencia(con: duckdb.DuckDBPyConnection = Db) -> list[dict]:
    return get_referencia(con)


@app.get("/cnpj/{cnpj}")
def get_cnpj(cnpj: str, con: duckdb.DuckDBPyConnection = Db) -> dict[str, Any]:
    try:
        return consulta_cnpj(con, cnpj)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/dv/{cnpj}")
def get_dv(cnpj: str) -> dict[str, Any]:
    """Valida (14 posições) ou calcula (12 posições) o DV — numérico ou alfanumérico."""
    c = limpar(cnpj)
    try:
        if len(c) == 12:
            dv = calcular_dv(c)
            return {"base": c, "dv": dv, "cnpj": c + dv, "cnpj_formatado": formatar(c + dv)}
        if len(c) == 14:
            esperado = calcular_dv(c[:12])
            return {
                "cnpj": c,
                "cnpj_formatado": formatar(c),
                "dv_valido": esperado == c[12:],
                "dv_esperado": esperado,
                "alfanumerico": not c.isdigit(),
            }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    raise HTTPException(status_code=400, detail="Informe 12 (base) ou 14 posições.")


def _busca_params(
    uf: Optional[str] = None,
    cnae: Optional[str] = None,
    incluir_cnae_secundario: bool = Query(True),
    municipio: Optional[str] = None,
    municipio_nome: Optional[str] = None,
    municipio_ibge: Optional[str] = Query(None, description="Código IBGE (7 dígitos)"),
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
) -> dict[str, Any]:
    return dict(
        uf=uf,
        cnae=cnae,
        incluir_cnae_secundario=incluir_cnae_secundario,
        municipio=municipio,
        municipio_nome=municipio_nome,
        municipio_ibge=municipio_ibge,
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


@app.get("/empresas")
def list_empresas(
    params: dict[str, Any] = Depends(_busca_params),
    con: duckdb.DuckDBPyConnection = Db,
) -> list[dict]:
    try:
        return buscar_empresas(con, **params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/socios")
def list_socios(
    nome: Optional[str] = None,
    documento: Optional[str] = None,
    limit: int = Query(DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT),
    con: duckdb.DuckDBPyConnection = Db,
) -> list[dict]:
    try:
        return buscar_socios(con, nome=nome, documento=documento, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/agregados/{tipo}")
def get_agregados(
    tipo: str,
    uf: Optional[str] = None,
    limit: int = Query(30, ge=1, le=500),
    con: duckdb.DuckDBPyConnection = Db,
) -> list[dict]:
    if tipo == "uf":
        return agregados_uf(con, limit=limit)
    if tipo == "cnae":
        return agregados_cnae(con, uf=uf, limit=limit)
    if tipo == "situacao":
        return agregados_situacao(con)
    raise HTTPException(status_code=400, detail="tipo deve ser uf, cnae ou situacao")


@app.get("/export")
def export_empresas(
    formato: str = Query("csv", pattern="^(csv|parquet)$"),
    params: dict[str, Any] = Depends(_busca_params),
    con: duckdb.DuckDBPyConnection = Db,
):
    out_dir = Path(DB_PATH).parent / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"export_{uuid.uuid4().hex}.{formato}"
    try:
        exportar_busca(con, dest, formato=formato, **params)  # type: ignore[arg-type]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    media = "text/csv" if formato == "csv" else "application/octet-stream"
    return FileResponse(dest, media_type=media, filename=f"export.{formato}")


@app.post("/query")
def post_query(body: QueryBody, con: duckdb.DuckDBPyConnection = Db) -> dict[str, Any]:
    try:
        return run_sql(con, body.sql, limit=body.limit)
    except UnsafeSQLError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro na consulta: {e}") from e
