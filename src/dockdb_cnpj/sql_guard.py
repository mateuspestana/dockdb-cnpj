"""
Validação de SQL livre (apenas SELECT / WITH).

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import re

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|COPY|EXPORT|IMPORT|"
    r"PRAGMA|CALL|EXECUTE|INSTALL|LOAD|SET|RESET|VACUUM|CHECKPOINT|"
    r"TRUNCATE|REPLACE|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

_MULTI_STATEMENT = re.compile(r";\s*\S")


class UnsafeSQLError(ValueError):
    """SQL não permitido para execução via API/CLI de consulta."""


def assert_safe_select(sql: str) -> str:
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeSQLError("SQL vazio.")
    if _MULTI_STATEMENT.search(sql.strip()):
        raise UnsafeSQLError("Apenas uma instrução SQL é permitida.")
    upper = cleaned.lstrip("(").lstrip().upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        raise UnsafeSQLError("Apenas consultas SELECT ou WITH são permitidas.")
    if _FORBIDDEN.search(cleaned):
        raise UnsafeSQLError("A consulta contém palavras-chave não permitidas.")
    return cleaned
