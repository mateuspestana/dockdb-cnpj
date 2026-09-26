"""
Consultas estruturadas sobre a base CNPJ.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Literal

import duckdb

from dockdb_cnpj.config import DEFAULT_QUERY_LIMIT, MAX_QUERY_LIMIT
from dockdb_cnpj.db import fetch_dicts
from dockdb_cnpj.sql_guard import assert_safe_select

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

ExportFormat = Literal["csv", "parquet"]

SITUACAO_LABEL = {
    "01": "Nula",
    "02": "Ativa",
    "03": "Suspensa",
    "04": "Inapta",
    "08": "Baixada",
}

PORTE_LABEL = {
    "00": "Não informado",
    "01": "Microempresa (ME)",
    "03": "Empresa de pequeno porte (EPP)",
    "05": "Demais",
}

MATRIZ_FILIAL_LABEL = {"1": "Matriz", "2": "Filial"}


def normalize_cnpj(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) not in (8, 14):
        raise ValueError("CNPJ deve ter 8 (básico) ou 14 dígitos.")
    return digits


def normalize_digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def get_referencia(con: duckdb.DuckDBPyConnection) -> list[dict]:
    try:
        return fetch_dicts(con, "SELECT referencia, valor FROM _referencia")
    except duckdb.Error:
        return []


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    row = con.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
        LIMIT 1
        """,
        [name],
    ).fetchone()
    return row is not None


def _fts_ready(con: duckdb.DuckDBPyConnection) -> bool:
    try:
        rows = fetch_dicts(
            con,
            "SELECT valor FROM _referencia WHERE referencia = 'fts' LIMIT 1",
        )
        return bool(rows and rows[0].get("valor") == "1")
    except duckdb.Error:
        return False


def consulta_cnpj(con: duckdb.DuckDBPyConnection, cnpj: str) -> dict[str, Any]:
    """Consulta completa com descrições de códigos decodificados."""
    cnpj = normalize_cnpj(cnpj)
    basico = cnpj[:8] if len(cnpj) == 14 else cnpj

    empresas = fetch_dicts(
        con,
        """
        SELECT
            e.*,
            nj.descricao AS natureza_juridica_desc,
            qr.descricao AS qualificacao_responsavel_desc
        FROM empresas e
        LEFT JOIN natureza_juridica nj ON nj.codigo = e.natureza_juridica
        LEFT JOIN qualificacao_socio qr ON qr.codigo = e.qualificacao_responsavel
        WHERE e.cnpj_basico = ?
        """,
        [basico],
    )
    for emp in empresas:
        porte = emp.get("porte_empresa")
        emp["porte_empresa_desc"] = PORTE_LABEL.get(str(porte or ""), porte)

    estab_sql = """
        SELECT est.*,
               c.descricao AS cnae_descricao,
               m.descricao AS municipio_nome,
               mot.descricao AS motivo_descricao,
               p.descricao AS pais_nome
        FROM estabelecimento est
        LEFT JOIN cnae c ON c.codigo = est.cnae_fiscal
        LEFT JOIN municipio m ON m.codigo = est.municipio
        LEFT JOIN motivo mot ON mot.codigo = est.motivo_situacao_cadastral
        LEFT JOIN pais p ON p.codigo = est.pais
        WHERE {where}
        {order}
    """

    if len(cnpj) == 14:
        estabelecimentos = fetch_dicts(
            con, estab_sql.format(where="est.cnpj = ?", order=""), [cnpj]
        )
        socios = fetch_dicts(
            con,
            """
            SELECT s.*,
                   q.descricao AS qualificacao_desc,
                   qr.descricao AS qualificacao_representante_desc,
                   p.descricao AS pais_nome
            FROM socios s
            LEFT JOIN qualificacao_socio q ON q.codigo = s.qualificacao_socio
            LEFT JOIN qualificacao_socio qr
                ON qr.codigo = s.qualificacao_representante_legal
            LEFT JOIN pais p ON p.codigo = s.pais
            WHERE s.cnpj = ?
            """,
            [cnpj],
        )
    else:
        estabelecimentos = fetch_dicts(
            con,
            estab_sql.format(
                where="est.cnpj_basico = ?",
                order="ORDER BY est.matriz_filial, est.cnpj",
            ),
            [basico],
        )
        socios = fetch_dicts(
            con,
            """
            SELECT s.*,
                   q.descricao AS qualificacao_desc,
                   qr.descricao AS qualificacao_representante_desc,
                   p.descricao AS pais_nome
            FROM socios s
            LEFT JOIN qualificacao_socio q ON q.codigo = s.qualificacao_socio
            LEFT JOIN qualificacao_socio qr
                ON qr.codigo = s.qualificacao_representante_legal
            LEFT JOIN pais p ON p.codigo = s.pais
            WHERE s.cnpj_basico = ?
            """,
            [basico],
        )

    for est in estabelecimentos:
        sit = str(est.get("situacao_cadastral") or "")
        est["situacao_cadastral_desc"] = SITUACAO_LABEL.get(sit, sit)
        mf = str(est.get("matriz_filial") or "")
        est["matriz_filial_desc"] = MATRIZ_FILIAL_LABEL.get(mf, mf)

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


