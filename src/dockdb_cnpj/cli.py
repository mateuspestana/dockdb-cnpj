"""
CLI Typer — DockDB-CNPJ.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from dockdb_cnpj import __email__, __version__
from dockdb_cnpj.config import DB_PATH, DEFAULT_QUERY_LIMIT, MAX_QUERY_LIMIT
from dockdb_cnpj.db import connect
from dockdb_cnpj.queries import (
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
from dockdb_cnpj.sql_guard import UnsafeSQLError
from dockdb_cnpj.validate import validar_base

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


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", help="Mostra a versão.", is_eager=True
    ),
) -> None:
    if version:
        typer.echo(
            f"dockdb-cnpj {__version__} — Matheus Cavalcanti Pestana <{__email__}>"
        )
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
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
    uf: Optional[str] = typer.Option(None, help="UF, ex: SP"),
    cnae: Optional[str] = typer.Option(None, help="CNAE (principal/secundário)"),
    incluir_secundario: bool = typer.Option(
        True,
        "--incluir-secundario/--somente-principal",
        help="Com --cnae, inclui secundários (padrão: sim).",
    ),
    municipio: Optional[str] = typer.Option(
        None, help="Código RF ou nome do município"
    ),
    municipio_nome: Optional[str] = typer.Option(None, help="Nome do município"),
    q: Optional[str] = typer.Option(None, help="Texto em razão social / fantasia"),
    fuzzy: bool = typer.Option(False, help="Busca fuzzy (Jaro-Winkler) em q"),
    situacao: Optional[str] = typer.Option(None, help="Situação cadastral"),
    porte: Optional[str] = typer.Option(None, help="Porte (00/01/03/05)"),
    matriz_filial: Optional[str] = typer.Option(None, help="1=matriz, 2=filial"),
    mei: Optional[bool] = typer.Option(
        None, "--mei/--nao-mei", help="Filtrar MEI"
    ),
    simples: Optional[bool] = typer.Option(
        None, "--simples/--nao-simples", help="Optante Simples"
    ),
    capital_min: Optional[float] = typer.Option(None, help="Capital social mínimo"),
    capital_max: Optional[float] = typer.Option(None, help="Capital social máximo"),
    data_inicio_de: Optional[str] = typer.Option(None, help="Data início >= AAAAMMDD"),
    data_inicio_ate: Optional[str] = typer.Option(None, help="Data início <= AAAAMMDD"),
    limit: int = typer.Option(DEFAULT_QUERY_LIMIT, help="Limite de linhas"),
    export: Optional[Path] = typer.Option(None, help="Exportar para arquivo"),
    formato: str = typer.Option("csv", help="csv ou parquet (com --export)"),
) -> None:
    """Busca por filtros ricos (UF, CNAE, porte, MEI, etc.)."""
    kwargs = dict(
        uf=uf,
        cnae=cnae,
        incluir_cnae_secundario=incluir_secundario,
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
    with _con() as con:
        if export:
            path = exportar_busca(con, export, formato=formato, **kwargs)  # type: ignore[arg-type]
            typer.echo(f"Exportado: {path}")
            return
        rows = buscar_empresas(con, **kwargs)  # type: ignore[arg-type]
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2, default=str))


@app.command("socio")
def socio_cmd(
    nome: Optional[str] = typer.Option(None, help="Nome do sócio"),
    documento: Optional[str] = typer.Option(None, help="CPF/CNPJ do sócio"),
    limit: int = typer.Option(DEFAULT_QUERY_LIMIT, help="Limite"),
) -> None:
    """Busca empresas por sócio (nome e/ou documento)."""
    with _con() as con:
        try:
            rows = buscar_socios(con, nome=nome, documento=documento, limit=limit)
        except ValueError as e:
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from e
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2, default=str))


@app.command("agregados")
def agregados_cmd(
    tipo: str = typer.Argument("uf", help="uf | cnae | situacao"),
    uf: Optional[str] = typer.Option(None, help="UF (para tipo=cnae)"),
    limit: int = typer.Option(30, help="Limite"),
) -> None:
    """Agregações rápidas (UF, CNAE, situação)."""
    with _con() as con:
        if tipo == "uf":
            rows = agregados_uf(con, limit=limit)
        elif tipo == "cnae":
            rows = agregados_cnae(con, uf=uf, limit=limit)
        elif tipo == "situacao":
            rows = agregados_situacao(con)
        else:
            typer.secho("tipo deve ser uf, cnae ou situacao", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2, default=str))


@app.command("validar")
def validar_cmd() -> None:
    """Roda validação pós-carga (somente leitura dos checks)."""
    with connect(DB_PATH, read_only=False) as con:
        result = validar_base(con, persist=True)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result["ok"]:
        raise typer.Exit(code=1)


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
