#!/usr/bin/env python3
"""
Remove dados brutos (ZIPs + CSVs) e mantém só o DuckDB.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dockdb_cnpj.cleanup import cleanup_raw  # noqa: E402
from dockdb_cnpj.config import DB_PATH  # noqa: E402

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Apaga ZIPs e CSVs brutos da Receita, deixando apenas data/cnpj.duckdb."
        )
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Não pedir confirmação."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só mostra o que seria apagado.",
    )
    parser.add_argument(
        "--keep-zip",
        action="store_true",
        help="Não apagar dados-publicos-zip/.",
    )
    parser.add_argument(
        "--keep-csv",
        action="store_true",
        help="Não apagar dados-publicos/.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Limpar mesmo se o .duckdb não existir.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help=f"Caminho do .duckdb esperado (default: {DB_PATH})",
    )
    args = parser.parse_args()

    if args.keep_zip and args.keep_csv:
        print("Nada a fazer (--keep-zip e --keep-csv).")
        return 0

    if not args.yes and not args.dry_run:
        resp = input(
            "Apagar dados brutos (ZIP/CSV) e manter só o DuckDB? [y/N] "
        ).strip().lower()
        if resp not in ("y", "s", "yes", "sim"):
            print("Cancelado.")
            return 1

    try:
        cleanup_raw(
            db_path=args.db,
            remove_zip=not args.keep_zip,
            remove_csv=not args.keep_csv,
            dry_run=args.dry_run,
            require_db=not args.force,
        )
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