def _build_busca_filters(
    *,
    uf: str | None,
    cnae: str | None,
    incluir_cnae_secundario: bool,
    municipio: str | None,
    municipio_nome: str | None,
    q: str | None,
    situacao: str | None,
    porte: str | None,
    matriz_filial: str | None,
    mei: bool | None,
    simples: bool | None,
    capital_min: float | None,
    capital_max: float | None,
    data_inicio_de: str | None,
    data_inicio_ate: str | None,
    use_cnae_bridge: bool,
    fuzzy: bool,
) -> tuple[list[str], list[Any], str, list[Any], bool]:
    """Retorna (where_clauses, where_params, cnae_origem_expr, origem_params, need_simples)."""
    clauses: list[str] = []
    params: list[Any] = []
    need_simples = mei is not None or simples is not None
    cnae_code = normalize_digits(cnae) if cnae else ""

    if uf:
        clauses.append("est.uf = ?")
        params.append(uf.upper())

    if cnae_code:
        if use_cnae_bridge and incluir_cnae_secundario:
            clauses.append(
                "EXISTS ("
                "SELECT 1 FROM estabelecimento_cnae ec "
                "WHERE ec.cnpj = est.cnpj AND ec.cnae = ?"
                ")"
            )
            params.append(cnae_code)
        elif incluir_cnae_secundario:
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
        # código RF (só dígitos) ou nome
        if municipio.isdigit() or (normalize_digits(municipio) == municipio and municipio):
            clauses.append("est.municipio = ?")
            params.append(normalize_digits(municipio) or municipio)
        else:
            clauses.append("m.descricao ILIKE ?")
            params.append(f"%{municipio}%")
    if municipio_nome:
        clauses.append("m.descricao ILIKE ?")
        params.append(f"%{municipio_nome}%")

    if situacao:
        clauses.append("est.situacao_cadastral = ?")
        params.append(situacao)
    if porte:
        clauses.append("e.porte_empresa = ?")
        params.append(porte)
    if matriz_filial:
        clauses.append("est.matriz_filial = ?")
        params.append(matriz_filial)
    if mei is True:
        clauses.append("UPPER(COALESCE(si.opcao_mei, '')) = 'S'")
    elif mei is False:
        clauses.append("(si.opcao_mei IS NULL OR UPPER(si.opcao_mei) <> 'S')")
    if simples is True:
        clauses.append("UPPER(COALESCE(si.opcao_simples, '')) = 'S'")
    elif simples is False:
        clauses.append("(si.opcao_simples IS NULL OR UPPER(si.opcao_simples) <> 'S')")
    if capital_min is not None:
        clauses.append("e.capital_social >= ?")
        params.append(float(capital_min))
    if capital_max is not None:
        clauses.append("e.capital_social <= ?")
        params.append(float(capital_max))
    if data_inicio_de:
        clauses.append("est.data_inicio_atividades >= ?")
        params.append(normalize_digits(data_inicio_de))
    if data_inicio_ate:
        clauses.append("est.data_inicio_atividades <= ?")
        params.append(normalize_digits(data_inicio_ate))

    if q:
        if fuzzy:
            clauses.append(
                "("
                "jaro_winkler_similarity(LOWER(COALESCE(e.razao_social, '')), LOWER(?)) >= 0.85 "
                "OR jaro_winkler_similarity(LOWER(COALESCE(est.nome_fantasia, '')), LOWER(?)) >= 0.85 "
                "OR e.razao_social ILIKE ? OR est.nome_fantasia ILIKE ?"
                ")"
            )
            like = f"%{q}%"
            params.extend([q, q, like, like])
        else:
            # FTS quando disponível é ligado no caller; aqui ILIKE padrão
            clauses.append("(e.razao_social ILIKE ? OR est.nome_fantasia ILIKE ?)")
            like = f"%{q}%"
            params.extend([like, like])

    if cnae_code and incluir_cnae_secundario:
        if use_cnae_bridge:
            cnae_origem_expr = """
                CASE
                    WHEN est.cnae_fiscal = ? THEN 'principal'
                    WHEN EXISTS (
                        SELECT 1 FROM estabelecimento_cnae ec
                        WHERE ec.cnpj = est.cnpj AND ec.cnae = ? AND ec.tipo = 'secundario'
                    ) THEN 'secundario'
                    ELSE NULL
                END AS cnae_origem
            """
            cnae_origem_params: list[Any] = [cnae_code, cnae_code]
        else:
            cnae_origem_expr = """
                CASE
                    WHEN est.cnae_fiscal = ? THEN 'principal'
                    WHEN list_contains(
                        string_split(COALESCE(est.cnae_fiscal_secundaria, ''), ','), ?
                    ) THEN 'secundario'
                    ELSE NULL
                END AS cnae_origem
            """
            cnae_origem_params = [cnae_code, cnae_code]
    elif cnae_code:
        cnae_origem_expr = "'principal' AS cnae_origem"
        cnae_origem_params = []
    else:
        cnae_origem_expr = "NULL AS cnae_origem"
        cnae_origem_params = []

    return clauses, params, cnae_origem_expr, cnae_origem_params, need_simples


