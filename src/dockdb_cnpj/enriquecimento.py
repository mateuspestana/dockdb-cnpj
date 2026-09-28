"""
Busca por lista: recebe CNPJs (arquivo ou lista) e devolve os dados cadastrais.

- CNPJ de 14 posições → o próprio estabelecimento;
- CNPJ básico (8) → a matriz;
- zeros à esquerda perdidos (coluna numérica no Excel) são recuperados;
- entradas inválidas voltam com ``erro`` preenchido, na ordem original.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb

from dockdb_cnpj.cnpj import BASICO_RE, CNPJ_RE, completar_zeros, dv_valido
from dockdb_cnpj.db import fetch_dicts
from dockdb_cnpj.queries import SITUACAO_LABEL, colunas_extras

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"


def _chave(entrada: str) -> tuple[str | None, str | None]:
    """(chave normalizada, erro)."""
    c = completar_zeros(entrada)
    if CNPJ_RE.fullmatch(c) or BASICO_RE.fullmatch(c):
        return c, None
    return None, "formato inválido (esperado 8 ou 14 posições)"


def enriquecer(con: duckdb.DuckDBPyConnection, cnpjs: Iterable[Any]) -> list[dict]:
    """Uma linha por entrada, na mesma ordem, com ``encontrado`` e os dados do CNPJ."""
    entradas = ["" if v is None else str(v).strip() for v in cnpjs]
    if not entradas:
        return []
    chaves: list[str | None] = []
    erros: list[str | None] = []
    for e in entradas:
        k, err = _chave(e)
        chaves.append(k)
        erros.append(err)

    extras_select, extras_join = colunas_extras(con)
    sql = f"""
        WITH ent AS (
            SELECT
                unnest(?::INTEGER[]) AS pos,
                unnest(?::VARCHAR[]) AS entrada,
                unnest(?::VARCHAR[]) AS chave
        ),
        matriz AS MATERIALIZED (
            SELECT cnpj_basico, cnpj FROM cnpj_base2matriz
            WHERE cnpj_basico IN (SELECT chave FROM ent WHERE length(chave) = 8)
        ),
        alvo AS MATERIALIZED (
            SELECT
                ent.*,
                CASE WHEN length(ent.chave) = 14 THEN ent.chave ELSE b.cnpj END AS cnpj_alvo
            FROM ent
            LEFT JOIN matriz b ON length(ent.chave) = 8 AND b.cnpj_basico = ent.chave
        ),
        est AS MATERIALIZED (
            SELECT * FROM estabelecimento
            WHERE cnpj IN (SELECT cnpj_alvo FROM alvo WHERE cnpj_alvo IS NOT NULL)
        ),
        e AS MATERIALIZED (
            SELECT * FROM empresas WHERE cnpj_basico IN (SELECT cnpj_basico FROM est)
        ),
        si AS MATERIALIZED (
            SELECT * FROM simples WHERE cnpj_basico IN (SELECT cnpj_basico FROM est)
        )
        SELECT
            alvo.pos,
            alvo.entrada,
            alvo.chave AS cnpj_normalizado,
            est.cnpj IS NOT NULL AS encontrado,
            est.cnpj,
            e.razao_social,
            est.nome_fantasia,
            est.matriz_filial,
            est.situacao_cadastral,
            est.data_situacao_cadastral,
            est.data_inicio_atividades,
            e.natureza_juridica,
            nj.descricao AS natureza_juridica_desc,
            e.porte_empresa,
            e.capital_social,
            est.cnae_fiscal,
            c.descricao AS cnae_descricao,
            est.cnae_fiscal_secundaria,
            est.uf,
            est.municipio,
            m.descricao AS municipio_nome,
            {extras_select}
            est.cep,
            est.tipo_logradouro,
            est.logradouro,
            est.numero,
            est.complemento,
            est.bairro,
            si.opcao_simples,
            si.opcao_mei
        FROM alvo
        LEFT JOIN est ON est.cnpj = alvo.cnpj_alvo
        LEFT JOIN e ON e.cnpj_basico = est.cnpj_basico
        LEFT JOIN natureza_juridica nj ON nj.codigo = e.natureza_juridica
        LEFT JOIN cnae c ON c.codigo = est.cnae_fiscal
        LEFT JOIN municipio m ON m.codigo = est.municipio
        {extras_join}
        LEFT JOIN si ON si.cnpj_basico = est.cnpj_basico
        ORDER BY alvo.pos
    """
    rows = fetch_dicts(con, sql, [list(range(len(entradas))), entradas, chaves])
    for r in rows:
        pos = r.pop("pos")
        chave = r["cnpj_normalizado"]
        r["erro"] = erros[pos]
        r["dv_valido"] = dv_valido(chave) if chave and len(chave) == 14 else None
        sit = str(r.get("situacao_cadastral") or "")
        r["situacao_cadastral_desc"] = SITUACAO_LABEL.get(sit, sit or None)
    return rows


def _parece_cnpj(valor: Any) -> bool:
    return _chave("" if valor is None else str(valor))[0] is not None


def _separador(path: Path) -> str:
    """Detecta ; , TAB ou | — sem isso o sniffer do pandas pode escolher um dígito."""
    amostra = path.read_text(encoding="utf-8", errors="replace")[:8192]
    try:
        return csv.Sniffer().sniff(amostra, delimiters=";,\t|").delimiter
    except csv.Error:
        return "\t"  # coluna única


def ler_lista(path: Path | str, *, coluna: str | None = None) -> list[str]:
    """Lê CNPJs de .csv/.txt (separador detectado) ou .parquet.

    Coluna: a informada, senão a primeira cujo nome contém "cnpj", senão a primeira.
    Arquivo sem cabeçalho é detectado quando a 1ª linha já parece um CNPJ.
    """
    import pandas as pd

    p = Path(path)
    if p.suffix.lower() == ".parquet":
        df = pd.read_parquet(p).astype("string")
    else:
        df = pd.read_csv(p, dtype=str, sep=_separador(p), header=None, keep_default_na=False)
        if len(df) and not any(_parece_cnpj(v) for v in df.iloc[0].tolist()):
            df.columns = [str(c) for c in df.iloc[0].tolist()]
            df = df.iloc[1:]
        else:
            df.columns = [f"col{i}" for i in range(df.shape[1])]
    if df.empty:
        return []
    if coluna:
        if coluna not in df.columns:
            raise ValueError(f"Coluna '{coluna}' não encontrada. Disponíveis: {list(df.columns)}")
        col = coluna
    else:
        col = next((c for c in df.columns if "cnpj" in str(c).lower()), df.columns[0])
    return [str(v) for v in df[col].fillna("").tolist()]


def salvar(rows: list[dict], path: Path | str) -> Path:
    """Grava CSV ou Parquet conforme a extensão."""
    import pandas as pd

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    if dest.suffix.lower() == ".parquet":
        df.to_parquet(dest, index=False)
    else:
        df.to_csv(dest, index=False)
    return dest
