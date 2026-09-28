#!/usr/bin/env python3
"""
Gera as tabelas auxiliares versionadas em src/dockdb_cnpj/data/.

- municipios_ibge.csv: código RF (TOM/SIAFI) → código IBGE, UF e centroide,
  a partir de kelvins/municipios-brasileiros (MIT).
- cnae_classes.csv: hierarquia CNAE 2.3 (classe → grupo → divisão → seção),
  a partir da API de CNAE do IBGE.

Só precisa rodar quando essas fontes mudarem; o resultado é commitado.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "src" / "dockdb_cnpj" / "data"

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

KELVINS = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv"
IBGE_CNAE = "https://servicodados.ibge.gov.br/api/v2/cnae/subclasses"


def _get_csv(url: str) -> list[dict[str, str]]:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))


def build_municipios() -> int:
    estados = {e["codigo_uf"]: e for e in _get_csv(f"{KELVINS}/estados.csv")}
    rows = []
    for m in _get_csv(f"{KELVINS}/municipios.csv"):
        uf = estados[m["codigo_uf"]]
        rows.append(
            {
                "codigo_rf": m["siafi_id"].zfill(4),
                "codigo_ibge": m["codigo_ibge"],
                "nome": m["nome"],
                "uf": uf["uf"],
                "regiao": uf["regiao"],
                "capital": m["capital"],
                "latitude": m["latitude"],
                "longitude": m["longitude"],
            }
        )
    rows.sort(key=lambda r: r["codigo_ibge"])
    dup = {r["codigo_rf"] for r in rows if sum(x["codigo_rf"] == r["codigo_rf"] for x in rows) > 1}
    if dup:
        raise RuntimeError(f"código RF duplicado na fonte: {sorted(dup)}")
    with (OUT_DIR / "municipios_ibge.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def build_cnae() -> int:
    r = requests.get(IBGE_CNAE, timeout=120)
    r.raise_for_status()
    classes: dict[str, dict[str, str]] = {}
    for sub in r.json():
        c = sub["classe"]
        g = c["grupo"]
        d = g["divisao"]
        s = d["secao"]
        classes[c["id"]] = {
            "classe": c["id"],
            "classe_desc": c["descricao"],
            "grupo": g["id"],
            "grupo_desc": g["descricao"],
            "divisao": d["id"],
            "divisao_desc": d["descricao"],
            "secao": s["id"],
            "secao_desc": s["descricao"],
        }
    rows = sorted(classes.values(), key=lambda x: x["classe"])
    with (OUT_DIR / "cnae_classes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"municipios_ibge.csv: {build_municipios()} linhas")
    print(f"cnae_classes.csv: {build_cnae()} linhas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
