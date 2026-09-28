"""
Manutenção da base: compactação e retenção (backups da base anterior e exports).

- ``compactar``: o DuckDB não devolve ao disco o espaço de tabelas apagadas ou
  reescritas (ponte CNAE, sócios, ``upgrade``…). A compactação copia tudo para
  um arquivo novo, confere as contagens e troca. Os índices são recriados só
  depois dos dados (inserir em tabela indexada estoura a memória na base real).
- ``backup_base``: na recarga, guarda a base anterior como
  ``cnpj.duckdb.bak-AAAAMM`` em vez de apagá-la.
- ``limpar_backups`` / ``limpar_exports``: mantêm só os N backups mais recentes
  e apagam exports mais velhos que X horas.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

import duckdb

from dockdb_cnpj.config import DB_PATH

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"


def _sql_path(p: Path) -> str:
    return str(p).replace("'", "''")


def _memoria_padrao() -> str:
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return "8GB"
    return f"{max(1, total // 2 // 1024**3)}GB"


def _copiar(con: duckdb.DuckDBPyConnection) -> None:
    """Copia ``origem`` → ``destino``: esquema, dados e, por último, os índices."""
    indices = con.execute(
        "SELECT schema_name, index_name, sql FROM duckdb_indexes() WHERE database_name = 'origem'"
    ).fetchall()
    con.execute("COPY FROM DATABASE origem TO destino (SCHEMA)")
    for schema, nome, _ in indices:
        con.execute(f'DROP INDEX IF EXISTS destino."{schema}"."{nome}"')
    con.execute("COPY FROM DATABASE origem TO destino (DATA)")
    for schema, _, sql in indices:
        con.execute(f'USE destino."{schema}"')
        con.execute(sql)
    con.execute("USE memory")


def _contagens(con: duckdb.DuckDBPyConnection, catalogo: str) -> dict[str, int]:
    tabelas = con.execute(
        "SELECT schema_name, table_name FROM duckdb_tables() WHERE database_name = ?",
        [catalogo],
    ).fetchall()
    out: dict[str, int] = {}
    for schema, tabela in tabelas:
        row = con.execute(f'SELECT count(*) FROM "{catalogo}"."{schema}"."{tabela}"').fetchone()
        out[f"{schema}.{tabela}"] = int(row[0]) if row else 0
    return out


def compactar(
    db_path: Path = DB_PATH, *, manter_backup: bool = False, memoria: str | None = None
) -> dict[str, Any]:
    """Reescreve a base num arquivo novo e substitui a original.

    Exige lock exclusivo (feche API/Streamlit). Precisa de espaço livre
    equivalente ao tamanho da base compactada. ``memoria`` limita a RAM do
    DuckDB (padrão: metade da RAM física); o excedente vai para disco.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Base não encontrada: {db_path}")
    tmp = db_path.with_name(db_path.name + ".compact.tmp")
    spill = db_path.with_name(db_path.name + ".compact.spill")
    for p in (tmp, Path(str(tmp) + ".wal")):
        if p.exists():
            p.unlink()

    t0 = time.time()
    with duckdb.connect(str(db_path)) as con:  # falha cedo se houver lock
        con.execute("CHECKPOINT")
    antes = db_path.stat().st_size

    con = duckdb.connect(
        ":memory:",
        config={
            "memory_limit": memoria or _memoria_padrao(),
            "temp_directory": str(spill),
            "preserve_insertion_order": False,
        },
    )
    try:
        con.execute(f"ATTACH '{_sql_path(db_path)}' AS origem (READ_ONLY)")
        con.execute(f"ATTACH '{_sql_path(tmp)}' AS destino")
        _copiar(con)
        c_origem = _contagens(con, "origem")
        c_destino = _contagens(con, "destino")
        if c_origem != c_destino:
            difs = {
                k: (c_origem.get(k), c_destino.get(k))
                for k in set(c_origem) | set(c_destino)
                if c_origem.get(k) != c_destino.get(k)
            }
            raise RuntimeError(f"Contagens divergentes após a cópia: {difs}")
        con.execute("DETACH origem")
        con.execute("DETACH destino")
    except BaseException:
        con.close()
        tmp.unlink(missing_ok=True)
        Path(str(tmp) + ".wal").unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(spill, ignore_errors=True)
    con.close()

    backup = None
    if manter_backup:
        backup = _nome_backup(db_path, time.strftime("%Y%m%d%H%M%S"))
        os.replace(db_path, backup)
    os.replace(tmp, db_path)
    depois = db_path.stat().st_size
    return {
        "db": str(db_path),
        "antes_bytes": antes,
        "depois_bytes": depois,
        "liberado_bytes": antes - depois,
        "tabelas": len(c_origem),
        "backup": str(backup) if backup else None,
        "segundos": round(time.time() - t0, 1),
    }


def _nome_backup(db_path: Path, sufixo: str) -> Path:
    alvo = db_path.with_name(f"{db_path.name}.bak-{sufixo}")
    if alvo.exists():
        alvo = db_path.with_name(f"{db_path.name}.bak-{sufixo}-{time.strftime('%Y%m%d%H%M%S')}")
    return alvo


def listar_backups(db_path: Path = DB_PATH) -> list[Path]:
    """Backups da base, do mais recente para o mais antigo."""
    db_path = Path(db_path)
    backups = [
        p
        for p in db_path.parent.glob(f"{db_path.name}.bak-*")
        if p.is_file() and not p.name.endswith(".wal")
    ]
    return sorted(backups, key=lambda p: p.stat().st_mtime, reverse=True)


def backup_base(db_path: Path = DB_PATH) -> Path | None:
    """Move a base atual para ``{db}.bak-{ano_mes}`` (ano_mes lido de ``_referencia``)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    ano_mes = None
    try:
        with duckdb.connect(str(db_path), read_only=True) as con:
            row = con.execute(
                "SELECT valor FROM _referencia WHERE referencia = 'ano_mes'"
            ).fetchone()
            ano_mes = row[0] if row else None
    except duckdb.Error:
        pass
    alvo = _nome_backup(db_path, ano_mes or time.strftime("%Y%m%d%H%M%S"))
    os.replace(db_path, alvo)
    wal = Path(str(db_path) + ".wal")
    if wal.exists():
        os.replace(wal, Path(str(alvo) + ".wal"))
    return alvo


def limpar_backups(
    db_path: Path = DB_PATH, *, manter: int = 0, dry_run: bool = False
) -> list[Path]:
    """Apaga backups além dos ``manter`` mais recentes. Retorna os removidos."""
    removidos = listar_backups(db_path)[max(manter, 0):]
    for p in removidos:
        if not dry_run:
            p.unlink(missing_ok=True)
            Path(str(p) + ".wal").unlink(missing_ok=True)
    return removidos


def limpar_exports(
    exports_dir: Path, *, max_idade_h: float, dry_run: bool = False
) -> list[Path]:
    """Apaga arquivos de ``exports_dir`` mais velhos que ``max_idade_h`` horas."""
    if not exports_dir.exists() or max_idade_h <= 0:
        return []
    limite = time.time() - max_idade_h * 3600
    removidos = [p for p in exports_dir.iterdir() if p.is_file() and p.stat().st_mtime < limite]
    for p in removidos:
        if not dry_run:
            p.unlink(missing_ok=True)
    return removidos