def buscar_empresas(
    con: duckdb.DuckDBPyConnection,
    *,
    uf: str | None = None,
    cnae: str | None = None,
    incluir_cnae_secundario: bool = True,
    municipio: str | None = None,
    municipio_nome: str | None = None,
    q: str | None = None,
    situacao: str | None = None,
    porte: str | None = None,
    matriz_filial: str | None = None,
    mei: bool | None = None,
    simples: bool | None = None,
    capital_min: float | None = None,
    capital_max: float | None = None,
    data_inicio_de: str | None = None,
    data_inicio_ate: str | None = None,
    fuzzy: bool = False,
    limit: int = DEFAULT_QUERY_LIMIT,
) -> list[dict]:
    """Busca estabelecimentos com filtros ricos (v0.4+) e ponte CNAE/FTS (v0.5)."""
    limit = max(1, min(int(limit), MAX_QUERY_LIMIT))
    use_bridge = _table_exists(con, "estabelecimento_cnae")
    use_fts = bool(q) and not fuzzy and _fts_ready(con)

    clauses, params, cnae_origem_expr, cnae_origem_params, need_simples = _build_busca_filters(
        uf=uf,
        cnae=cnae,
        incluir_cnae_secundario=incluir_cnae_secundario,
        municipio=municipio,
        municipio_nome=municipio_nome,
        q=None if use_fts else q,
        situacao=situacao,
        porte=porte,
        matriz_filial=matriz_filial,
        mei=mei,
        simples=simples,
        capital_min=capital_min,
        capital_max=capital_max,
        data_inicio_de=data_inicio_de,
        data_inicio_ate=data_inicio_ate,
        use_cnae_bridge=use_bridge,
        fuzzy=fuzzy,
    )
    if use_fts and q:
        # BM25: exige score e ordena — sem ORDER BY o LIMIT pega matches fracos (ex.: só "DO")
        clauses.append("fts_main_empresas.match_bm25(e.cnpj_basico, ?) IS NOT NULL")
        params.append(q)
        fts_score_select = "fts_main_empresas.match_bm25(e.cnpj_basico, ?) AS _fts_score,"
        fts_score_params: list[Any] = [q]
        order_by = "ORDER BY _fts_score DESC NULLS LAST"
    else:
        fts_score_select = ""
        fts_score_params = []
        order_by = ""

    simples_join = (
        "LEFT JOIN simples si ON si.cnpj_basico = est.cnpj_basico" if need_simples else ""
    )
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
            {fts_score_select}
            est.situacao_cadastral,
            est.matriz_filial,
            e.porte_empresa,
            e.capital_social,
            est.data_inicio_atividades
        FROM estabelecimento est
        JOIN empresas e ON e.cnpj_basico = est.cnpj_basico
        LEFT JOIN municipio m ON m.codigo = est.municipio
        LEFT JOIN cnae c ON c.codigo = est.cnae_fiscal
        {simples_join}
        {where}
        {order_by}
        LIMIT {limit}
    """
    # Ordem dos ?: SELECT (cnae_origem + fts_score) depois WHERE
    return fetch_dicts(con, sql, cnae_origem_params + fts_score_params + params)


def buscar_socios(
    con: duckdb.DuckDBPyConnection,
    *,
    nome: str | None = None,
    documento: str | None = None,
    limit: int = DEFAULT_QUERY_LIMIT,
) -> list[dict]:
    """Busca sócios por nome e/ou CPF/CNPJ (dígitos)."""
    if not nome and not documento:
        raise ValueError("Informe nome e/ou documento do sócio.")
    limit = max(1, min(int(limit), MAX_QUERY_LIMIT))
    clauses: list[str] = []
    params: list[Any] = []
    if nome:
        clauses.append("s.nome_socio ILIKE ?")
        params.append(f"%{nome}%")
    if documento:
        doc = normalize_digits(documento)
        clauses.append(
            "(regexp_replace(COALESCE(s.cnpj_cpf_socio, ''), '[^0-9]', '', 'g') = ? "
            "OR s.cnpj_cpf_socio ILIKE ?)"
        )
        params.extend([doc, f"%{doc}%"])
    where = " AND ".join(clauses)
    sql = f"""
        SELECT
            s.cnpj,
            s.cnpj_basico,
            s.nome_socio,
            s.cnpj_cpf_socio,
            s.identificador_de_socio,
            s.qualificacao_socio,
            q.descricao AS qualificacao_desc,
            s.data_entrada_sociedade,
            e.razao_social,
            est.uf,
            est.situacao_cadastral
        FROM socios s
        LEFT JOIN qualificacao_socio q ON q.codigo = s.qualificacao_socio
        LEFT JOIN empresas e ON e.cnpj_basico = s.cnpj_basico
        LEFT JOIN estabelecimento est
            ON est.cnpj = s.cnpj
        WHERE {where}
        LIMIT {limit}
    """
    return fetch_dicts(con, sql, params)


def exportar_busca(
    con: duckdb.DuckDBPyConnection,
    path: Path | str,
    *,
    formato: ExportFormat = "csv",
    limit: int = MAX_QUERY_LIMIT,
    **busca_kwargs: Any,
) -> Path:
    """Executa buscar_empresas e grava CSV ou Parquet."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    rows = buscar_empresas(con, limit=limit, **busca_kwargs)
    if formato == "csv":
        if not rows:
            dest.write_text("", encoding="utf-8")
            return dest
        with dest.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    elif formato == "parquet":
        import pandas as pd

        pd.DataFrame(rows).to_parquet(dest, index=False)
    else:
        raise ValueError("formato deve ser 'csv' ou 'parquet'")
    return dest


