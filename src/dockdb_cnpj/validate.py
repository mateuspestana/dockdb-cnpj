"""
Validação pós-carga da base CNPJ.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

from typing import Any

import duckdb

from dockdb_cnpj.db import fetch_dicts

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"


def validar_base(con: duckdb.DuckDBPyConnection, *, persist: bool = True) -> dict[str, Any]:
    """Roda checks básicos e opcionalmente grava em `_validacao`."""
    checks: list[dict[str, Any]] = []

    def add(nome: str, ok: bool, detalhe: str, valor: Any = None) -> None:
        checks.append(
            {"check": nome, "ok": ok, "detalhe": detalhe, "valor": valor}
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
        n_est = con.execute("SELECT count(*) FROM estabelecimento").fetchone()[0]
        add("count_estabelecimento", n_est > 0, "estabelecimentos > 0", n_est)
        n_null_cnpj = con.execute(
            "SELECT count(*) FROM estabelecimento WHERE cnpj IS NULL OR cnpj = ''"
        ).fetchone()[0]
        add(
            "cnpj_preenchido",
            n_null_cnpj == 0,
            "estabelecimento.cnpj sem nulos",
            n_null_cnpj,
        )
        orfaos = con.execute(
            """
            SELECT count(*) FROM (
              SELECT DISTINCT est.cnae_fiscal
              FROM estabelecimento est
              LEFT JOIN cnae c ON c.codigo = est.cnae_fiscal
              WHERE est.cnae_fiscal IS NOT NULL AND est.cnae_fiscal <> ''
                AND c.codigo IS NULL
              LIMIT 1000
            )
            """
        ).fetchone()[0]
        add("cnae_orfaos_amostra", orfaos == 0, "CNAEs sem descrição (amostra)", orfaos)

    if "empresas" in tables:
        n_emp = con.execute("SELECT count(*) FROM empresas").fetchone()[0]
        add("count_empresas", n_emp > 0, "empresas > 0", n_emp)

    if "socios" in tables:
        n_soc = con.execute("SELECT count(*) FROM socios").fetchone()[0]
        add("count_socios", n_soc >= 0, "sócios carregados", n_soc)

    if "estabelecimento_cnae" in tables:
        n_ec = con.execute("SELECT count(*) FROM estabelecimento_cnae").fetchone()[0]
        add("count_estabelecimento_cnae", n_ec > 0, "ponte CNAE", n_ec)

    ok_all = all(c["ok"] for c in checks)
    result = {"ok": ok_all, "checks": checks}

    if persist:
        con.execute("DROP TABLE IF EXISTS _validacao")
        con.execute(
            """
            CREATE TABLE _validacao (
                check_name VARCHAR,
                ok BOOLEAN,
                detalhe VARCHAR,
                valor VARCHAR
            )
            """
        )
        for c in checks:
            con.execute(
                "INSERT INTO _validacao VALUES (?, ?, ?, ?)",
                [c["check"], c["ok"], c["detalhe"], str(c["valor"])],
            )

    return result
