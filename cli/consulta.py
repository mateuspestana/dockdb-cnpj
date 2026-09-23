#!/usr/bin/env python3
"""
Wrapper CLI — DockDB-CNPJ.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dockdb_cnpj.cli import app  # noqa: E402

if __name__ == "__main__":
    app()
