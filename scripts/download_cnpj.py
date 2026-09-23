#!/usr/bin/env python3
"""
Baixa os arquivos ZIP de CNPJ da Receita Federal.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dockdb_cnpj.download import (  # noqa: E402
    consulta_base_webdap,
    download_all,
    save_sync_meta,
)

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download dos dados públicos de CNPJ (Receita Federal)."
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Não pedir confirmação."
    )
    parser.add_argument(
        "--force", action="store_true", help="Rebaixar mesmo se o arquivo existir."
    )
    args = parser.parse_args()

    listing = consulta_base_webdap()
    print(f"Competência: {listing.ano_mes}")
    print(f"Página: {listing.url_pagina}")
    print(f"Arquivos ({len(listing.arquivos)}):")
    for a in listing.arquivos:
        print(f"  - {a}")

    if not args.yes:
        resp = input("Baixar estes arquivos? [y/N] ").strip().lower()
        if resp not in ("y", "s", "yes", "sim"):
            print("Cancelado.")
            return 1

    download_all(listing, force=args.force)
    save_sync_meta(listing, {"step": "download"})
    print("Concluído. Próximo passo: python scripts/load_duckdb.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
