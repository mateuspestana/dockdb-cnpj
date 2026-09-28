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
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dockdb_cnpj import __email__, __version__  # noqa: E402
from dockdb_cnpj.analytics import agregados_municipio, coortes  # noqa: E402
from dockdb_cnpj.cache import RateLimiter, TTLCache  # noqa: E402
from dockdb_cnpj.cnpj import calcular_dv, formatar, limpar  # noqa: E402
from dockdb_cnpj.config import (  # noqa: E402
    API_CACHE_MAX,
    API_CACHE_TTL,
    API_RATE_LIMIT,
    API_TRUST_PROXY,
    DB_PATH,
    DEFAULT_QUERY_LIMIT,
    EXPORTS_DIR,
    EXPORTS_MAX_AGE_H,
    MAX_QUERY_LIMIT,
)
from dockdb_cnpj.db import connect  # noqa: E402
from dockdb_cnpj.enriquecimento import enriquecer  # noqa: E402
from dockdb_cnpj.manutencao import limpar_exports  # noqa: E402
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

cache: TTLCache | None = TTLCache(API_CACHE_TTL, API_CACHE_MAX) if API_CACHE_TTL > 0 else None
limiter: RateLimiter | None = RateLimiter(API_RATE_LIMIT) if API_RATE_LIMIT > 0 else None

SEM_CACHE = {"/health", "/export", "/docs", "/redoc", "/openapi.json"}
SEM_LIMITE = {"/health"}


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
    if cache is not None:
        cache.clear()


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


def _ip(request: Request) -> str:
    if API_TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


@app.middleware("http")
async def cache_e_rate_limit(request: Request, call_next):
    path = request.url.path
    if limiter is not None and path not in SEM_LIMITE:
        ok, espera = limiter.permitir(_ip(request))
        if not ok:
            return JSONResponse(
                {"detail": f"Limite de {limiter.limite} requisições/min excedido."},
                status_code=429,
                headers={"Retry-After": str(espera)},
            )

    cacheavel = cache is not None and request.method == "GET" and path not in SEM_CACHE
    if not cacheavel:
        return await call_next(request)
    assert cache is not None
    chave = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(request.query_params.multi_items()))
    hit = cache.get(chave)
    if hit is not None:
        return Response(content=hit, media_type="application/json", headers={"X-Cache": "HIT"})

    response = await call_next(request)
    if response.status_code != 200 or "json" not in response.headers.get("content-type", ""):
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
    cache.set(chave, body)
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    headers["X-Cache"] = "MISS"
    return Response(content=body, status_code=200, headers=headers, media_type="application/json")


class QueryBody(BaseModel):
    sql: str = Field(..., description="SELECT ou WITH")
    limit: int = Field(DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT)


class EnriquecerBody(BaseModel):
    cnpjs: list[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_QUERY_LIMIT,
        description="CNPJs (8 ou 14 posições, numéricos ou alfanuméricos)",
    )


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "db": str(DB_PATH),
        "author": f"Matheus Cavalcanti Pestana <{__email__}>",
        "version": __version__,
        "auth": "none — trusted network only (see TODO.md)",
        "cache": cache.stats() if cache is not None else None,
        "rate_limit_por_min": limiter.limite if limiter is not None else None,
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
    cnae_secao: Optional[str] = Query(None, description="Seção CNAE (letra; principal)"),
    cnae_divisao: Optional[str] = Query(None, description="Divisão CNAE (2 dígitos; principal)"),
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
        cnae_secao=cnae_secao,
        cnae_divisao=cnae_divisao,
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
    nivel: str = Query("subclasse", description="tipo=cnae: subclasse|classe|grupo|divisao|secao"),
    limit: int = Query(30, ge=1, le=6000),
    con: duckdb.DuckDBPyConnection = Db,
) -> list[dict]:
    try:
        if tipo == "uf":
            return agregados_uf(con, limit=limit)
        if tipo == "cnae":
            return agregados_cnae(con, uf=uf, nivel=nivel, limit=limit)
        if tipo == "situacao":
            return agregados_situacao(con)
        if tipo == "municipio":
            return agregados_municipio(con, uf=uf, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    raise HTTPException(
        status_code=400, detail="tipo deve ser uf, cnae, situacao ou municipio"
    )


@app.get("/coortes")
def get_coortes(
    freq: str = Query("ano", pattern="^(ano|mes)$"),
    desde: Optional[str] = Query(None, description="AAAA ou AAAAMM"),
    ate: Optional[str] = Query(None, description="AAAA ou AAAAMM"),
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    municipio_ibge: Optional[str] = None,
    cnae: Optional[str] = None,
    cnae_secao: Optional[str] = None,
    cnae_divisao: Optional[str] = None,
    matriz_filial: Optional[str] = None,
    con: duckdb.DuckDBPyConnection = Db,
) -> list[dict]:
    """Aberturas, baixas, saldo e sobrevivência por período (retrato do dump atual)."""
    try:
        return coortes(
            con,
            freq=freq,  # type: ignore[arg-type]
            desde=desde,
            ate=ate,
            uf=uf,
            municipio=municipio,
            municipio_ibge=municipio_ibge,
            cnae=cnae,
            cnae_secao=cnae_secao,
            cnae_divisao=cnae_divisao,
            matriz_filial=matriz_filial,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/enriquecer")
def post_enriquecer(body: EnriquecerBody, con: duckdb.DuckDBPyConnection = Db) -> list[dict]:
    """Busca por lista: uma linha por CNPJ enviado, na mesma ordem."""
    return enriquecer(con, body.cnpjs)


@app.get("/export")
def export_empresas(
    formato: str = Query("csv", pattern="^(csv|parquet)$"),
    params: dict[str, Any] = Depends(_busca_params),
    con: duckdb.DuckDBPyConnection = Db,
):
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    limpar_exports(EXPORTS_DIR, max_idade_h=EXPORTS_MAX_AGE_H)
    dest = EXPORTS_DIR / f"export_{uuid.uuid4().hex}.{formato}"
    try:
        exportar_busca(con, dest, formato=formato, **params)  # type: ignore[arg-type]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    media = "text/csv" if formato == "csv" else "application/octet-stream"
    return FileResponse(
        dest,
        media_type=media,
        filename=f"export.{formato}",
        background=BackgroundTask(dest.unlink, missing_ok=True),
    )


@app.post("/query")
def post_query(body: QueryBody, con: duckdb.DuckDBPyConnection = Db) -> dict[str, Any]:
    try:
        return run_sql(con, body.sql, limit=body.limit)
    except UnsafeSQLError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro na consulta: {e}") from e
