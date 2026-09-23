#!/usr/bin/env python3
"""
Atualiza a base: baixa só ZIPs novos/alterados e recarrega o DuckDB.

A Receita publica dump mensal completo; o “incremental” aqui é download
inteligente (pula arquivos íntegros) + rebuild da base.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dockdb_cnpj.config import DB_PATH, ZIP_DIR  # noqa: E402
from dockdb_cnpj.download import (  # noqa: E402
    consulta_base_webdap,
    download_all,
    load_sync_meta,
    save_sync_meta,
)
from dockdb_cnpj.load import load_duckdb  # noqa: E402

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync incremental CNPJ → DuckDB (rodado pelo usuário)."
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Não pedir confirmação."
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Só baixa; não recarrega o DuckDB.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Força redownload de todos os ZIPs.",
    )
    parser.add_argument(
        "--remove-csv",
        action="store_true",
        help="Apagar CSVs após a carga.",
    )
    args = parser.parse_args()

    prev = load_sync_meta()
    listing = consulta_base_webdap()
    print(f"Remoto: {listing.ano_mes} ({len(listing.arquivos)} arquivos)")
    if prev:
        print(f"Última sync local: {prev.get('ano_mes')} em {prev.get('synced_at')}")

    if not args.yes:
        resp = input("Baixar atualizações e recarregar a base? [y/N] ").strip().lower()
        if resp not in ("y", "s", "yes", "sim"):
            print("Cancelado.")
            return 1

    # Remove ZIPs que não estão mais no mês remoto (evita misturar competências)
    remote_names = set(listing.arquivos)
    for local in ZIP_DIR.glob("*.zip"):
        if local.name not in remote_names:
            print(f"  [rm] ZIP antigo: {local.name}")
            local.unlink()

    download_all(listing, only_missing=True, force=args.force_download)
    save_sync_meta(listing, {"step": "sync-download"})

    if args.download_only:
        print("Download ok (--download-only).")
        return 0

    load_duckdb(extract=True, remove_csv_after=args.remove_csv, db_path=DB_PATH)
    save_sync_meta(listing, {"step": "sync-complete", "db": str(DB_PATH)})
    print("Sync concluído.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
