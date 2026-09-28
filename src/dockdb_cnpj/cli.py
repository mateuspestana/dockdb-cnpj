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
from dockdb_cnpj.cnpj import calcular_dv, dv_valido, formatar, limpar
from dockdb_cnpj.analytics import agregados_municipio, coortes
from dockdb_cnpj.config import DB_PATH, DEFAULT_QUERY_LIMIT, MAX_QUERY_LIMIT
from dockdb_cnpj.db import connect
from dockdb_cnpj.enriquecimento import enriquecer, ler_lista, salvar
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
    cnpj: str = typer.Argument(..., help="CNPJ com 8 ou 14 posições (aceita alfanumérico)."),
) -> None:
    """Consulta empresa / estabelecimentos / sócios."""
    with _con() as con:
        try:
            data = consulta_cnpj(con, cnpj)
        except ValueError as e:
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from e
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


@app.command("dv")
def dv_cmd(
    cnpj: str = typer.Argument(..., help="CNPJ (14 posições) ou base (12) para calcular o DV."),
) -> None:
    """Valida o dígito verificador (CNPJ numérico ou alfanumérico). Não usa a base."""
    c = limpar(cnpj)
    out: dict[str, str | bool]
    try:
        if len(c) == 12:
            dv = calcular_dv(c)
            out = {"base": c, "dv": dv, "cnpj": c + dv, "cnpj_formatado": formatar(c + dv)}
        elif len(c) == 14:
            esperado = calcular_dv(c[:12])
            out = {
                "cnpj": c,
                "cnpj_formatado": formatar(c),
                "dv_valido": dv_valido(c),
                "dv_esperado": esperado,
                "alfanumerico": not c.isdigit(),
            }
        else:
            raise ValueError("Informe 12 (base) ou 14 posições.")
    except ValueError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e
    typer.echo(json.dumps(out, ensure_ascii=False, indent=2))
    if len(c) == 14 and not out["dv_valido"]:
        raise typer.Exit(code=1)


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
    municipio_ibge: Optional[str] = typer.Option(
        None, help="Código IBGE do município (7 dígitos)"
    ),
    cnae_secao: Optional[str] = typer.Option(
        None, help="Seção CNAE (letra A–U; CNAE principal)"
    ),
    cnae_divisao: Optional[str] = typer.Option(
        None, help="Divisão CNAE (2 dígitos; CNAE principal)"
    ),
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
    with _con() as con:
        try:
            if export:
                path = exportar_busca(con, export, formato=formato, **kwargs)  # type: ignore[arg-type]
                typer.echo(f"Exportado: {path}")
                return
            rows = buscar_empresas(con, **kwargs)  # type: ignore[arg-type]
        except ValueError as e:
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from e
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
    tipo: str = typer.Argument("uf", help="uf | cnae | situacao | municipio"),
    uf: Optional[str] = typer.Option(None, help="UF (para tipo=cnae ou municipio)"),
    nivel: str = typer.Option(
        "subclasse", help="Para tipo=cnae: subclasse | classe | grupo | divisao | secao"
    ),
    limit: int = typer.Option(30, help="Limite"),
) -> None:
    """Agregações rápidas (UF, CNAE em qualquer nível, situação, município)."""
    with _con() as con:
        try:
            if tipo == "uf":
                rows = agregados_uf(con, limit=limit)
            elif tipo == "cnae":
                rows = agregados_cnae(con, uf=uf, nivel=nivel, limit=limit)
            elif tipo == "situacao":
                rows = agregados_situacao(con)
            elif tipo == "municipio":
                rows = agregados_municipio(con, uf=uf, limit=limit)
            else:
                raise ValueError("tipo deve ser uf, cnae, situacao ou municipio")
        except ValueError as e:
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from e
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2, default=str))


@app.command("coortes")
def coortes_cmd(
    freq: str = typer.Option("ano", help="ano | mes"),
    desde: Optional[str] = typer.Option(None, help="Período inicial (AAAA ou AAAAMM)"),
    ate: Optional[str] = typer.Option(None, help="Período final (AAAA ou AAAAMM)"),
    uf: Optional[str] = typer.Option(None, help="UF"),
    municipio: Optional[str] = typer.Option(None, help="Código RF do município"),
    municipio_ibge: Optional[str] = typer.Option(None, help="Código IBGE do município"),
    cnae: Optional[str] = typer.Option(None, help="CNAE principal (subclasse)"),
    cnae_secao: Optional[str] = typer.Option(None, help="Seção CNAE (letra)"),
    cnae_divisao: Optional[str] = typer.Option(None, help="Divisão CNAE (2 dígitos)"),
    matriz_filial: Optional[str] = typer.Option(None, help="1=matriz, 2=filial"),
    export: Optional[Path] = typer.Option(None, help="Gravar em .csv ou .parquet"),
) -> None:
    """Aberturas, baixas, saldo e sobrevivência por ano/mês (retrato do dump atual)."""
    with _con() as con:
        try:
            rows = coortes(
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
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from e
    if export:
        typer.echo(f"Exportado: {salvar(rows, export)}")
        return
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2, default=str))


