"""
Consultas estruturadas sobre a base CNPJ.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import re
from typing import Any

import duckdb

from dockdb_cnpj.config import DEFAULT_QUERY_LIMIT, MAX_QUERY_LIMIT
from dockdb_cnpj.db import fetch_dicts
from dockdb_cnpj.sql_guard import assert_safe_select

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"


def normalize_cnpj(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) not in (8, 14):
        raise ValueError("CNPJ deve ter 8 (básico) ou 14 dígitos.")
    return digits


def get_referencia(con: duckdb.DuckDBPyConnection) -> list[dict]:
    try:
        return fetch_dicts(con, "SELECT referencia, valor FROM _referencia")
    except duckdb.Error:
        return []


def consulta_cnpj(con: duckdb.DuckDBPyConnection, cnpj: str) -> dict[str, Any]:
    cnpj = normalize_cnpj(cnpj)
    basico = cnpj[:8] if len(cnpj) == 14 else cnpj

    empresas = fetch_dicts(
        con,
        """
        SELECT e.*, nj.descricao AS natureza_juridica_desc
        FROM empresas e
        LEFT JOIN natureza_juridica nj ON nj.codigo = e.natureza_juridica
        WHERE e.cnpj_basico = ?
        """,
        [basico],
    )

    if len(cnpj) == 14:
        estabelecimentos = fetch_dicts(
            con,
            """
            SELECT est.*,
                   c.descricao AS cnae_descricao,
                   m.descricao AS municipio_nome,
                   mot.descricao AS motivo_descricao
            FROM estabelecimento est
            LEFT JOIN cnae c ON c.codigo = est.cnae_fiscal
            LEFT JOIN municipio m ON m.codigo = est.municipio
            LEFT JOIN motivo mot ON mot.codigo = est.motivo_situacao_cadastral
            WHERE est.cnpj = ?
            """,
            [cnpj],
        )
        socios = fetch_dicts(
            con,
            """
            SELECT s.*, q.descricao AS qualificacao_desc
            FROM socios s
            LEFT JOIN qualificacao_socio q ON q.codigo = s.qualificacao_socio
            WHERE s.cnpj = ?
            """,
            [cnpj],
        )
    else:
        estabelecimentos = fetch_dicts(
            con,
            """
            SELECT est.*,
                   c.descricao AS cnae_descricao,
                   m.descricao AS municipio_nome,
                   mot.descricao AS motivo_descricao
            FROM estabelecimento est
            LEFT JOIN cnae c ON c.codigo = est.cnae_fiscal
            LEFT JOIN municipio m ON m.codigo = est.municipio
            LEFT JOIN motivo mot ON mot.codigo = est.motivo_situacao_cadastral
            WHERE est.cnpj_basico = ?
            ORDER BY est.matriz_filial, est.cnpj
            """,
            [basico],
        )
        socios = fetch_dicts(
            con,
            """
            SELECT s.*, q.descricao AS qualificacao_desc
            FROM socios s
            LEFT JOIN qualificacao_socio q ON q.codigo = s.qualificacao_socio
            WHERE s.cnpj_basico = ?
            """,
            [basico],
        )

    simples = fetch_dicts(
        con,
        "SELECT * FROM simples WHERE cnpj_basico = ?",
        [basico],
    )

    return {
        "cnpj_consultado": cnpj,
        "empresas": empresas,
        "estabelecimentos": estabelecimentos,
        "socios": socios,
        "simples": simples,
    }


def buscar_empresas(
    con: duckdb.DuckDBPyConnection,
    *,
    uf: str | None = None,
    cnae: str | None = None,
    incluir_cnae_secundario: bool = True,
    municipio: str | None = None,
    q: str | None = None,
    situacao: str | None = None,
    limit: int = DEFAULT_QUERY_LIMIT,
) -> list[dict]:
    """Busca estabelecimentos. Com ``cnae``, por padrão também casa secundários."""
    limit = max(1, min(int(limit), MAX_QUERY_LIMIT))
    clauses: list[str] = []
    params: list[Any] = []
    cnae_code = re.sub(r"\D", "", cnae) if cnae else ""

    if uf:
        clauses.append("est.uf = ?")
        params.append(uf.upper())
    if cnae_code:
        if incluir_cnae_secundario:
            # Lista CSV da RF (ex.: "4784900,4712100") — match exato por código
            clauses.append(
                "("
                "est.cnae_fiscal = ? OR "
                "list_contains("
                "string_split(COALESCE(est.cnae_fiscal_secundaria, ''), ','), ?"
                ")"
                ")"
            )
            params.extend([cnae_code, cnae_code])
        else:
            clauses.append("est.cnae_fiscal = ?")
            params.append(cnae_code)
    if municipio:
        clauses.append("est.municipio = ?")
        params.append(municipio)
    if situacao:
        clauses.append("est.situacao_cadastral = ?")
        params.append(situacao)
    if q:
        clauses.append("(e.razao_social ILIKE ? OR est.nome_fantasia ILIKE ?)")
        like = f"%{q}%"
        params.extend([like, like])

    if cnae_code and incluir_cnae_secundario:
        cnae_origem_expr = """
            CASE
                WHEN est.cnae_fiscal = ? THEN 'principal'
                WHEN list_contains(
                    string_split(COALESCE(est.cnae_fiscal_secundaria, ''), ','), ?
                ) THEN 'secundario'
                ELSE NULL
            END AS cnae_origem
        """
        cnae_origem_params: list[Any] = [cnae_code, cnae_code]
    elif cnae_code:
        cnae_origem_expr = "'principal' AS cnae_origem"
        cnae_origem_params = []
    else:
        cnae_origem_expr = "NULL AS cnae_origem"
        cnae_origem_params = []

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT
            est.cnpj,
            e.razao_social,
            est.nome_fantasia,
            est.uf,
            est.municipio,
            m.descricao AS municipio_nome,
            est.cnae_fiscal,
            c.descricao AS cnae_descricao,
            est.cnae_fiscal_secundaria,
            {cnae_origem_expr},
            est.situacao_cadastral,
            est.matriz_filial,
            e.capital_social
        FROM estabelecimento est
        JOIN empresas e ON e.cnpj_basico = est.cnpj_basico
        LEFT JOIN municipio m ON m.codigo = est.municipio
        LEFT JOIN cnae c ON c.codigo = est.cnae_fiscal
        {where}
        LIMIT {limit}
    """
    # SELECT params (cnae_origem) vêm antes dos WHERE params no DuckDB prepared?
    # Na verdade os `?` seguem a ordem de aparição no SQL: SELECT first, then WHERE.
    # Aqui cnae_origem está no SELECT (antes do WHERE), então: origem params + where params.
    return fetch_dicts(con, sql, cnae_origem_params + params)


def run_sql(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    *,
    limit: int = DEFAULT_QUERY_LIMIT,
) -> dict[str, Any]:
    cleaned = assert_safe_select(sql)
    limit = max(1, min(int(limit), MAX_QUERY_LIMIT))
    # Envolve em subquery se ainda não houver LIMIT explícito no fim
    wrapped = f"SELECT * FROM ({cleaned}) AS _q LIMIT {limit}"
    rows = fetch_dicts(con, wrapped)
    cols = list(rows[0].keys()) if rows else []
    return {"columns": cols, "rows": rows, "count": len(rows)}
