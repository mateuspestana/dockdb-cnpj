"""
Geocodificação por CEP (opcional), com cache na tabela ``cep_geo``.

Sem geocodificar, busca e consulta já devolvem o centroide do município
(``geo_precisao = 'municipio'``). CEPs geocodificados passam a ter prioridade
(``geo_precisao = 'cep'``). Fonte: BrasilAPI (``/api/cep/v2``), consultada
só para CEPs que ainda não estão no cache — respeite o serviço (``pausa``).

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any

import duckdb
import requests

from dockdb_cnpj.db import fetch_dicts
from dockdb_cnpj.queries import normalize_digits, table_exists

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

BRASILAPI_URL = "https://brasilapi.com.br/api/cep/v2/{cep}"
USER_AGENT = "DockDB-CNPJ (+https://github.com/mateuspestana/dockdb-cnpj)"

Resultado = dict[str, Any]
Fetcher = Callable[[str], Resultado]


def ensure_cep_geo(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS cep_geo (
            cep VARCHAR PRIMARY KEY,
            status VARCHAR,          -- ok | sem_coordenada | nao_encontrado | erro
            latitude DOUBLE,
            longitude DOUBLE,
            municipio_ibge VARCHAR,
            fonte VARCHAR,
            atualizado_em TIMESTAMP
        )
        """
    )


def fetch_brasilapi(cep: str, *, timeout: float = 15.0) -> Resultado:
    """Consulta um CEP na BrasilAPI e devolve status + coordenadas."""
    try:
        r = requests.get(
            BRASILAPI_URL.format(cep=cep), headers={"User-Agent": USER_AGENT}, timeout=timeout
        )
    except requests.RequestException as e:
        return {"status": "erro", "detalhe": str(e)}
    if r.status_code == 404:
        return {"status": "nao_encontrado"}
    if r.status_code >= 400:
        return {"status": "erro", "detalhe": f"HTTP {r.status_code}"}
    body = r.json()
    coords = ((body.get("location") or {}).get("coordinates")) or {}
    ibge = (body.get("ibge") or {}).get("city")
    try:
        lat = float(coords["latitude"])
        lon = float(coords["longitude"])
    except (KeyError, TypeError, ValueError):
        return {"status": "sem_coordenada", "municipio_ibge": ibge}
    return {"status": "ok", "latitude": lat, "longitude": lon, "municipio_ibge": ibge}


def ceps_pendentes(con: duckdb.DuckDBPyConnection, ceps: Iterable[str]) -> list[str]:
    """CEPs válidos (8 dígitos), sem repetição, que ainda não estão no cache."""
    vistos: dict[str, None] = {}
    for c in ceps:
        d = normalize_digits(c)
        if len(d) == 8 and d != "00000000":
            vistos.setdefault(d, None)
    if not vistos:
        return []
    if not table_exists(con, "cep_geo"):
        return list(vistos)
    em_cache = {
        r["cep"]
        for r in fetch_dicts(
            con,
            "SELECT cep FROM cep_geo WHERE cep IN (SELECT unnest(?::VARCHAR[])) "
            "AND status IN ('ok', 'sem_coordenada', 'nao_encontrado')",
            [list(vistos)],
        )
    }
    return [c for c in vistos if c not in em_cache]


def geocodificar_ceps(
    con: duckdb.DuckDBPyConnection,
    ceps: Iterable[str],
    *,
    fetcher: Fetcher | None = None,
    pausa: float = 0.3,
    limite: int | None = None,
    on_progress: Callable[[int, int, str, Resultado], None] | None = None,
) -> dict[str, int]:
    """Geocodifica os CEPs pendentes e grava em ``cep_geo`` (conexão de escrita)."""
    fetch = fetcher or fetch_brasilapi
    ensure_cep_geo(con)
    pendentes = ceps_pendentes(con, ceps)
    if limite is not None:
        pendentes = pendentes[:limite]
    stats = {"pendentes": len(pendentes), "ok": 0, "sem_coordenada": 0, "nao_encontrado": 0, "erro": 0}
    for i, cep in enumerate(pendentes, start=1):
        res = fetch(cep)
        status = res.get("status", "erro")
        stats[status] = stats.get(status, 0) + 1
        con.execute(
            "INSERT OR REPLACE INTO cep_geo VALUES (?, ?, ?, ?, ?, 'brasilapi', now())",
            [cep, status, res.get("latitude"), res.get("longitude"), res.get("municipio_ibge")],
        )
        if on_progress:
            on_progress(i, len(pendentes), cep, res)
        if pausa and i < len(pendentes):
            time.sleep(pausa)
    return stats
