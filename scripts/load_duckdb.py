#!/usr/bin/env python3
"""
Carrega os ZIPs/CSVs de CNPJ em um arquivo DuckDB.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dockdb_cnpj.config import DB_PATH  # noqa: E402
from dockdb_cnpj.load import load_duckdb  # noqa: E402

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga CNPJ → DuckDB.")
    parser.add_argument(
        "--no-extract",
        action="store_true",
        help="Não extrair ZIPs (usar CSVs já em dados-publicos/).",
    )
    parser.add_argument(
        "--remove-csv",
        action="store_true",
        help="Apagar CSVs após a carga (libera disco).",
    )
    parser.add_argument(
        "--cleanup-raw",
        action="store_true",
        help="Após a carga, apagar ZIPs e CSVs (só sobra o DuckDB).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help=f"Caminho do .duckdb (default: {DB_PATH})",
    )
    args = parser.parse_args()

    load_duckdb(
        db_path=args.db,
        extract=not args.no_extract,
        remove_csv_after=args.remove_csv or args.cleanup_raw,
    )
    if args.cleanup_raw:
        from dockdb_cnpj.cleanup import cleanup_raw

        cleanup_raw(db_path=args.db, remove_zip=True, remove_csv=True, require_db=True)
    print(f"Pronto: {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
