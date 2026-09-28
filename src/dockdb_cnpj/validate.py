"""
Validação pós-carga da base CNPJ.

Cada check tem nível ``erro`` (derruba ``ok``) ou ``aviso`` (só informa).

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

from typing import Any, Literal

import duckdb

from dockdb_cnpj.cnpj import sql_dv_expr
from dockdb_cnpj.db import fetch_dicts, scalar

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

Nivel = Literal["erro", "aviso"]


def validar_base(con: duckdb.DuckDBPyConnection, *, persist: bool = True) -> dict[str, Any]:
    """Roda checks básicos e opcionalmente grava em `_validacao`."""
    checks: list[dict[str, Any]] = []

    def add(nome: str, ok: bool, detalhe: str, valor: Any = None, nivel: Nivel = "erro") -> None:
        checks.append(
            {"check": nome, "ok": ok, "nivel": nivel, "detalhe": detalhe, "valor": valor}
        )

    tables = {
        r["table_name"]
        for r in fetch_dicts(
            con,
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'",
        )
    }
    for required in ("empresas", "estabelecimento", "socios", "cnae"):
        add(f"tabela_{required}", required in tables, f"existência de {required}")

    if "estabelecimento" in tables:
        n_est = scalar(con, "SELECT count(*) FROM estabelecimento")
        add("count_estabelecimento", n_est > 0, "estabelecimentos > 0", n_est)
        n_null_cnpj = scalar(
            con, "SELECT count(*) FROM estabelecimento WHERE cnpj IS NULL OR cnpj = ''"
        )
        add(
            "cnpj_preenchido",
            n_null_cnpj == 0,
            "estabelecimento.cnpj sem nulos",
            n_null_cnpj,
        )
        n_formato = scalar(
            con,
            "SELECT count(*) FROM estabelecimento "
            "WHERE NOT regexp_full_match(cnpj, '[0-9A-Z]{12}[0-9]{2}')",
        )
        add(
            "cnpj_formato",
            n_formato == 0,
            "CNPJ com 14 posições [0-9A-Z]{12}[0-9]{2}",
            n_formato,
            nivel="aviso",
        )
        n_dv = scalar(
            con,
            f"SELECT count(*) FROM estabelecimento "
            f"WHERE regexp_full_match(cnpj, '[0-9A-Z]{{12}}[0-9]{{2}}') "
            f"AND substr(cnpj, 13, 2) <> {sql_dv_expr('cnpj')}",
        )
        add("cnpj_dv", n_dv == 0, "CNPJ com dígito verificador inválido", n_dv, nivel="aviso")
        n_alfa = scalar(
            con, "SELECT count(*) FROM estabelecimento WHERE regexp_matches(cnpj, '[A-Z]')"
        )
        add("cnpj_alfanumerico", True, "CNPJs alfanuméricos (informativo)", n_alfa, nivel="aviso")
        orfaos = scalar(
            con,
            """
            SELECT count(*) FROM (
              SELECT DISTINCT est.cnae_fiscal
              FROM estabelecimento est
              LEFT JOIN cnae c ON c.codigo = est.cnae_fiscal
              WHERE est.cnae_fiscal IS NOT NULL AND est.cnae_fiscal <> ''
                AND c.codigo IS NULL
              LIMIT 1000
            )
            """,
        )
        add("cnae_orfaos_amostra", orfaos == 0, "CNAEs sem descrição (amostra)", orfaos)

    if "empresas" in tables:
        n_emp = scalar(con, "SELECT count(*) FROM empresas")
        add("count_empresas", n_emp > 0, "empresas > 0", n_emp)

    if "socios" in tables:
        n_soc = scalar(con, "SELECT count(*) FROM socios")
        add("count_socios", n_soc >= 0, "sócios carregados", n_soc)

    if "estabelecimento_cnae" in tables:
        n_ec = scalar(con, "SELECT count(*) FROM estabelecimento_cnae")
        add("count_estabelecimento_cnae", n_ec > 0, "ponte CNAE", n_ec)

    if "municipio_ibge" in tables and "municipio" in tables:
        sem_ibge = [
            r["codigo"]
            for r in fetch_dicts(
                con,
                """
                SELECT m.codigo FROM municipio m
                LEFT JOIN municipio_ibge mi ON mi.codigo_rf = m.codigo
                WHERE mi.codigo_rf IS NULL AND m.codigo <> '9707'
                ORDER BY 1
                """,
            )
        ]
        add(
            "municipio_ibge_cobertura",
            not sem_ibge,
            "municípios RF sem código IBGE (exceto 9707 EXTERIOR)",
            ",".join(sem_ibge) or 0,
            nivel="aviso",
        )

    ok_all = all(c["ok"] for c in checks if c["nivel"] == "erro")
    result = {"ok": ok_all, "checks": checks}

    if persist:
        con.execute("DROP TABLE IF EXISTS _validacao")
        con.execute(
            """
            CREATE TABLE _validacao (
                check_name VARCHAR,
                ok BOOLEAN,
                nivel VARCHAR,
                detalhe VARCHAR,
                valor VARCHAR
            )
            """
        )
        for c in checks:
            con.execute(
                "INSERT INTO _validacao VALUES (?, ?, ?, ?, ?)",
                [c["check"], c["ok"], c["nivel"], c["detalhe"], str(c["valor"])],
            )

    return result
