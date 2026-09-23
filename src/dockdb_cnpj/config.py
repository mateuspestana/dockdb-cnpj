"""
Configuração de paths e ambiente.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import os
from pathlib import Path

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

# Raiz do repositório (…/DockDB-CNPJ)
ROOT = Path(__file__).resolve().parents[2]

ZIP_DIR = Path(os.environ.get("CNPJ_ZIP_DIR", ROOT / "dados-publicos-zip"))
CSV_DIR = Path(os.environ.get("CNPJ_CSV_DIR", ROOT / "dados-publicos"))
DATA_DIR = Path(os.environ.get("CNPJ_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.environ.get("CNPJ_DB_PATH", DATA_DIR / "cnpj.duckdb"))
LAST_SYNC_PATH = Path(os.environ.get("CNPJ_LAST_SYNC", DATA_DIR / "last_sync.json"))

# WebDAV share da Receita (pode mudar; ver README)
SHARE_TOKEN = os.environ.get("CNPJ_SHARE_TOKEN", "YggdBLfdninEJX9")
WEBDAV_BASE = os.environ.get(
    "CNPJ_WEBDAV_BASE",
    "https://arquivos.receitafederal.gov.br/public.php/webdav",
)

DEFAULT_QUERY_LIMIT = int(os.environ.get("CNPJ_QUERY_LIMIT", "1000"))
MAX_QUERY_LIMIT = int(os.environ.get("CNPJ_MAX_QUERY_LIMIT", "10000"))


def ensure_dirs() -> None:
    ZIP_DIR.mkdir(parents=True, exist_ok=True)
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
