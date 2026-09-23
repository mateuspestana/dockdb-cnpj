"""
Remove dados brutos (ZIPs e CSVs), mantendo apenas o DuckDB.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

from pathlib import Path

from dockdb_cnpj.config import CSV_DIR, DB_PATH, ZIP_DIR, ensure_dirs

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

KEEP_NAMES = {".gitkeep", ".gitignore"}


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def _fmt(n: int) -> str:
    for unit, div in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


def _clear_dir(path: Path, *, dry_run: bool) -> tuple[int, int]:
    """Apaga arquivos em path (exceto keep). Retorna (n_arquivos, bytes)."""
    if not path.exists():
        return 0, 0
    removed = 0
    bytes_ = 0
    for p in sorted(path.rglob("*"), reverse=True):
        if p.name in KEEP_NAMES:
            continue
        if p.is_file():
            size = p.stat().st_size
            print(f"  {'[dry] ' if dry_run else ''}rm {p.relative_to(path.parent)}")
            if not dry_run:
                p.unlink()
            removed += 1
            bytes_ += size
        elif p.is_dir() and not dry_run:
            try:
                p.rmdir()
            except OSError:
                pass
    return removed, bytes_


def cleanup_raw(
    *,
    zip_dir: Path = ZIP_DIR,
    csv_dir: Path = CSV_DIR,
    db_path: Path = DB_PATH,
    remove_zip: bool = True,
    remove_csv: bool = True,
    dry_run: bool = False,
    require_db: bool = True,
) -> dict:
    """
    Remove ZIPs e/ou CSVs brutos, deixando só o .duckdb.

    Por padrão exige que db_path exista (evita apagar fonte sem base pronta).
    """
    ensure_dirs()
    if require_db and not db_path.exists():
        raise FileNotFoundError(
            f"Base DuckDB não encontrada em {db_path}. "
            "Rode a carga antes de limpar os dados brutos "
            "(ou use --force para limpar mesmo assim)."
        )

    before_zip = _dir_size(zip_dir)
    before_csv = _dir_size(csv_dir)
    db_size = db_path.stat().st_size if db_path.exists() else 0

    print(f"DuckDB: {db_path} ({_fmt(db_size)})")
    print(f"ZIPs:   {zip_dir} ({_fmt(before_zip)})")
    print(f"CSVs:   {csv_dir} ({_fmt(before_csv)})")

    n_zip = n_csv = 0
    b_zip = b_csv = 0
    if remove_zip:
        print("Limpando ZIPs …")
        n_zip, b_zip = _clear_dir(zip_dir, dry_run=dry_run)
    if remove_csv:
        print("Limpando CSVs …")
        n_csv, b_csv = _clear_dir(csv_dir, dry_run=dry_run)

    freed = (b_zip if remove_zip else 0) + (b_csv if remove_csv else 0)
    print(
        f"{'Liberaria' if dry_run else 'Liberado'}: {_fmt(freed)} "
        f"({n_zip} zip(s)/arquivo(s), {n_csv} csv(s)/arquivo(s))"
    )
    return {
        "removed_files": n_zip + n_csv,
        "bytes_freed": freed,
        "db_path": str(db_path),
        "db_size": db_size,
        "dry_run": dry_run,
    }
