"""
CLI Typer — DockDB-CNPJ.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import json

import typer

from dockdb_cnpj import __email__, __version__
from dockdb_cnpj.config import DB_PATH, DEFAULT_QUERY_LIMIT
from dockdb_cnpj.db import connect
from dockdb_cnpj.queries import buscar_empresas, consulta_cnpj, get_referencia, run_sql
from dockdb_cnpj.sql_guard import UnsafeSQLError

__author__ = "Matheus Cavalcanti Pestana"

app = typer.Typer(
    help=(
        "DockDB-CNPJ — consulta CNPJ em DuckDB\n"
        f"Autor: Matheus Cavalcanti Pestana <{__email__}>"
    ),
    no_args_is_help=True,
)


def _con():
    return connect(DB_PATH, read_only=True)


@app.callback()
def _root(
    version: bool = typer.Option(False, "--version", help="Mostra a versão."),
) -> None:
    if version:
        typer.echo(
            f"dockdb-cnpj {__version__} — Matheus Cavalcanti Pestana <{__email__}>"
        )
        raise typer.Exit()


@app.command("info")
def info_cmd() -> None:
    """Mostra metadados da base (_referencia)."""
    with _con() as con:
        rows = get_referencia(con)
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))


@app.command("cnpj")
def cnpj_cmd(
    cnpj: str = typer.Argument(..., help="CNPJ com 8 ou 14 dígitos."),
) -> None:
    """Consulta empresa / estabelecimentos / sócios."""
    with _con() as con:
        data = consulta_cnpj(con, cnpj)
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


@app.command("buscar")
def buscar_cmd(
    uf: str | None = typer.Option(None, help="UF, ex: SP"),
    cnae: str | None = typer.Option(None, help="CNAE (principal e, por padrão, secundário)"),
    incluir_secundario: bool = typer.Option(
        True,
        "--incluir-secundario/--somente-principal",
        help="Com --cnae, inclui cnae_fiscal_secundaria (padrão: sim).",
    ),
    municipio: str | None = typer.Option(None, help="Código município RF"),
    q: str | None = typer.Option(None, help="Texto em razão social / fantasia"),
    situacao: str | None = typer.Option(None, help="Situação cadastral"),
    limit: int = typer.Option(DEFAULT_QUERY_LIMIT, help="Limite de linhas"),
) -> None:
    """Busca por filtros (UF, CNAE, texto, etc.)."""
    with _con() as con:
        rows = buscar_empresas(
            con,
            uf=uf,
            cnae=cnae,
            incluir_cnae_secundario=incluir_secundario,
            municipio=municipio,
            q=q,
            situacao=situacao,
            limit=limit,
        )
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2, default=str))


@app.command("sql")
def sql_cmd(
    consulta: str = typer.Argument(..., help="SELECT ou WITH"),
    limit: int = typer.Option(DEFAULT_QUERY_LIMIT, help="Limite de linhas"),
) -> None:
    """Executa SQL livre (somente SELECT/WITH)."""
    try:
        with _con() as con:
            result = run_sql(con, consulta, limit=limit)
    except UnsafeSQLError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