@app.command("enriquecer")
def enriquecer_cmd(
    arquivo: Path = typer.Argument(..., help="Lista de CNPJs (.csv, .txt ou .parquet)"),
    coluna: Optional[str] = typer.Option(None, help="Coluna com o CNPJ (padrão: detecta)"),
    saida: Optional[Path] = typer.Option(None, help="Gravar em .csv ou .parquet"),
) -> None:
    """Busca por lista: devolve os dados cadastrais de cada CNPJ, na ordem do arquivo."""
    try:
        cnpjs = ler_lista(arquivo, coluna=coluna)
    except (ValueError, OSError) as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e
    with _con() as con:
        rows = enriquecer(con, cnpjs)
    achados = sum(1 for r in rows if r["encontrado"])
    typer.secho(f"{achados}/{len(rows)} encontrados", err=True)
    if saida:
        typer.echo(f"Exportado: {salvar(rows, saida)}")
        return
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2, default=str))


@app.command("geocodificar")
def geocodificar_cmd(
    uf: Optional[str] = typer.Option(None, help="UF"),
    municipio_ibge: Optional[str] = typer.Option(None, help="Código IBGE do município"),
    cnae: Optional[str] = typer.Option(None, help="CNAE (principal/secundário)"),
    situacao: Optional[str] = typer.Option("02", help="Situação cadastral (padrão: ativas)"),
    arquivo: Optional[Path] = typer.Option(
        None, help="Em vez de filtros, geocodificar os CEPs de uma lista de CNPJs"
    ),
    limite: int = typer.Option(100, help="Máximo de CEPs novos a consultar"),
    pausa: float = typer.Option(0.3, help="Segundos entre chamadas à BrasilAPI"),
) -> None:
    """Geocodifica CEPs via BrasilAPI e guarda em `cep_geo` (exige lock de escrita)."""
    from dockdb_cnpj.geo import geocodificar_ceps

    try:
        with connect(DB_PATH, read_only=False) as con:
            if arquivo:
                ceps = [r["cep"] or "" for r in enriquecer(con, ler_lista(arquivo))]
            else:
                rows = buscar_empresas(
                    con,
                    uf=uf,
                    municipio_ibge=municipio_ibge,
                    cnae=cnae,
                    situacao=situacao or None,
                    limit=MAX_QUERY_LIMIT,
                )
                ceps = [r["cep"] or "" for r in rows]

            def progresso(i: int, total: int, cep: str, res: dict) -> None:
                typer.echo(f"  [{i}/{total}] {cep}: {res.get('status')}", err=True)

            stats = geocodificar_ceps(
                con, ceps, pausa=pausa, limite=limite, on_progress=progresso
            )
    except Exception as e:
        msg = str(e).lower()
        if "lock" in msg or "conflict" in msg:
            typer.secho(
                "Não foi possível abrir a base em modo escrita (lock). "
                "Feche Streamlit/API e tente de novo.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=2) from e
        if isinstance(e, ValueError):
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from e
        raise
    typer.echo(json.dumps(stats, ensure_ascii=False, indent=2))


@app.command("validar")
def validar_cmd() -> None:
    """Roda validação pós-carga (persiste em `_validacao` se possível)."""
    result = None
    try:
        with connect(DB_PATH, read_only=False) as con:
            result = validar_base(con, persist=True)
    except Exception as e:
        msg = str(e).lower()
        if "lock" in msg or "conflict" in msg or "read-only" in msg:
            typer.secho(
                f"Aviso: não foi possível gravar (_validacao): {e}\n"
                "Rodando validação em modo somente leitura…",
                fg=typer.colors.YELLOW,
                err=True,
            )
            with connect(DB_PATH, read_only=True) as con:
                result = validar_base(con, persist=False)
        else:
            raise
    assert result is not None
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command("upgrade")
def upgrade_cmd(
    cnae_bridge: bool = typer.Option(True, "--cnae-bridge/--no-cnae-bridge"),
    views: bool = typer.Option(True, "--views/--no-views"),
    fts: bool = typer.Option(True, "--fts/--no-fts"),
    referencias: bool = typer.Option(
        True, "--referencias/--no-referencias", help="Tabelas auxiliares (IBGE etc.)"
    ),
    validar: bool = typer.Option(True, "--validar/--no-validar"),
) -> None:
    """Aplica artefatos v0.5+ numa base já carregada (sem reimportar CSVs)."""
    from dockdb_cnpj.load import upgrade_base

    try:
        with connect(DB_PATH, read_only=False) as con:
            result = upgrade_base(
                con,
                build_cnae_bridge=cnae_bridge,
                build_mvs=views,
                build_fts=fts,
                build_refs=referencias,
                run_validate=validar,
            )
    except Exception as e:
        msg = str(e).lower()
        if "lock" in msg or "conflict" in msg:
            typer.secho(
                "Não foi possível abrir a base em modo escrita (lock).\n"
                "Feche Streamlit/API/outros processos que usem o DuckDB e tente de novo.\n"
                f"Detalhe: {e}",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=2) from e
        raise
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


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
