"""
Séries e agregados para pesquisa: coortes de abertura/baixa e mapa por município.

As coortes são calculadas sobre **um único dump** (retrato atual):

- ``aberturas``: estabelecimentos com ``data_inicio_atividades`` no período;
- ``baixas``: estabelecimentos hoje baixados (situação 08) cuja
  ``data_situacao_cadastral`` cai no período;
- ``ativas_hoje`` / ``taxa_sobrevivencia``: das aberturas do período, quantas
  seguem ativas (situação 02) na data de referência do dump.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

from typing import Any, Literal

import duckdb

from dockdb_cnpj.db import fetch_dicts
from dockdb_cnpj.queries import (
    municipio_ibge_para_rf,
    table_exists,
    codigos_cnae_hierarquia,
    normalize_digits,
)

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

Frequencia = Literal["ano", "mes"]


def _filtros(
    con: duckdb.DuckDBPyConnection,
    *,
    uf: str | None,
    municipio: str | None,
    municipio_ibge: str | None,
    cnae: str | None,
    cnae_secao: str | None,
    cnae_divisao: str | None,
    matriz_filial: str | None,
) -> tuple[list[str], list[Any]] | None:
    """Cláusulas sobre ``est``; None quando algum filtro não casa com nada."""
    clauses: list[str] = []
    params: list[Any] = []
    if uf:
        clauses.append("est.uf = ?")
        params.append(uf.upper())
    if municipio:
        clauses.append("est.municipio = ?")
        params.append(normalize_digits(municipio))
    if municipio_ibge:
        rf = municipio_ibge_para_rf(con, municipio_ibge)
        if not rf:
            return None
        clauses.append(f"est.municipio IN ({', '.join('?' for _ in rf)})")
        params.extend(rf)
    if cnae:
        clauses.append("est.cnae_fiscal = ?")
        params.append(normalize_digits(cnae))
    if cnae_secao or cnae_divisao:
        codigos = codigos_cnae_hierarquia(con, secao=cnae_secao, divisao=cnae_divisao)
        if not codigos:
            return None
        clauses.append(f"est.cnae_fiscal IN ({', '.join('?' for _ in codigos)})")
        params.extend(codigos)
    if matriz_filial:
        clauses.append("est.matriz_filial = ?")
        params.append(matriz_filial)
    return clauses, params


def coortes(
    con: duckdb.DuckDBPyConnection,
    *,
    freq: Frequencia = "ano",
    desde: str | None = None,
    ate: str | None = None,
    uf: str | None = None,
    municipio: str | None = None,
    municipio_ibge: str | None = None,
    cnae: str | None = None,
    cnae_secao: str | None = None,
    cnae_divisao: str | None = None,
    matriz_filial: str | None = None,
) -> list[dict]:
    """Aberturas, baixas, saldo e sobrevivência por ano (AAAA) ou mês (AAAAMM)."""
    if freq not in ("ano", "mes"):
        raise ValueError("freq deve ser 'ano' ou 'mes'")
    n = 4 if freq == "ano" else 6
    f = _filtros(
        con,
        uf=uf,
        municipio=municipio,
        municipio_ibge=municipio_ibge,
        cnae=cnae,
        cnae_secao=cnae_secao,
        cnae_divisao=cnae_divisao,
        matriz_filial=matriz_filial,
    )
    if f is None:
        return []
    clauses, params = f
    extra = "".join(f" AND {c}" for c in clauses)

    periodo_clauses: list[str] = []
    periodo_params: list[Any] = []
    if desde:
        periodo_clauses.append("periodo >= ?")
        periodo_params.append(normalize_digits(desde)[:n])
    if ate:
        periodo_clauses.append("periodo <= ?")
        periodo_params.append(normalize_digits(ate)[:n])
    where_periodo = ("WHERE " + " AND ".join(periodo_clauses)) if periodo_clauses else ""

    sql = f"""
        WITH ab AS (
            SELECT
                substr(est.data_inicio_atividades, 1, {n}) AS periodo,
                count(*) AS aberturas,
                count(*) FILTER (WHERE est.situacao_cadastral = '02') AS ativas_hoje
            FROM estabelecimento est
            WHERE regexp_full_match(est.data_inicio_atividades, '[0-9]{{8}}'){extra}
            GROUP BY 1
        ),
        bx AS (
            SELECT
                substr(est.data_situacao_cadastral, 1, {n}) AS periodo,
                count(*) AS baixas
            FROM estabelecimento est
            WHERE est.situacao_cadastral = '08'
              AND regexp_full_match(est.data_situacao_cadastral, '[0-9]{{8}}'){extra}
            GROUP BY 1
        ),
        j AS (
            SELECT
                COALESCE(ab.periodo, bx.periodo) AS periodo,
                COALESCE(ab.aberturas, 0) AS aberturas,
                COALESCE(bx.baixas, 0) AS baixas,
                COALESCE(ab.ativas_hoje, 0) AS ativas_hoje
            FROM ab FULL OUTER JOIN bx ON ab.periodo = bx.periodo
        )
        SELECT
            periodo,
            aberturas,
            baixas,
            aberturas - baixas AS saldo,
            ativas_hoje,
            CASE WHEN aberturas > 0 THEN round(ativas_hoje / aberturas, 4) END
                AS taxa_sobrevivencia
        FROM j
        {where_periodo}
        ORDER BY periodo
    """
    return fetch_dicts(con, sql, params + params + periodo_params)


def agregados_municipio(
    con: duckdb.DuckDBPyConnection,
    *,
    uf: str | None = None,
    cnae: str | None = None,
    cnae_secao: str | None = None,
    limit: int = 6000,
) -> list[dict]:
    """Estabelecimentos ativos por município, com código IBGE e centroide (p/ mapas)."""
    if not table_exists(con, "municipio_ibge"):
        raise ValueError("Agregado por município exige municipio_ibge — rode `dockdb-cnpj upgrade`.")
    f = _filtros(
        con,
        uf=uf,
        municipio=None,
        municipio_ibge=None,
        cnae=cnae,
        cnae_secao=cnae_secao,
        cnae_divisao=None,
        matriz_filial=None,
    )
    if f is None:
        return []
    clauses, params = f
    extra = "".join(f" AND {c}" for c in clauses)
    return fetch_dicts(
        con,
        f"""
        SELECT
            mi.codigo_ibge AS municipio_ibge,
            mi.nome,
            mi.uf,
            mi.latitude,
            mi.longitude,
            count(*) AS n
        FROM estabelecimento est
        JOIN municipio_ibge mi ON mi.codigo_rf = est.municipio
        WHERE est.situacao_cadastral = '02'{extra}
        GROUP BY 1, 2, 3, 4, 5
        ORDER BY n DESC
        LIMIT ?
        """,
        params + [limit],
    )
