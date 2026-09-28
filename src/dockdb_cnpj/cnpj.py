"""
CNPJ numérico e alfanumérico (IN RFB nº 2.229/2024, vigente desde jul/2026).

As 12 primeiras posições aceitam [0-9A-Z]; os 2 dígitos verificadores
continuam numéricos. O DV usa módulo 11 com o valor de cada caractere
igual a ``ord(c) - 48`` (``0``–``9`` → 0–9, ``A`` → 17, …, ``Z`` → 42).

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import re

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

PESOS_DV1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
PESOS_DV2 = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)

CNPJ_RE = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")
BASICO_RE = re.compile(r"^[0-9A-Z]{8}$")
_NAO_ALNUM = re.compile(r"[^0-9A-Z]")


def limpar(value: str | None) -> str:
    """Remove pontuação/espaços e passa para maiúsculas (mantém letras)."""
    return _NAO_ALNUM.sub("", (value or "").upper())


def _dv(chars: str, pesos: tuple[int, ...]) -> int:
    total = sum((ord(c) - 48) * p for c, p in zip(chars, pesos, strict=True))
    resto = total % 11
    return 0 if resto < 2 else 11 - resto


def calcular_dv(base12: str) -> str:
    """Calcula os 2 DVs a partir das 12 primeiras posições."""
    base = limpar(base12)
    if not re.fullmatch(r"[0-9A-Z]{12}", base):
        raise ValueError("A base do CNPJ deve ter 12 caracteres [0-9A-Z].")
    d1 = _dv(base, PESOS_DV1)
    d2 = _dv(base + str(d1), PESOS_DV2)
    return f"{d1}{d2}"


def dv_valido(cnpj: str) -> bool:
    """True se o CNPJ de 14 posições tem formato e DV corretos."""
    c = limpar(cnpj)
    if not CNPJ_RE.fullmatch(c):
        return False
    return calcular_dv(c[:12]) == c[12:]


def normalize_cnpj(value: str | None) -> str:
    """Normaliza para 8 (básico) ou 14 posições alfanuméricas.

    Não valida o DV — um CNPJ com DV errado ainda pode ser consultado
    (o resultado simplesmente vem vazio). Use :func:`dv_valido` para isso.
    """
    c = limpar(value)
    if BASICO_RE.fullmatch(c) or CNPJ_RE.fullmatch(c):
        return c
    raise ValueError(
        "CNPJ deve ter 8 (básico) ou 14 posições; as 12 primeiras aceitam "
        "letras e números, os 2 últimos (DV) são numéricos."
    )


def formatar(cnpj: str) -> str:
    """Formata como ``XX.XXX.XXX/XXXX-XX`` (ou ``XX.XXX.XXX`` para o básico)."""
    c = limpar(cnpj)
    if len(c) == 8:
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}"
    if len(c) == 14:
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"
    raise ValueError("CNPJ deve ter 8 ou 14 posições.")


def completar_zeros(value: str | None) -> str:
    """Recupera zeros à esquerda perdidos (ex.: coluna numérica no Excel).

    Só se aplica a entradas puramente numéricas: 9–13 dígitos viram 14,
    1–7 dígitos viram 8. Entradas alfanuméricas voltam só limpas.
    """
    c = limpar(value)
    if c.isdigit():
        if 8 < len(c) < 14:
            return c.zfill(14)
        if len(c) < 8:
            return c.zfill(8)
    return c


def sql_dv_expr(col: str) -> str:
    """Expressão SQL (DuckDB) que retorna os 2 DVs esperados para ``col``.

    ``col`` deve ter 14 posições; só as 12 primeiras são usadas.
    """

    def soma(n: int, pesos: tuple[int, ...], extra: str | None = None) -> str:
        termos = [
            f"(ascii(substr({col}, {i + 1}, 1)) - 48) * {p}"
            for i, p in enumerate(pesos[:n])
        ]
        if extra is not None:
            termos.append(f"({extra}) * {pesos[n]}")
        return " + ".join(termos)

    def dv(total: str) -> str:
        return f"(CASE WHEN ({total}) % 11 < 2 THEN 0 ELSE 11 - ({total}) % 11 END)"

    d1 = dv(soma(12, PESOS_DV1))
    d2 = dv(soma(12, PESOS_DV2, extra=d1))
    return f"(CAST({d1} AS VARCHAR) || CAST({d2} AS VARCHAR))"