def agregados_uf(con: duckdb.DuckDBPyConnection, *, limit: int = 30) -> list[dict]:
    return fetch_dicts(
        con,
        """
        SELECT uf, count(*) AS estabelecimentos
        FROM estabelecimento
        GROUP BY uf
        ORDER BY estabelecimentos DESC
        LIMIT ?
        """,
        [limit],
    )


def agregados_cnae(
    con: duckdb.DuckDBPyConnection,
    *,
    uf: str | None = None,
    limit: int = 30,
) -> list[dict]:
    clauses = ["est.situacao_cadastral = '02'"]
    params: list[Any] = []
    if uf:
        clauses.append("est.uf = ?")
        params.append(uf.upper())
    params.append(limit)
    where = " AND ".join(clauses)
    return fetch_dicts(
        con,
        f"""
        SELECT est.cnae_fiscal AS cnae, c.descricao, count(*) AS n
        FROM estabelecimento est
        LEFT JOIN cnae c ON c.codigo = est.cnae_fiscal
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY n DESC
        LIMIT ?
        """,
        params,
    )


def agregados_situacao(con: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = fetch_dicts(
        con,
        """
        SELECT situacao_cadastral AS situacao, count(*) AS n
        FROM estabelecimento
        GROUP BY 1
        ORDER BY n DESC
        """,
    )
    for r in rows:
        r["situacao_desc"] = SITUACAO_LABEL.get(str(r["situacao"]), r["situacao"])
    return rows


def run_sql(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    *,
    limit: int = DEFAULT_QUERY_LIMIT,
) -> dict[str, Any]:
    cleaned = assert_safe_select(sql)
    limit = max(1, min(int(limit), MAX_QUERY_LIMIT))
    wrapped = f"SELECT * FROM ({cleaned}) AS _q LIMIT {limit}"
    rows = fetch_dicts(con, wrapped)
    cols = list(rows[0].keys()) if rows else []
    return {"columns": cols, "rows": rows, "count": len(rows)}
